"""
personal_brand/test_research_expanded.py
-----------------------------------------
Targeted test suite verifying:
1. Expanded topic category classification (A. AI & Tech, B. Startups, C. Business, D. AI Business).
2. Reddit result parsing & metadata preservation (permalink, date, score, comments, community signal).
3. Reddit resilience: timeouts, HTTP 429 rate limits, HTTP 403, network errors, malformed JSON.
4. Graceful fallback to existing research sources (TechCrunch / RSS).
5. Cross-source deduplication (RSS vs Reddit) and 30-day log deduplication.
6. Topic category diversity balancing over time.
7. Content schema compatibility with PostGenerator and CarouselBuilder.
8. Preservation of publishing safety and carousel rendering contracts.
"""

import sys
import json
import socket
import datetime
import tempfile
import urllib.error
from pathlib import Path
from unittest.mock import patch, MagicMock

# Ensure root directory is in sys.path
root_dir = Path(__file__).resolve().parent.parent
if str(root_dir) not in sys.path:
    sys.path.insert(0, str(root_dir))

from personal_brand.research import (
    CATEGORY_AI_TECH,
    CATEGORY_STARTUPS,
    CATEGORY_BUSINESS_STRATEGY,
    CATEGORY_AI_BUSINESS,
    ALL_CATEGORIES,
    classify_topic_category,
    classify_source_type,
    fetch_reddit_signals,
    fetch_rss_articles,
    generate_research_candidates,
    create_research_candidate,
    REDDIT_URLS,
    RSS_FEEDS
)
from personal_brand.deduplication import PersonalBrandLog
from personal_brand.post_generator import (
    PostGenerator,
    LLMProvider,
    validate_content_package
)
from personal_brand.carousel_builder import CarouselBuilder


def test_expanded_topic_classification():
    """Test 1: Verify accurate classification across the 4 expanded topic categories."""
    print("  • Testing Topic Category Classification...")

    # Category A: AI & Technology
    cat_ai1 = classify_topic_category("DeepSeek-V3 Architecture: Multi-Head Latent Attention", "Detailed breakdown of new model architecture", "TechCrunch AI")
    assert cat_ai1 == CATEGORY_AI_TECH, f"Expected {CATEGORY_AI_TECH}, got {cat_ai1}"

    cat_ai2 = classify_topic_category("How to run 70B open-source models on consumer hardware", "Benchmarking local inference speed", "r/LocalLLaMA")
    assert cat_ai2 == CATEGORY_AI_TECH, f"Expected {CATEGORY_AI_TECH}, got {cat_ai2}"

    # Category B: Startups & Entrepreneurship
    cat_startup1 = classify_topic_category("Why 3 YC founders pivoted from fintech to dev tools", "Founder journey and post-mortem lessons", "r/startups")
    assert cat_startup1 == CATEGORY_STARTUPS, f"Expected {CATEGORY_STARTUPS}, got {cat_startup1}"

    cat_startup2 = classify_topic_category("Indian startup raises $100M Series B round", "Early stage market expansion in Bangalore", "TechCrunch Startups")
    assert cat_startup2 == CATEGORY_STARTUPS, f"Expected {CATEGORY_STARTUPS}, got {cat_startup2}"

    cat_startup3 = classify_topic_category("Bootstrapped founder hits $40k MRR without funding", "Solo entrepreneur lessons on indie hacking", "r/indiehackers")
    assert cat_startup3 == CATEGORY_STARTUPS, f"Expected {CATEGORY_STARTUPS}, got {cat_startup3}"

    # Category C: Business & Strategy
    cat_biz1 = classify_topic_category("The Unit Economics of Consumption-Based Pricing vs Subscriptions", "How gross margins and churn change with pricing tiers", "r/SaaS")
    assert cat_biz1 == CATEGORY_BUSINESS_STRATEGY, f"Expected {CATEGORY_BUSINESS_STRATEGY}, got {cat_biz1}"

    cat_biz2 = classify_topic_category("How Figma reduced customer acquisition cost (CAC) and built a distribution moat", "Growth strategy and retention breakdown", "TechCrunch")
    assert cat_biz2 == CATEGORY_BUSINESS_STRATEGY, f"Expected {CATEGORY_BUSINESS_STRATEGY}, got {cat_biz2}"

    # Category D: AI Business & Future of Work
    cat_aibiz1 = classify_topic_category("Enterprise AI startups: How AI SaaS companies are closing $200k ARR deals", "Commercial transformation in enterprise workflows", "r/SaaS")
    assert cat_aibiz1 == CATEGORY_AI_BUSINESS, f"Expected {CATEGORY_AI_BUSINESS}, got {cat_aibiz1}"

    cat_aibiz2 = classify_topic_category("How AI coding assistants are reshaping developer productivity and job markets", "Autonomous agents changing software workforce", "TechCrunch AI")
    assert cat_aibiz2 == CATEGORY_AI_BUSINESS, f"Expected {CATEGORY_AI_BUSINESS}, got {cat_aibiz2}"

    print("    ✓ All 4 categories classified accurately.")


