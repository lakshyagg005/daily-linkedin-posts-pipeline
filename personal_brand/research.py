"""
personal_brand/research.py
---------------------------
Research module for Lakshya's personal-brand content engine.
Discovers topics from high-quality RSS feeds (TechCrunch AI, Startups, Venture,
VentureBeat, MIT Tech Review) and community signals (Reddit: r/startups,
r/Entrepreneur, r/SaaS, r/smallbusiness, r/indiehackers, r/artificial,
r/LocalLLaMA, r/technology, r/venturecapital).

Categorizes research across:
A. AI & Technology
B. Startups & Entrepreneurship
C. Business & Strategy
D. AI Business & Future of Work

Maintains 100% backward compatibility with orchestrator, content schemas,
deduplication logging, and test suites.
"""

from pathlib import Path
import json
import urllib.request
import urllib.error
import xml.etree.ElementTree as ET
import ssl
import re
import html
import datetime
import socket
from typing import List, Dict, Any, Optional

from .deduplication import PersonalBrandLog, jaccard_similarity

# SSL Context for HTTPS requests
SSL_CTX = ssl.create_default_context()
SSL_CTX.check_hostname = False
SSL_CTX.verify_mode = ssl.CERT_NONE

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
}

# The 4 Core Content Ecosystem Categories
CATEGORY_AI_TECH = "AI & Technology"
CATEGORY_STARTUPS = "Startups & Entrepreneurship"
CATEGORY_BUSINESS_STRATEGY = "Business & Strategy"
CATEGORY_AI_BUSINESS = "AI Business & Future of Work"

ALL_CATEGORIES = [
    CATEGORY_AI_TECH,
    CATEGORY_STARTUPS,
    CATEGORY_BUSINESS_STRATEGY,
    CATEGORY_AI_BUSINESS,
]

# High-Quality RSS Feeds (TechCrunch integration preserved & expanded across categories)
RSS_FEEDS = [
    {"name": "TechCrunch AI", "url": "https://techcrunch.com/category/artificial-intelligence/feed/", "type": "high_quality_journalism", "default_category": CATEGORY_AI_TECH},
    {"name": "TechCrunch Startups", "url": "https://techcrunch.com/category/startups/feed/", "type": "high_quality_journalism", "default_category": CATEGORY_STARTUPS},
    {"name": "TechCrunch Venture", "url": "https://techcrunch.com/category/venture/feed/", "type": "high_quality_journalism", "default_category": CATEGORY_STARTUPS},
    {"name": "VentureBeat AI", "url": "https://venturebeat.com/category/ai/feed/", "type": "high_quality_journalism", "default_category": CATEGORY_AI_TECH},
    {"name": "MIT Tech Review", "url": "https://www.technologyreview.com/feed/", "type": "high_quality_journalism", "default_category": CATEGORY_AI_TECH},
]

# Reddit subreddits for community discovery signals (Targeted expansion)
SUBREDDIT_CONFIGS = [
    {"subreddit": "startups", "default_category": CATEGORY_STARTUPS},
    {"subreddit": "Entrepreneur", "default_category": CATEGORY_STARTUPS},
    {"subreddit": "SaaS", "default_category": CATEGORY_BUSINESS_STRATEGY},
    {"subreddit": "smallbusiness", "default_category": CATEGORY_BUSINESS_STRATEGY},
    {"subreddit": "indiehackers", "default_category": CATEGORY_STARTUPS},
    {"subreddit": "artificial", "default_category": CATEGORY_AI_TECH},
    {"subreddit": "LocalLLaMA", "default_category": CATEGORY_AI_TECH},
    {"subreddit": "technology", "default_category": CATEGORY_AI_TECH},
    {"subreddit": "venturecapital", "default_category": CATEGORY_BUSINESS_STRATEGY},
    {"subreddit": "SideProject", "default_category": CATEGORY_STARTUPS},
    {"subreddit": "ChatGPT", "default_category": CATEGORY_AI_TECH},
]

# Preserved list of Reddit endpoints for backward compatibility
REDDIT_URLS = [
    {
        "url": f"https://www.reddit.com/r/{item['subreddit']}/top.json?limit=15&t=week&raw_json=1",
        "subreddit": f"r/{item['subreddit']}",
        "default_category": item["default_category"]
    }
    for item in SUBREDDIT_CONFIGS
]


