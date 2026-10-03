"""
personal_brand/test_phase1.py
-----------------------------
Self-test suite verifying deduplication, log persistence, similarity scoring,
and research data schema for Phase 1.
"""

import sys
import json
import tempfile
from pathlib import Path
import datetime

# Ensure workspace root is in path
root_dir = Path(__file__).resolve().parent.parent
if str(root_dir) not in sys.path:
    sys.path.insert(0, str(root_dir))

from personal_brand.deduplication import PersonalBrandLog, normalize_text, jaccard_similarity
from personal_brand.research import (
    generate_research_candidates,
    save_research_artifacts,
    classify_source_type,
    create_research_candidate
)


def test_missing_log_and_creation():
    """Test 1: Safely handles missing log and initializes valid JSON."""
    with tempfile.TemporaryDirectory() as tmpdir:
        tmp_log_path = Path(tmpdir) / "test-log.json"

        # Verify file does not exist yet
        assert not tmp_log_path.exists()

        log = PersonalBrandLog(log_path=tmp_log_path)

        # File should now exist with default empty schema
        assert tmp_log_path.exists()
        assert log.data == {"version": 1, "entries": []}

        # Verify disk contents are valid JSON
        with open(tmp_log_path, "r", encoding="utf-8") as f:
            data = json.load(f)
            assert data["version"] == 1
            assert data["entries"] == []


def test_add_entry_and_load():
    """Test 2: Adding entries, saving, reloading, and date filtering."""
    with tempfile.TemporaryDirectory() as tmpdir:
        tmp_log_path = Path(tmpdir) / "test-log.json"
        log = PersonalBrandLog(log_path=tmp_log_path)

        today_str = datetime.date.today().isoformat()
        old_date_str = (datetime.date.today() - datetime.timedelta(days=45)).isoformat()

        # Add recent entry
        log.add_entry(
            topic="Why AI wrappers fail",
            angle="Moat analysis",
            thesis="Distribution beats simple wrappers",
            linkedin_hook="Most AI startups aren't AI companies.",
            x_themes=["wrappers", "moats"],
            sources=[{"title": "TechCrunch", "url": "https://techcrunch.com", "source_type": "high_quality_journalism"}],
            date_str=today_str
        )

        # Add old entry (45 days ago)
        log.add_entry(
            topic="Building micro-saas in 2024",
            angle="Solo founder strategy",
            thesis="Small focused tools succeed",
            linkedin_hook="How to build micro-saas",
            x_themes=["saas"],
            date_str=old_date_str
        )

        # Reload from disk
        reloaded_log = PersonalBrandLog(log_path=tmp_log_path)
        assert len(reloaded_log.data["entries"]) == 2

        # Test 30-day filtering
        recent_entries = reloaded_log.get_recent_entries(days=30)
        assert len(recent_entries) == 1
        assert recent_entries[0]["topic"] == "Why AI wrappers fail"


def test_duplicate_detection():
    """Test 3: Duplicate topic and hook similarity detection."""
    with tempfile.TemporaryDirectory() as tmpdir:
        tmp_log_path = Path(tmpdir) / "test-log.json"
        log = PersonalBrandLog(log_path=tmp_log_path)

        log.add_entry(
            topic="Why AI wrapper startups are losing defensibility",
            angle="Moats",
            thesis="Wrappers lose to foundational platforms",
            linkedin_hook="Most AI startups aren't really AI companies.",
            x_themes=["ai", "startups"]
        )

        # Test similar topic
        is_dup, match, score = log.is_topic_similar("Why AI wrapper startups lose defensibility")
        assert is_dup is True
        assert match["topic"] == "Why AI wrapper startups are losing defensibility"

        # Test distinct topic
        is_dup_distinct, _, _ = log.is_topic_similar("Quantum computing breakthroughs in cryptography")
        assert is_dup_distinct is False

        # Test similar hook
        is_hook_dup, match_h, _ = log.is_hook_similar("Most AI startups aren't real AI companies")
        assert is_hook_dup is True

        # Test distinct hook
        is_hook_distinct, _, _ = log.is_hook_similar("Here is how we redesigned our database schema")
        assert is_hook_distinct is False


def test_research_candidate_schema_and_saving():
    """Test 4: Research candidate schema creation and saving artifacts."""
    with tempfile.TemporaryDirectory() as tmpdir:
        candidate = create_research_candidate(
            topic="Autonomous AI Coding Agents",
            why_now="New benchmark results released",
            potential_angle="How developer workflows change in 2026",
            thesis="AI agents handle multi-file refactoring autonomously",
            category="Software",
            sources=[
                {"title": "OpenAI Blog", "url": "https://openai.com/index/agents", "source_type": "official_company"},
                {"title": "Reddit discussion", "url": "https://reddit.com/r/artificial/123", "source_type": "community_signal"}
            ]
        )

        assert candidate["category"] == "Software"
        assert candidate["sources"][0]["source_type"] == "official_company"
        assert candidate["sources"][1]["source_type"] == "community_signal"

        # Verify source classification helper
        assert classify_source_type("https://reddit.com/r/startups") == "community_signal"
        assert classify_source_type("https://openai.com/blog/test") == "official_company"
        assert classify_source_type("https://arxiv.org/abs/2401.1234") == "research_paper"

        # Save test artifact into temporary directory structure
        art_path = save_research_artifacts([candidate], date_str="2026-09-30")
        assert art_path.exists()
        with open(art_path, "r", encoding="utf-8") as f:
            data = json.load(f)
            assert data["count"] == 1
            assert data["candidates"][0]["topic"] == "Autonomous AI Coding Agents"


def run_all_tests():
    print("Running Personal Brand Phase 1 Self-Test Suite...")
    test_missing_log_and_creation()
    print("  ✓ Test 1: Missing log & initialization passed")
    test_add_entry_and_load()
    print("  ✓ Test 2: Add entry, save, reload & 30-day filtering passed")
    test_duplicate_detection()
    print("  ✓ Test 3: Duplicate topic & hook detection passed")
    test_research_candidate_schema_and_saving()
    print("  ✓ Test 4: Research candidate schema & artifact saving passed")
    print("\nALL PHASE 1 SELF-TESTS PASSED SUCCESSFULLY! 🎉")


if __name__ == "__main__":
    run_all_tests()