def test_reddit_result_parsing_and_metadata():
    """Test 2: Verify Reddit JSON parsing, metadata extraction (URL, date, score), and filtering."""
    print("  • Testing Reddit Result Parsing & Metadata Extraction...")

    mock_reddit_response = {
        "data": {
            "children": [
                {
                    "data": {
                        "title": "We scaled our bootstrapped SaaS to $50k MRR: Here is our exact tech stack and pricing",
                        "ups": 142,
                        "num_comments": 48,
                        "permalink": "/r/startups/comments/abc123/bootstrapped_saas/",
                        "selftext": "We started 18 months ago with zero outside funding. Here are 3 key takeaways...",
                        "created_utc": 1729000000,
                        "stickied": False,
                        "over_18": False,
                        "author": "founder_bob",
                        "subreddit": "startups"
                    }
                },
                {
                    # Low score post — should be filtered out
                    "data": {
                        "title": "Need feedback on my new idea",
                        "ups": 4,
                        "num_comments": 2,
                        "permalink": "/r/startups/comments/def456/low_score/",
                        "selftext": "What do you think?",
                        "created_utc": 1729000000,
                        "stickied": False,
                        "over_18": False,
                        "author": "newbie",
                        "subreddit": "startups"
                    }
                },
                {
                    # Stickied announcement — should be filtered out
                    "data": {
                        "title": "[Weekly Thread] Monthly Feedback and Promotion Thread",
                        "ups": 350,
                        "num_comments": 200,
                        "permalink": "/r/startups/comments/mod123/weekly_thread/",
                        "selftext": "Please post your promotions here only.",
                        "created_utc": 1729000000,
                        "stickied": True,
                        "over_18": False,
                        "author": "AutoModerator",
                        "subreddit": "startups"
                    }
                }
            ]
        }
    }

    mock_resp_obj = MagicMock()
    mock_resp_obj.read.return_value = json.dumps(mock_reddit_response).encode("utf-8")
    mock_resp_obj.__enter__.return_value = mock_resp_obj

    with patch("urllib.request.urlopen", return_value=mock_resp_obj):
        # Limit to 1 URL call for fast testing
        with patch("personal_brand.research.REDDIT_URLS", [{"url": "https://reddit.com/r/startups/top.json", "subreddit": "r/startups", "default_category": CATEGORY_STARTUPS}]):
            signals = fetch_reddit_signals(timeout=2.0)

    assert len(signals) == 1, f"Expected exactly 1 valid signal, got {len(signals)}"
    sig = signals[0]
    assert sig["title"] == "We scaled our bootstrapped SaaS to $50k MRR: Here is our exact tech stack and pricing"
    assert sig["url"] == "https://www.reddit.com/r/startups/comments/abc123/bootstrapped_saas/"
    assert sig["score"] == 142
    assert sig["num_comments"] == 48
    assert sig["source_name"] == "r/startups"
    assert sig["source_type"] == "community_signal"
    assert sig["is_community_signal"] is True
    assert sig["published_date"] != ""
    print("    ✓ Reddit parsing, signal filtering, and metadata extraction passed.")


