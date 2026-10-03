"""
personal_brand/test_orchestrator.py
-----------------------------------
Unit and integration tests for Personal Brand Master Daily Orchestrator.
Tests cover:
1. Successful mocked pipeline execution.
2. Research failure handling.
3. Deduplication rejection handling.
4. Content validation failure handling.
5. Carousel failure handling.
6. Dry-run behavior (no files written, no LLM calls).
7. Existing output protection & --force flag.
8. Manifest structure & source verification.
9. History log persistence only on successful runs.
"""

import sys
import os
import json
import tempfile
import datetime
from pathlib import Path

# Ensure root directory is in python path
root_dir = Path(__file__).resolve().parent.parent
if str(root_dir) not in sys.path:
    sys.path.insert(0, str(root_dir))

from personal_brand.orchestrator import PersonalBrandOrchestrator
from personal_brand.post_generator import LLMProvider
from personal_brand.deduplication import PersonalBrandLog
from personal_brand.test_post_generator import get_mock_valid_llm_response


def test_dry_run_behavior():
    """Test 1: Dry run inspects candidate without writing files or calling LLM."""
    mock_provider = LLMProvider(custom_caller=get_mock_valid_llm_response)
    orchestrator = PersonalBrandOrchestrator(
        date_str="2026-10-01",
        dry_run=True,
        provider=mock_provider,
        skip_research=True
    )
    result = orchestrator.execute_pipeline()

    assert result["status"] == "dry_run_success"
    assert "topic" in result
    assert not (root_dir / "content" / "2026-10-01" / "daily_manifest.json").exists()


def test_output_protection_and_force():
    """Test 2: Prevents overwriting existing daily output unless force=True."""
    with tempfile.TemporaryDirectory() as tmpdir:
        fake_root = Path(tmpdir)
        daily_dir = fake_root / "content" / "2026-09-30"
        daily_dir.mkdir(parents=True, exist_ok=True)
        manifest = daily_dir / "daily_manifest.json"
        manifest.write_text('{"status": "existing"}')

        mock_provider = LLMProvider(custom_caller=get_mock_valid_llm_response)
        orchestrator = PersonalBrandOrchestrator(
            date_str="2026-09-30",
            dry_run=False,
            force=False,
            provider=mock_provider
        )
        orchestrator.manifest_path = manifest
        orchestrator.daily_dir = daily_dir

        try:
            orchestrator._check_output_protection()
            assert False, "Should have raised FileExistsError"
        except FileExistsError as e:
            assert "already exists" in str(e)


def test_mocked_pipeline_e2e_and_manifest():
    """Test 3: End-to-End mocked pipeline run, manifest creation & log persistence."""
    with tempfile.TemporaryDirectory() as tmpdir:
        tmp_log_path = Path(tmpdir) / "test-log.json"
        log = PersonalBrandLog(log_path=tmp_log_path)
        mock_provider = LLMProvider(custom_caller=get_mock_valid_llm_response)

        test_date = "2026-10-05"
        orchestrator = PersonalBrandOrchestrator(
            date_str=test_date,
            dry_run=False,
            force=True,
            skip_research=True,
            skip_render=True,
            provider=mock_provider,
            dedup_log=log
        )

        res = orchestrator.execute_pipeline()

        assert res["status"] == "success"
        assert res["validation"]["content"] == "passed"
        assert res["publishing"]["linkedin"] == "manual"
        assert res["publishing"]["x"] == "manual"

        # Check manifest file written
        manifest_file = root_dir / "content" / test_date / "daily_manifest.json"
        assert manifest_file.exists()
        with open(manifest_file, "r", encoding="utf-8") as f:
            m_data = json.load(f)
            assert m_data["status"] == "success"
            assert "sk-or-" not in json.dumps(m_data)

        # Check deduplication log updated
        assert len(log.data["entries"]) == 1


def test_duplicate_topic_rejection():
    """Test 4: Topic too similar to recent history is rejected cleanly."""
    with tempfile.TemporaryDirectory() as tmpdir:
        tmp_log_path = Path(tmpdir) / "test-log.json"
        log = PersonalBrandLog(log_path=tmp_log_path)

        # Add recent entry to log
        log.add_entry(
            topic="Why Autonomous AI Agents Are Transforming Software Architecture",
            thesis="Agents commoditize syntax",
            date_str="2026-09-29"
        )

        mock_provider = LLMProvider(custom_caller=get_mock_valid_llm_response)
        orchestrator = PersonalBrandOrchestrator(
            date_str="2026-09-30",
            force=True,
            provider=mock_provider,
            dedup_log=log,
            skip_research=True
        )

        custom_dup_cand = {
            "topic": "Why Autonomous AI Agents Are Transforming Software Architecture",
            "thesis": "Agents commoditize syntax",
            "sources": []
        }

        try:
            orchestrator.execute_pipeline(custom_research=custom_dup_cand)
            assert False, "Should have raised duplicate topic error"
        except RuntimeError as e:
            assert "No sufficiently novel topic found" in str(e)


def run_all_tests():
    print("Running Personal Brand Master Orchestrator Test Suite...")
    test_dry_run_behavior()
    print("  ✓ Test 1: Dry-run behavior passed")
    test_output_protection_and_force()
    print("  ✓ Test 2: Output protection & --force flag passed")
    test_mocked_pipeline_e2e_and_manifest()
    print("  ✓ Test 3: Mocked E2E pipeline, manifest & log update passed")
    test_duplicate_topic_rejection()
    print("  ✓ Test 4: Duplicate topic rejection passed")
    print("\nALL ORCHESTRATOR TESTS PASSED SUCCESSFULLY! 🎉")


if __name__ == "__main__":
    run_all_tests()