def load_env_file(env_path: Optional[Path] = None) -> Dict[str, str]:
    """Parse .env file into key-value map without third-party dependencies."""
    if env_path is None:
        env_path = Path(__file__).resolve().parent.parent / ".env"

    env_vars = {}
    if env_path.exists():
        try:
            with open(env_path, "r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if line and not line.startswith("#") and "=" in line:
                        k, v = line.split("=", 1)
                        env_vars[k.strip()] = v.strip()
        except Exception:
            pass
    return env_vars


def classify_source_type(url: str, default_type: str = "high_quality_journalism") -> str:
    """Classify source URL into hierarchical quality tiers."""
    url_lower = url.lower()
    if "reddit.com" in url_lower or "twitter.com" in url_lower or "x.com" in url_lower:
        return "community_signal"
    if "arxiv.org" in url_lower or "nature.com" in url_lower or "paperswithcode.com" in url_lower:
        return "research_paper"
    if "github.com" in url_lower or "docs." in url_lower or "developer." in url_lower:
        return "official_docs"
    if any(domain in url_lower for domain in ["openai.com", "anthropic.com", "google.com", "microsoft.com", "apple.com", "meta.com", "stripe.com"]):
        return "official_company"
    if any(domain in url_lower for domain in ["gov", "census.gov", "bls.gov", "statista.com"]):
        return "gov_stat"
    if any(domain in url_lower for domain in ["gartner.com", "forrester.com", "mckinsey.com", "a16z.com"]):
        return "industry_report"
    return default_type


def classify_topic_category(title: str, summary: str = "", source_name: str = "") -> str:
    """
    Classifies content into one of 4 core ecosystem categories:
    A. AI & Technology
    B. Startups & Entrepreneurship
    C. Business & Strategy
    D. AI Business & Future of Work
    """
    combined = f"{title} {summary} {source_name}".lower()

    # Keyword sets
    ai_keywords = [
        "ai", "artificial intelligence", "llm", "large language model", "gpt",
        "claude", "gemini", "deepseek", "neural", "gpu", "localllama", "agent",
        "agents", "machine learning", "deep learning", "inference", "weights",
        "transformer", "open-source model", "prompt engineering", "context window"
    ]

    business_keywords = [
        "business model", "revenue", "pricing", "monetization", "growth strategy",
        "growth", "distribution", "unit economics", "margins", "gross margin",
        "profit", "profitable", "customer acquisition", "cac", "ltv", "churn",
        "retention", "marketing", "sales", "gtm", "go-to-market", "competitive advantage",
        "moat", "case study", "pricing tier", "annual recurring revenue", "arr", "mrr",
        "cash flow", "economics", "monetize"
    ]

    startup_keywords = [
        "startup", "startups", "founder", "founders", "seed round", "series a",
        "series b", "series c", "funding round", "venture capital", "vc", "accelerator",
        "incubator", "y combinator", "pitch", "pivot", "failure", "post-mortem",
        "co-founder", "equity", "mvp", "launch", "indie hacker", "side project",
        "indian startup", "india", "acquired by", "startup acquisition", "angel investor",
        "early-stage", "bootstrapped", "bootstrapping"
    ]

    future_work_keywords = [
        "future of work", "workforce", "automation", "productivity", "enterprise ai",
        "ai saas", "copilot", "coding assistant", "developer productivity",
        "job market", "replacing jobs", "ai startup", "ai product", "ai workflow"
    ]

    # Scoring matches
    ai_score = sum(1 for k in ai_keywords if re.search(rf"\b{re.escape(k)}\b", combined))
    biz_score = sum(1 for k in business_keywords if re.search(rf"\b{re.escape(k)}\b", combined))
    startup_score = sum(1 for k in startup_keywords if re.search(rf"\b{re.escape(k)}\b", combined))
    future_work_score = sum(1 for k in future_work_keywords if re.search(rf"\b{re.escape(k)}\b", combined))

    # 1. AI Business & Future of Work (Intersection of AI and Business/Startups/Work)
    if (ai_score > 0 and (biz_score > 0 or startup_score > 0)) or future_work_score > 0:
        return CATEGORY_AI_BUSINESS

    # 2. Score-based selection between Startups and Business
    if startup_score > biz_score and startup_score > 0:
        return CATEGORY_STARTUPS
    if biz_score > startup_score and biz_score > 0:
        return CATEGORY_BUSINESS_STRATEGY
    if startup_score > 0:
        return CATEGORY_STARTUPS
    if biz_score > 0:
        return CATEGORY_BUSINESS_STRATEGY

    # 3. AI & Technology
    if ai_score > 0:
        return CATEGORY_AI_TECH

    # Fallback to source-level default if keywords are neutral
    source_lower = source_name.lower()
    if "startup" in source_lower or "venture" in source_lower or "entrepreneur" in source_lower or "indie" in source_lower:
        return CATEGORY_STARTUPS
    if "saas" in source_lower or "smallbusiness" in source_lower:
        return CATEGORY_BUSINESS_STRATEGY
    if "ai" in source_lower or "tech" in source_lower or "artificial" in source_lower or "localllama" in source_lower:
        return CATEGORY_AI_TECH

    return CATEGORY_AI_TECH


def fetch_rss_articles(timeout: float = 10.0) -> List[Dict[str, Any]]:
    """Fetch raw news articles from RSS feeds reusing stdlib ElementTree logic."""
    articles = []
    for feed in RSS_FEEDS:
        req = urllib.request.Request(feed["url"], headers=HEADERS)
        try:
            with urllib.request.urlopen(req, context=SSL_CTX, timeout=timeout) as response:
                rss_content = response.read()
                root = ET.fromstring(rss_content)
                items = root.findall(".//item")
                for item in items[:8]:
                    title_el = item.find("title")
                    link_el = item.find("link")
                    desc_el = item.find("description")
                    pubdate_el = item.find("pubDate")

                    title = title_el.text.strip() if title_el is not None and title_el.text else ""
                    link = link_el.text.strip() if link_el is not None and link_el.text else ""
                    desc_html = desc_el.text if desc_el is not None and desc_el.text else ""
                    pubdate_str = pubdate_el.text.strip() if pubdate_el is not None and pubdate_el.text else ""

                    clean_desc = ""
                    if desc_html:
                        decoded = html.unescape(desc_html)
                        text_no_tags = re.sub(r"<[^>]+>", "", decoded)
                        clean_desc = re.sub(r"\s+", " ", text_no_tags).strip()

                    if title:
                        cat = classify_topic_category(title, clean_desc, feed["name"])
                        articles.append({
                            "title": title,
                            "url": link,
                            "summary": clean_desc[:280],
                            "source_name": feed["name"],
                            "source_type": classify_source_type(link, feed["type"]),
                            "category": cat,
                            "published_date": pubdate_str,
                        })
        except Exception:
            # Gracefully ignore individual feed failure
            pass

    return articles


def fetch_reddit_signals(timeout: float = 5.0) -> List[Dict[str, Any]]:
    """
    Fetch community discussion signals from Reddit public JSON endpoints.
    Resilient against rate limits (HTTP 429), timeouts, network errors, and malformed data.
    Gracefully returns whatever signals were collected, or empty list if unavailable.
    """
    signals = []
    for target in REDDIT_URLS:
        req = urllib.request.Request(target["url"], headers=HEADERS)
        try:
            with urllib.request.urlopen(req, context=SSL_CTX, timeout=timeout) as response:
                raw_bytes = response.read()
                data = json.loads(raw_bytes.decode("utf-8"))
                posts = data.get("data", {}).get("children", [])
                for p in posts[:8]:
                    pdata = p.get("data", {})
                    # Skip stickied announcements, deleted posts, or AutoModerator
                    if pdata.get("stickied") or pdata.get("over_18"):
                        continue
                    if pdata.get("author") in ("AutoModerator", "[deleted]"):
                        continue

                    title = pdata.get("title", "").strip()
                    ups = pdata.get("ups", 0)
                    num_comments = pdata.get("num_comments", 0)
                    permalink = "https://www.reddit.com" + pdata.get("permalink", "")
                    selftext = pdata.get("selftext", "").strip()
                    created_utc = pdata.get("created_utc")

                    # Convert created_utc to ISO date if present
                    pub_date = ""
                    if created_utc:
                        try:
                            pub_date = datetime.datetime.fromtimestamp(created_utc, tz=datetime.timezone.utc).strftime("%Y-%m-%d")
                        except Exception:
                            pub_date = ""

                    # Require meaningful community engagement (> 30 upvotes or > 10 comments)
                    if title and (ups >= 30 or num_comments >= 10):
                        summary_text = selftext[:280] if selftext else title
                        cat = classify_topic_category(title, summary_text, target["subreddit"])
                        signals.append({
                            "title": title,
                            "url": permalink,
                            "summary": summary_text,
                            "source_name": target["subreddit"],
                            "source_type": "community_signal",
                            "score": ups,
                            "num_comments": num_comments,
                            "category": cat,
                            "published_date": pub_date,
                            "is_community_signal": True
                        })
        except urllib.error.HTTPError as http_err:
            if http_err.code == 429:
                # Rate limited: halt further Reddit requests for this cycle to respect rate limits
                break
            continue
        except (socket.timeout, urllib.error.URLError, json.JSONDecodeError, Exception):
            # Gracefully skip failed subreddit
            continue

    return signals


def create_research_candidate(
    topic: str,
    why_now: str,
    potential_angle: str,
    thesis: str,
    category: str,
    sources: List[Dict[str, str]],
    platform_fit: Optional[List[str]] = None
) -> Dict[str, Any]:
    """Factory creating a standard research candidate dictionary."""
    return {
        "topic": topic,
        "why_now": why_now,
        "potential_angle": potential_angle,
        "thesis": thesis,
        "category": category,
        "sources": sources,
        "platform_fit": platform_fit or ["linkedin", "x"]
    }


def _get_category_angle(category: str) -> str:
    """Generate a category-tailored angle for the content candidate."""
    if category == CATEGORY_STARTUPS:
        return "Key strategic and operational lesson for early-stage founders, builders, and entrepreneurs."
    if category == CATEGORY_BUSINESS_STRATEGY:
        return "Breakdown of unit economics, distribution strategy, and sustainable monetization moats."
    if category == CATEGORY_AI_BUSINESS:
        return "Commercial implications and practical market opportunities for entrepreneurs deploying AI."
    return "Impact of this technical shift on software builders, engineers, and product strategy."


def generate_research_candidates(
    dedup_log: Optional[PersonalBrandLog] = None,
    max_candidates: int = 5
) -> List[Dict[str, Any]]:
    """
    Gathers raw feed items and community signals, filters out recent duplicates,
    enforces cross-source deduplication, balances category diversity,
    and formats them into structured research candidates.
    """
    if dedup_log is None:
        dedup_log = PersonalBrandLog()

    rss_items = fetch_rss_articles()
    reddit_items = fetch_reddit_signals()

    # Track seen topics in this run to avoid cross-source duplicates
    seen_candidate_topics: List[str] = []
    candidates: List[Dict[str, Any]] = []

    # Helper for cross-source and in-run deduplication
    def is_already_seen(title: str) -> bool:
        for st in seen_candidate_topics:
            if jaccard_similarity(title, st) > 0.40:
                return True
        return False

    # Retrieve recent categories from dedup log to maintain balanced mix over time
    recent_entries = dedup_log.get_recent_entries(days=14)
    recent_category_counts: Dict[str, int] = {cat: 0 for cat in ALL_CATEGORIES}
    for re_entry in recent_entries:
        cat = re_entry.get("category")
        if cat in recent_category_counts:
            recent_category_counts[cat] += 1

    # Pool all items: RSS items (journalism) first, then Reddit signals (community)
    all_raw_items = []
    for it in rss_items:
        it["is_reddit"] = False
        all_raw_items.append(it)
    for it in reddit_items:
        it["is_reddit"] = True
        all_raw_items.append(it)

    # Sort available candidates by under-represented categories to ensure healthy diversity
    def category_priority(item: Dict[str, Any]) -> int:
        cat = item.get("category", CATEGORY_AI_TECH)
        # Lower count in recent days gets higher priority (smaller sort key)
        return recent_category_counts.get(cat, 0)

    # Secondary sort: prefer high-quality journalism first, then by community engagement score
    def item_score(item: Dict[str, Any]) -> int:
        if not item.get("is_reddit", False):
            return 1000
        return item.get("score", 0)

    # Partition items by category to facilitate stratified selection
    categorized_pools: Dict[str, List[Dict[str, Any]]] = {cat: [] for cat in ALL_CATEGORIES}
    for item in all_raw_items:
        cat = item.get("category", CATEGORY_AI_TECH)
        if cat not in categorized_pools:
            cat = CATEGORY_AI_TECH
        categorized_pools[cat].append(item)

    # Order categories so least-represented category in recent history is picked first
    sorted_categories = sorted(ALL_CATEGORIES, key=lambda c: recent_category_counts.get(c, 0))

    # Stratified candidate selection across categories
    added = True
    while len(candidates) < max_candidates and added:
        added = False
        for target_cat in sorted_categories:
            if len(candidates) >= max_candidates:
                break
            pool = categorized_pools[target_cat]
            while pool:
                item = pool.pop(0)
                topic_title = item["title"]

                # 1. 30-day log deduplication check
                is_dup, _, _ = dedup_log.is_topic_similar(topic_title)
                if is_dup:
                    continue

                # 2. In-run cross-source deduplication check
                if is_already_seen(topic_title):
                    continue

                # Build candidate
                is_reddit = item.get("is_reddit", False)
                if is_reddit:
                    why_now = (
                        f"Active community debate on {item['source_name']} "
                        f"({item.get('score', 0)} upvotes, {item.get('num_comments', 0)} comments). "
                        "Note: Community sentiment signal, not verified fact."
                    )
                    thesis = f"Community discussion around {topic_title}: {item['summary'][:160]}"
                else:
                    why_now = f"Featured in recent coverage on {item['source_name']}."
                    thesis = item["summary"] if item["summary"] else topic_title

                src_dict = {
                    "title": item["title"],
                    "url": item["url"],
                    "source_type": item["source_type"]
                }
                if item.get("published_date"):
                    src_dict["published_date"] = item["published_date"]

                candidate = create_research_candidate(
                    topic=topic_title,
                    why_now=why_now,
                    potential_angle=_get_category_angle(target_cat),
                    thesis=thesis,
                    category=target_cat,
                    sources=[src_dict],
                    platform_fit=["linkedin", "x"]
                )

                candidates.append(candidate)
                seen_candidate_topics.append(topic_title)
                recent_category_counts[target_cat] += 1
                added = True
                break

    # If candidates still under max_candidates, fill with any remaining non-duplicate items
    if len(candidates) < max_candidates:
        for item in all_raw_items:
            topic_title = item["title"]
            is_dup, _, _ = dedup_log.is_topic_similar(topic_title)
            if is_dup or is_already_seen(topic_title):
                continue

            target_cat = item.get("category", CATEGORY_AI_TECH)
            is_reddit = item.get("is_reddit", False)
            if is_reddit:
                why_now = (
                    f"Active community debate on {item['source_name']} "
                    f"({item.get('score', 0)} upvotes). Note: Community sentiment signal."
                )
                thesis = f"Community discussion: {topic_title}"
            else:
                why_now = f"Featured in recent coverage on {item['source_name']}."
                thesis = item["summary"] if item["summary"] else topic_title

            src_dict = {
                "title": item["title"],
                "url": item["url"],
                "source_type": item["source_type"]
            }
            if item.get("published_date"):
                src_dict["published_date"] = item["published_date"]

            candidate = create_research_candidate(
                topic=topic_title,
                why_now=why_now,
                potential_angle=_get_category_angle(target_cat),
                thesis=thesis,
                category=target_cat,
                sources=[src_dict],
                platform_fit=["linkedin", "x"]
            )
            candidates.append(candidate)
            seen_candidate_topics.append(topic_title)
            if len(candidates) >= max_candidates:
                break

    return candidates


def save_research_artifacts(
    candidates: List[Dict[str, Any]],
    date_str: Optional[str] = None
) -> Path:
    """Save candidates into content/research/YYYY-MM-DD/research_candidates.json."""
    if date_str is None:
        date_str = datetime.date.today().isoformat()

    root_dir = Path(__file__).resolve().parent.parent
    target_dir = root_dir / "content" / "research" / date_str
    target_dir.mkdir(parents=True, exist_ok=True)

    target_file = target_dir / "research_candidates.json"

    output_data = {
        "date": date_str,
        "count": len(candidates),
        "candidates": candidates
    }

    with open(target_file, "w", encoding="utf-8") as f:
        json.dump(output_data, f, indent=2, ensure_ascii=False)

    return target_file