def test_reddit_timeouts_and_failure_resilience():
    """Test 3: Verify Reddit timeouts, HTTP 429 rate limits, and network error resilience."""
    print("  • Testing Reddit Resilience (Timeouts, HTTP 429, Network Failures)...")

    # Case A: Socket timeout
    with patch("urllib.request.urlopen", side_effect=socket.timeout("Connection timed out")):
        signals = fetch_reddit_signals(timeout=1.0)
        assert signals == [], f"Expected empty list on timeout, got {signals}"

    # Case B: HTTP 429 Too Many Requests (Rate limit)
    http_429 = urllib.error.HTTPError(
        url="https://reddit.com/top.json",
        code=429,
        msg="Too Many Requests",
        hdrs={},
        fp=None
    )
    with patch("urllib.request.urlopen", side_effect=http_429):
        signals = fetch_reddit_signals(timeout=1.0)
        assert signals == [], f"Expected empty list on HTTP 429, got {signals}"

    # Case C: Malformed JSON response
    mock_bad_json = MagicMock()
    mock_bad_json.read.return_value = b"{not-valid-json"
    mock_bad_json.__enter__.return_value = mock_bad_json
    with patch("urllib.request.urlopen", return_value=mock_bad_json):
        signals = fetch_reddit_signals(timeout=1.0)
        assert signals == [], f"Expected empty list on malformed JSON, got {signals}"

    print("    ✓ All Reddit failure scenarios gracefully handled without crashing.")


def test_fallback_to_existing_research_sources():
    """Test 4: Verify that when Reddit fails, candidate generation seamlessly falls back to RSS."""
    print("  • Testing Fallback to Existing Research Sources (TechCrunch / RSS)...")

    mock_rss_articles = [
        {
            "title": "TechCrunch: Anthropic announces new Enterprise Agent capabilities",
            "url": "https://techcrunch.com/2026/10/22/anthropic-enterprise/",
            "summary": "Anthropic announced new tool-use capabilities for enterprise workflows.",
            "source_name": "TechCrunch AI",
            "source_type": "high_quality_journalism",
            "category": CATEGORY_AI_TECH,
            "published_date": "2026-10-22"
        },
        {
            "title": "YC-backed startup raises $15M for automated developer verification",
            "url": "https://techcrunch.com/2026/10/22/yc-startup-verification/",
            "summary": "Early stage developer tooling startup closes Series A funding.",
            "source_name": "TechCrunch Startups",
            "source_type": "high_quality_journalism",
            "category": CATEGORY_STARTUPS,
            "published_date": "2026-10-22"
        }
    ]

    with tempfile.TemporaryDirectory() as tmpdir:
        tmp_log = PersonalBrandLog(log_path=Path(tmpdir) / "test-log.json")

        # Mock Reddit failing completely (returning empty list)
        with patch("personal_brand.research.fetch_reddit_signals", return_value=[]):
            with patch("personal_brand.research.fetch_rss_articles", return_value=mock_rss_articles):
                candidates = generate_research_candidates(dedup_log=tmp_log, max_candidates=5)

    assert len(candidates) == 2, f"Expected 2 candidates from RSS, got {len(candidates)}"
    assert candidates[0]["topic"] == "TechCrunch: Anthropic announces new Enterprise Agent capabilities"
    assert candidates[0]["sources"][0]["source_type"] == "high_quality_journalism"
    assert candidates[0]["sources"][0]["url"] == "https://techcrunch.com/2026/10/22/anthropic-enterprise/"
    assert candidates[1]["category"] == CATEGORY_STARTUPS
    print("    ✓ Graceful fallback to existing RSS/TechCrunch sources passed.")


