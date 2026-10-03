"""
personal_brand/research.py
---------------------------
Research module for Lakshya's personal-brand content engine.
Discovers topics from high-quality RSS feeds and community signals (Reddit),
classifies sources, applies topic filtering & deduplication, and writes outputs
to content/research/YYYY-MM-DD/research_candidates.json.
"""

from pathlib import Path
import json
import urllib.request
import xml.etree.ElementTree as ET
import ssl
import re
import html
import datetime
from typing import List, Dict, Any, Optional

from .deduplication import PersonalBrandLog

# SSL Context for HTTPS requests
SSL_CTX = ssl.create_default_context()
SSL_CTX.check_hostname = False
SSL_CTX.verify_mode = ssl.CERT_NONE

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
}

# High-Quality RSS Feeds
RSS_FEEDS = [
    {"name": "TechCrunch AI", "url": "https://techcrunch.com/category/artificial-intelligence/feed/", "type": "high_quality_journalism"},
    {"name": "VentureBeat AI", "url": "https://venturebeat.com/category/ai/feed/", "type": "high_quality_journalism"},
    {"name": "MIT Tech Review", "url": "https://www.technologyreview.com/feed/", "type": "high_quality_journalism"},
]

# Reddit subreddits for community discovery signals
REDDIT_URLS = [
    {"url": "https://www.reddit.com/r/artificial/top.json?limit=15&t=week&raw_json=1", "subreddit": "r/artificial"},
    {"url": "https://www.reddit.com/r/ChatGPT/top.json?limit=15&t=week&raw_json=1", "subreddit": "r/ChatGPT"},
    {"url": "https://www.reddit.com/r/startups/top.json?limit=15&t=week&raw_json=1", "subreddit": "r/startups"},
    {"url": "https://www.reddit.com/r/SideProject/top.json?limit=15&t=week&raw_json=1", "subreddit": "r/SideProject"},
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


def fetch_rss_articles() -> List[Dict[str, Any]]:
    """Fetch raw news articles from RSS feeds reusing stdlib ElementTree logic."""
    articles = []
    for feed in RSS_FEEDS:
        req = urllib.request.Request(feed["url"], headers=HEADERS)
        try:
            with urllib.request.urlopen(req, context=SSL_CTX, timeout=10) as response:
                rss_content = response.read()
                root = ET.fromstring(rss_content)
                items = root.findall(".//item")
                for item in items[:8]:
                    title_el = item.find("title")
                    link_el = item.find("link")
                    desc_el = item.find("description")

                    title = title_el.text.strip() if title_el is not None and title_el.text else ""
                    link = link_el.text.strip() if link_el is not None and link_el.text else ""
                    desc_html = desc_el.text if desc_el is not None and desc_el.text else ""

                    clean_desc = ""
                    if desc_html:
                        decoded = html.unescape(desc_html)
                        text_no_tags = re.sub(r"<[^>]+>", "", decoded)
                        clean_desc = re.sub(r"\s+", " ", text_no_tags).strip()

                    if title:
                        articles.append({
                            "title": title,
                            "url": link,
                            "summary": clean_desc[:250],
                            "source_name": feed["name"],
                            "source_type": classify_source_type(link, feed["type"])
                        })
        except Exception:
            pass

    return articles


def fetch_reddit_signals() -> List[Dict[str, Any]]:
    """Fetch community discussion signals from Reddit using fallback JSON endpoint."""
    signals = []
    for target in REDDIT_URLS:
        req = urllib.request.Request(target["url"], headers=HEADERS)
        try:
            with urllib.request.urlopen(req, context=SSL_CTX, timeout=10) as response:
                data = json.loads(response.read().decode("utf-8"))
                posts = data.get("data", {}).get("children", [])
                for p in posts[:6]:
                    pdata = p.get("data", {})
                    title = pdata.get("title", "")
                    ups = pdata.get("ups", 0)
                    permalink = "https://www.reddit.com" + pdata.get("permalink", "")
                    selftext = pdata.get("selftext", "")

                    if title and ups > 50:
                        signals.append({
                            "title": title,
                            "url": permalink,
                            "summary": selftext[:200] if selftext else title,
                            "source_name": target["subreddit"],
                            "source_type": "community_signal",
                            "score": ups
                        })
        except Exception:
            pass

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


def generate_research_candidates(
    dedup_log: Optional[PersonalBrandLog] = None,
    max_candidates: int = 5
) -> List[Dict[str, Any]]:
    """
    Gathers raw feed items and community signals, filters out recent duplicates,
    and formats them into structured research candidates.
    """
    if dedup_log is None:
        dedup_log = PersonalBrandLog()

    rss_items = fetch_rss_articles()
    reddit_items = fetch_reddit_signals()

    candidates: List[Dict[str, Any]] = []

    # Process RSS Items (Higher factual priority)
    for item in rss_items:
        topic_title = item["title"]

        # Check deduplication against last 30 days
        is_dup, _, _ = dedup_log.is_topic_similar(topic_title)
        if is_dup:
            continue

        candidate = create_research_candidate(
            topic=topic_title,
            why_now=f"Featured in recent coverage on {item['source_name']}.",
            potential_angle="Impact of this technical shift on software builders and product strategy.",
            thesis=item["summary"] if item["summary"] else topic_title,
            category="AI",
            sources=[{
                "title": item["title"],
                "url": item["url"],
                "source_type": item["source_type"]
            }],
            platform_fit=["linkedin", "x"]
        )
        candidates.append(candidate)
        if len(candidates) >= max_candidates:
            break

    # Process Reddit items if candidate pool is under max
    if len(candidates) < max_candidates:
        for r_item in reddit_items:
            topic_title = r_item["title"]
            is_dup, _, _ = dedup_log.is_topic_similar(topic_title)
            if is_dup:
                continue

            candidate = create_research_candidate(
                topic=topic_title,
                why_now=f"High community engagement on {r_item['source_name']} ({r_item['score']} upvotes).",
                potential_angle="Counterintuitive developer observation from public builder discussions.",
                thesis=f"Community insight around {topic_title}",
                category="Technology",
                sources=[{
                    "title": r_item["title"],
                    "url": r_item["url"],
                    "source_type": "community_signal"
                }],
                platform_fit=["linkedin", "x"]
            )
            candidates.append(candidate)
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