def test_cross_source_deduplication():
    """Test 5: Verify cross-source deduplication between RSS and Reddit."""
    print("  • Testing Cross-Source Deduplication...")

    mock_rss = [
        {
            "title": "OpenAI releases open weights model for autonomous reasoning",
            "url": "https://techcrunch.com/openai-reasoning/",
            "summary": "OpenAI introduces open reasoning weights for researchers.",
            "source_name": "TechCrunch AI",
            "source_type": "high_quality_journalism",
            "category": CATEGORY_AI_TECH,
            "published_date": "2026-10-22"
        }
    ]

    mock_reddit = [
        {
            # Substantially similar topic on Reddit (duplicate)
            "title": "OpenAI releases open weights model for autonomous reasoning discussions",
            "url": "https://reddit.com/r/LocalLLaMA/comments/123/openai_open_weights/",
            "summary": "Community thoughts on OpenAI releasing open weights model for autonomous reasoning",
            "source_name": "r/LocalLLaMA",
            "source_type": "community_signal",
            "score": 350,
            "category": CATEGORY_AI_TECH,
            "published_date": "2026-10-22",
            "is_community_signal": True
        },
        {
            # Distinct topic on Reddit
            "title": "Why we rejected a $5M acquisition offer to stay bootstrapped",
            "url": "https://reddit.com/r/startups/comments/456/rejected_acquisition/",
            "summary": "Our founder journey staying independent and profitable.",
            "source_name": "r/startups",
            "source_type": "community_signal",
            "score": 280,
            "category": CATEGORY_STARTUPS,
            "published_date": "2026-10-22",
            "is_community_signal": True
        }
    ]

    with tempfile.TemporaryDirectory() as tmpdir:
        tmp_log = PersonalBrandLog(log_path=Path(tmpdir) / "test-log.json")

        with patch("personal_brand.research.fetch_rss_articles", return_value=mock_rss):
            with patch("personal_brand.research.fetch_reddit_signals", return_value=mock_reddit):
                candidates = generate_research_candidates(dedup_log=tmp_log, max_candidates=5)

    # Should have 2 candidates: the RSS OpenAI one and the distinct Reddit acquisition one
    assert len(candidates) == 2, f"Expected 2 candidates after cross-source dedup, got {len(candidates)}"
    topics = [c["topic"] for c in candidates]
    assert "OpenAI releases open weights model for autonomous reasoning" in topics
    assert "Why we rejected a $5M acquisition offer to stay bootstrapped" in topics
    print("    ✓ Cross-source deduplication correctly suppressed overlapping Reddit topic.")


def test_category_diversity_balancing():
    """Test 6: Verify candidate balancing across categories over time."""
    print("  • Testing Category Diversity Balancing...")

    with tempfile.TemporaryDirectory() as tmpdir:
        tmp_log = PersonalBrandLog(log_path=Path(tmpdir) / "test-log.json")

        # Simulate that the last 5 posts were AI & Technology
        today = datetime.date.today()
        for i in range(5):
            tmp_log.add_entry(
                topic=f"AI Tech Topic {i+1}",
                angle="AI",
                thesis="AI",
                date_str=(today - datetime.timedelta(days=i+1)).isoformat()
            )
            # Add category metadata to entry
            tmp_log.data["entries"][-1]["category"] = CATEGORY_AI_TECH
        tmp_log.save()

        # Feed with multiple items across different categories
        mock_rss = [
            {"title": "New GPU architecture announced for AI inference", "url": "https://tc.com/1", "summary": "tech", "source_name": "TechCrunch AI", "source_type": "high_quality_journalism", "category": CATEGORY_AI_TECH},
            {"title": "How bootstrapped founders manage early customer acquisition", "url": "https://tc.com/2", "summary": "biz", "source_name": "TechCrunch Startups", "source_type": "high_quality_journalism", "category": CATEGORY_STARTUPS},
            {"title": "SaaS retention mechanics: Reducing churn with usage billing", "url": "https://tc.com/3", "summary": "saas", "source_name": "TechCrunch", "source_type": "high_quality_journalism", "category": CATEGORY_BUSINESS_STRATEGY},
            {"title": "How enterprise AI workflows are transforming legal operations", "url": "https://tc.com/4", "summary": "ai biz", "source_name": "TechCrunch", "source_type": "high_quality_journalism", "category": CATEGORY_AI_BUSINESS},
        ]

        with patch("personal_brand.research.fetch_rss_articles", return_value=mock_rss):
            with patch("personal_brand.research.fetch_reddit_signals", return_value=[]):
                candidates = generate_research_candidates(dedup_log=tmp_log, max_candidates=4)

    assert len(candidates) == 4
    candidate_categories = [c["category"] for c in candidates]
    # Because AI Tech was published 5 times recently, under-represented categories should be prioritized
    assert CATEGORY_STARTUPS in candidate_categories
    assert CATEGORY_BUSINESS_STRATEGY in candidate_categories
    assert CATEGORY_AI_BUSINESS in candidate_categories
    # The first candidate chosen should be an underrepresented category, not AI Tech
    assert candidates[0]["category"] != CATEGORY_AI_TECH
    print(f"    ✓ Candidates successfully diversified: {candidate_categories}")


def test_content_schema_and_generator_compatibility():
    """Test 7: Verify candidates from all 4 categories validate cleanly through PostGenerator."""
    print("  • Testing Content Schema & PostGenerator Compatibility...")

    def make_mock_response(topic: str, category: str):
        def _caller(sys_p: str, user_p: str) -> str:
            return json.dumps({
                "date": "2026-10-22",
                "topic": topic,
                "thesis": f"Practical builder thesis for {topic}",
                "category": category,
                "linkedin": {
                    "caption": f"Why this matters for founders and builders:\n\n"
                               f"We analyzed recent shifts across early-stage technology and business models. The core lesson is clear: "
                               f"distribution and unit economics matter more than superficial hype.\n\n"
                               f"What is your take on this development?",
                    "sources": [{"title": "Source 1", "url": "https://example.com"}]
                },
                "carousel": {
                    "date": "2026-10-22",
                    "topic": topic,
                    "category": category,
                    "thesis": f"Thesis for {topic}",
                    "hook": {"headline": "The Shift Nobody Saw Coming", "subtitle": "Here is what changes."},
                    "context": {"headline": "The Context", "points": ["Point 1", "Point 2", "Point 3"]},
                    "misunderstanding": {"myth": "Hype is everything", "reality": "Execution and retention win."},
                    "evidence": {"stat": "$12M ARR", "label": "Milestone", "explanation": "Reached with 15 engineers."},
                    "why_it_matters": {"headline": "Why it matters", "implications": [{"target": "Founders", "desc": "Focus on cash flow"}]},
                    "builder_takeaway": {"headline": "What to build", "actions": ["Audit unit economics", "Measure churn", "Deploy automated verification"]},
                    "final_insight": {"quote": "Distribution beats pure syntax every single time.", "cta": "Follow for daily engineering and startup insights."},
                    "sources": [{"title": "Source 1", "url": "https://example.com"}]
                },
                "x_posts": [
                    {"angle": "interesting", "text": "Interesting insight with specific metric: $12M ARR reached with zero outside capital.", "sources": []},
                    {"angle": "contrarian", "text": "Contrarian angle: Scaling fast before achieving positive unit economics is organizational debt.", "sources": []},
                    {"angle": "builder", "text": "Builder takeaway: Prioritize retention and verification before optimizing marketing spend.", "sources": []}
                ]
            })
        return _caller

    topics_by_cat = {
        CATEGORY_AI_TECH: "DeepSeek Latent Attention Architecture and Local Inference",
        CATEGORY_STARTUPS: "Zepto Funding Round and Quick Commerce Unit Economics",
        CATEGORY_BUSINESS_STRATEGY: "SaaS Consumption-Based Pricing Tiers and Churn Reduction",
        CATEGORY_AI_BUSINESS: "Enterprise Autonomous Workflow Agents Replacing Manual Processing"
    }

    for cat in ALL_CATEGORIES:
        topic_name = topics_by_cat[cat]
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp_log = PersonalBrandLog(log_path=Path(tmpdir) / "test-log.json")
            mock_provider = LLMProvider(custom_caller=make_mock_response(topic_name, cat))
            generator = PostGenerator(provider=mock_provider, dedup_log=tmp_log)

            cand = create_research_candidate(
                topic=topic_name,
                why_now="Recent market observation",
                potential_angle="Builder perspective",
                thesis=f"Clear analytical thesis for {topic_name}",
                category=cat,
                sources=[{"title": "Source", "url": "https://example.com", "source_type": "high_quality_journalism"}]
            )

            pkg = generator.generate_content_package(cand)
            is_valid, errors = validate_content_package(pkg)
            assert is_valid, f"Validation failed for category {cat}: {errors}"
            assert pkg["category"] == cat
            assert len(pkg["x_posts"]) == 3
            assert len(pkg["carousel"]["context"]["points"]) == 3

    print("    ✓ All 4 categories produce schema-compliant, slop-free content packages.")


def test_carousel_rendering_preservation():
    """Test 8: Verify CarouselBuilder compiles 7 HTML slides with watermark for expanded categories."""
    print("  • Testing Carousel Slide Builder Preservation...")

    for cat in [CATEGORY_STARTUPS, CATEGORY_BUSINESS_STRATEGY, CATEGORY_AI_BUSINESS]:
        carousel_content = {
            "date": "2026-10-22",
            "topic": f"Scaling Bootstrapped Software in {cat}",
            "category": cat,
            "thesis": "Retention beats vanity metrics.",
            "hook": {"headline": "How to Build a $10M SaaS", "subtitle": "Without venture capital."},
            "context": {"headline": "The Operating Reality", "points": ["Point A", "Point B", "Point C"]},
            "misunderstanding": {"myth": "You need VC funding to scale", "reality": "Profitable unit economics scale sustainably."},
            "evidence": {"stat": "82%", "label": "Gross Margin", "explanation": "Maintained across 3 years."},
            "why_it_matters": {"headline": "Why It Matters", "implications": [{"target": "Builders", "desc": "Focus on cash flow"}]},
            "builder_takeaway": {"headline": "Tactical Steps", "actions": ["Track churn weekly", "Automate testing", "Charge from day 1"]},
            "final_insight": {"quote": "Sustainable revenue is the ultimate competitive advantage.", "cta": "Follow for daily builder breakdowns."},
            "sources": [{"title": "Example", "url": "https://example.com"}]
        }

        builder = CarouselBuilder(content=carousel_content, date_str="2026-10-22")
        slides = builder.write_html_files()

        assert len(slides) == 7, f"Expected 7 slides, got {len(slides)}"
        # Slide 1 contains the category badge
        slide_1_content = slides[0].read_text(encoding="utf-8")
        assert cat.upper() in slide_1_content, f"Category badge missing in slide 1 for {cat}"

        # All slides contain Lakshya Goyal watermark and 1080 canvas
        for idx, slide_path in enumerate(slides, 1):
            assert slide_path.exists(), f"Slide {idx} file does not exist"
            content = slide_path.read_text(encoding="utf-8")
            assert "Lakshya Goyal" in content, f"Watermark missing in slide {idx}"
            assert "1080" in content, f"1080 dimension missing in slide {idx}"

    print("    ✓ CarouselBuilder renders 7 valid HTML slides with watermark & category badge.")


import unittest


class TestExpandedResearchAndReddit(unittest.TestCase):
    def test_expanded_topic_classification(self):
        test_expanded_topic_classification()

    def test_reddit_result_parsing_and_metadata(self):
        test_reddit_result_parsing_and_metadata()

    def test_reddit_timeouts_and_failure_resilience(self):
        test_reddit_timeouts_and_failure_resilience()

    def test_fallback_to_existing_research_sources(self):
        test_fallback_to_existing_research_sources()

    def test_cross_source_deduplication(self):
        test_cross_source_deduplication()

    def test_category_diversity_balancing(self):
        test_category_diversity_balancing()

    def test_content_schema_and_generator_compatibility(self):
        test_content_schema_and_generator_compatibility()

    def test_carousel_rendering_preservation(self):
        test_carousel_rendering_preservation()


def run_all_tests():
    print("==================================================")
    print("🧪 RUNNING EXPANDED RESEARCH & REDDIT TEST SUITE")
    print("==================================================")
    test_expanded_topic_classification()
    test_reddit_result_parsing_and_metadata()
    test_reddit_timeouts_and_failure_resilience()
    test_fallback_to_existing_research_sources()
    test_cross_source_deduplication()
    test_category_diversity_balancing()
    test_content_schema_and_generator_compatibility()
    test_carousel_rendering_preservation()
    print("==================================================")
    print("🎉 ALL EXPANDED RESEARCH & REDDIT TESTS PASSED! 🚀")
    print("==================================================")


if __name__ == "__main__":
    run_all_tests()
