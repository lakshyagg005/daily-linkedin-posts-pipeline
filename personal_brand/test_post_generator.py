"""
personal_brand/test_post_generator.py
-------------------------------------
Test suite for Personal Brand PostGenerator.
Validates provider detection, input validation, quality control (1 LinkedIn post,
3 X posts with distinct angles, 7-slide carousel spec), anti-AI-slop rules,
malformed JSON error handling, and artifact file saving.
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

from personal_brand.post_generator import (
    LLMProvider,
    PostGenerator,
    validate_content_package,
    extract_and_parse_json,
    BANNED_SLOP
)
from personal_brand.deduplication import PersonalBrandLog


def get_mock_valid_llm_response(system_prompt: str, user_prompt: str) -> str:
    """Returns a valid structured JSON response for unit testing without API calls."""
    today_str = datetime.date.today().isoformat()
    package = {
        "date": today_str,
        "topic": "Why Autonomous AI Coding Agents Are Redefining Software Engineering",
        "thesis": "AI coding tools are shifting from line completion to multi-file architecture execution.",
        "category": "AI & Software",
        "linkedin": {
            "caption": "Most software engineering teams are underestimating how fast coding workflows are shifting.\n\n"
                       "Two years ago, AI meant tab-completion for syntax. Today, autonomous agents are executing multi-file refactors and running unit test suites directly from terminal specifications.\n\n"
                       "The implication: syntax memorization is no longer the primary bottleneck for developers. System architecture, specification clarity, and automated verification are now the core skills.\n\n"
                       "If you are building products today, invest in robust test suites first. That is what enables AI agents to work safely.",
            "sources": [{"title": "OpenAI Engineering Report, 2026", "url": "https://openai.com"}]
        },
        "carousel": {
            "date": today_str,
            "topic": "Why Autonomous AI Coding Agents Are Redefining Software Engineering",
            "category": "AI & Software",
            "thesis": "AI coding tools are shifting from line completion to multi-file architecture execution.",
            "hook": {
                "headline": "Most Software Teams Are Misunderstanding AI Coding Agents.",
                "subtitle": "It is no longer about writing syntax faster. It is about multi-file architecture."
            },
            "context": {
                "headline": "The Evolution of Developer Tooling",
                "points": [
                    "2022: Autocomplete suggestions for single lines of code.",
                    "2024: Chat interfaces embedded inside IDE sidebars.",
                    "2026: Autonomous agents executing terminal commands & multi-file refactoring."
                ]
            },
            "misunderstanding": {
                "myth": "AI agents will make junior developers obsolete next month.",
                "reality": "AI agents elevate developers into systems architects, raising the bar for software quality."
            },
            "evidence": {
                "stat": "84%",
                "label": "Engineering Lead Benchmark",
                "explanation": "84% of engineering managers report high-level system design is now more critical than syntax memorization."
            },
            "why_it_matters": {
                "headline": "What This Means for Tech Teams",
                "implications": [
                    {"target": "Developers", "desc": "Focus shifts from typing code to specification, review, and verification."},
                    {"target": "Founders", "desc": "Product velocity increases by 3x, lowering the cost of initial MVP validation."}
                ]
            },
            "builder_takeaway": {
                "headline": "The Builder Playbook",
                "actions": [
                    "Invest heavily in automated unit & integration test coverage.",
                    "Define explicit coding conventions and context files in your repositories.",
                    "Treat AI agents as pair programmers, not autonomous magic."
                ]
            },
            "final_insight": {
                "quote": "The bottleneck is no longer how fast you can write code. It is how clearly you can specify software.",
                "cta": "Follow for practical AI + startup breakdowns."
            },
            "sources": [{"title": "OpenAI Engineering Report, 2026", "url": "https://openai.com"}]
        },
        "x_posts": [
            {
                "angle": "interesting",
                "text": "Syntax memorization is no longer the primary bottleneck in software engineering. AI agents can write boilerplate faster than anyone. The new bottleneck is specification clarity.",
                "sources": []
            },
            {
                "angle": "contrarian",
                "text": "AI coding tools won't eliminate software developers. They will make un-tested code bases completely unmaintainable. Great automated test suites are the real moat.",
                "sources": []
            },
            {
                "angle": "builder",
                "text": "If you build software in 2026: write your test suite before asking AI agents to build features. Verification is how you control non-deterministic code generation.",
                "sources": []
            }
        ]
    }
    return json.dumps(package)


def test_provider_detection():
    """Test 1: Provider configuration detection & custom mock provider."""
    mock_provider = LLMProvider(custom_caller=get_mock_valid_llm_response)
    assert mock_provider.is_configured()
    assert mock_provider.provider_name == "custom_mock"

    res = mock_provider.generate("sys", "user")
    assert "LinkedIn" in res or "topic" in res


def test_validation_logic():
    """Test 2: Validation for 1 LinkedIn caption, 3 X posts with distinct angles, and slop filtering."""
    valid_data = json.loads(get_mock_valid_llm_response("sys", "user"))
    is_valid, errors = validate_content_package(valid_data)
    assert is_valid, f"Validation failed unexpectedly: {errors}"

    # Test invalid X post count
    invalid_x_data = json.loads(get_mock_valid_llm_response("sys", "user"))
    invalid_x_data["x_posts"] = invalid_x_data["x_posts"][:2]
    is_valid_x, err_x = validate_content_package(invalid_x_data)
    assert not is_valid_x
    assert any("must be a list of exactly 3 items" in e for e in err_x)

    # Test duplicate X angles
    dup_angle_data = json.loads(get_mock_valid_llm_response("sys", "user"))
    dup_angle_data["x_posts"][1]["angle"] = "interesting"
    is_valid_angle, err_angle = validate_content_package(dup_angle_data)
    assert not is_valid_angle
    assert any("distinct angles" in e for e in err_angle)

    # Test Anti-AI-Slop detection
    slop_data = json.loads(get_mock_valid_llm_response("sys", "user"))
    slop_data["linkedin"]["caption"] += " This is a revolutionary game changer that unlocks 10x potential."
    is_valid_slop, err_slop = validate_content_package(slop_data)
    assert not is_valid_slop
    assert any("banned AI slop words" in e for e in err_slop)


def test_extract_valid_raw_json():
    """Test 3a: Extract valid raw JSON."""
    raw = '{"date": "2026-10-05", "topic": "Valid Raw JSON"}'
    parsed = extract_and_parse_json(raw)
    assert parsed["date"] == "2026-10-05"
    assert parsed["topic"] == "Valid Raw JSON"


def test_extract_json_inside_fences():
    """Test 3b: Extract JSON inside markdown code fences."""
    raw = '```json\n{"date": "2026-10-05", "topic": "JSON inside fences"}\n```'
    parsed = extract_and_parse_json(raw)
    assert parsed["topic"] == "JSON inside fences"

    raw_no_lang = '```\n{"date": "2026-10-05", "topic": "Fenced without lang tag"}\n```'
    parsed_no_lang = extract_and_parse_json(raw_no_lang)
    assert parsed_no_lang["topic"] == "Fenced without lang tag"


def test_extract_json_surrounding_text():
    """Test 3c: Extract JSON with harmless surrounding text."""
    raw_with_text = 'Here is the JSON package requested:\n```json\n{"date": "2026-10-05", "topic": "Surrounding Text"}\n```\nHope this helps!'
    parsed = extract_and_parse_json(raw_with_text)
    assert parsed["topic"] == "Surrounding Text"

    raw_preamble = 'Sure! Here is your JSON: {"date": "2026-10-05", "topic": "Preamble Only"} Let me know if you need changes.'
    parsed_preamble = extract_and_parse_json(raw_preamble)
    assert parsed_preamble["topic"] == "Preamble Only"


def test_extract_malformed_truncated_json():
    """Test 3d: Reject malformed/truncated JSON."""
    raw_truncated = '{"date": "2026-10-05", "topic": "Truncated'
    try:
        extract_and_parse_json(raw_truncated)
        assert False, "Should have raised ValueError"
    except ValueError as e:
        assert "invalid JSON" in str(e) or "LLM returned invalid JSON" in str(e)


def test_extract_unterminated_string():
    """Test 3e: Unterminated string handling."""
    raw_unterminated = '{"date": "2026-10-05", "caption": "Unterminated string starting here...'
    try:
        extract_and_parse_json(raw_unterminated)
        assert False, "Should have raised ValueError"
    except ValueError as e:
        assert "invalid JSON" in str(e) or "Unterminated" in str(e)


def test_retry_after_json_failure():
    """Test 3f: Retry with concise correction prompt after initial JSON failure."""
    calls = 0
    received_prompts = []

    def flaky_caller(sys_p, usr_p):
        nonlocal calls
        calls += 1
        received_prompts.append(usr_p)
        if calls == 1:
            return "{invalid json unterminated string..."
        return get_mock_valid_llm_response(sys_p, usr_p)

    with tempfile.TemporaryDirectory() as tmpdir:
        tmp_log_path = Path(tmpdir) / "test-flaky-log.json"
        log = PersonalBrandLog(log_path=tmp_log_path)
        flaky_provider = LLMProvider(custom_caller=flaky_caller)
        generator = PostGenerator(provider=flaky_provider, dedup_log=log)

        research_input = {
            "date": "2026-10-05",
            "topic": "Flaky LLM Recovery Test",
            "thesis": "Testing retry after JSON failure.",
            "why_now": "Production robustness test.",
            "potential_angle": "Resilience in LLM pipelines.",
            "category": "AI & Software",
            "sources": [{"title": "Test Source", "url": "https://example.com"}]
        }

        package = generator.generate_content_package(research_input)
        assert package is not None
        assert calls == 2
        assert "PREVIOUS GENERATION ATTEMPT FAILED" in received_prompts[1]
        assert "Please return ONLY a single valid" in received_prompts[1]


def test_final_failure_when_json_remains_unrecoverable():
    """Test 3g: Final failure after maximum retries when JSON remains unrecoverable."""
    calls = 0

    def bad_caller(sys_p, usr_p):
        nonlocal calls
        calls += 1
        return "{permanently broken JSON..."

    bad_provider = LLMProvider(custom_caller=bad_caller)
    generator = PostGenerator(provider=bad_provider)

    try:
        generator.generate_content_package({"topic": "Broken", "thesis": "Broken", "date": "2026-10-05"})
        assert False, "Should have raised ValueError after 3 attempts"
    except ValueError as e:
        assert "failed editorial quality validation after 3 attempts" in str(e)
        assert calls == 3


def test_generator_mocked_end_to_end():
    """Test 4: End-to-end generator execution with mock provider, deduplication, and file saving."""
    with tempfile.TemporaryDirectory() as tmpdir:
        tmp_log_path = Path(tmpdir) / "test-log.json"
        log = PersonalBrandLog(log_path=tmp_log_path)
        mock_provider = LLMProvider(custom_caller=get_mock_valid_llm_response)

        generator = PostGenerator(provider=mock_provider, dedup_log=log)

        research_input = {
            "date": "2026-09-30",
            "topic": "Why Autonomous AI Coding Agents Are Redefining Software Engineering",
            "thesis": "AI coding tools are shifting from line completion to multi-file architecture execution.",
            "why_now": "New AI agent benchmarks released.",
            "potential_angle": "System architecture over syntax typing.",
            "category": "AI & Software",
            "sources": [{"title": "OpenAI Report", "url": "https://openai.com", "source_type": "official_company"}]
        }

        package = generator.generate_content_package(research_input)
        assert package["date"] == "2026-09-30"

        # Verify artifacts written
        saved_files = generator.save_content_artifacts(package)
        for name, p in saved_files.items():
            assert Path(p).exists()
            assert Path(p).stat().st_size > 50

        # Check deduplication logged
        assert len(log.data["entries"]) == 1
        assert log.data["entries"][0]["topic"] == research_input["topic"]


def test_real_llm_provider_report():
    """Test 5: Check real provider credentials state."""
    real_provider = LLMProvider()
    if not real_provider.is_configured():
        print("\n  [INFO] Real LLM generation was not executed because no provider credentials are configured.")
    else:
        print(f"\n  [INFO] Real LLM provider detected: '{real_provider.provider_name}'")


def run_all_tests():
    print("Running Personal Brand PostGenerator Unit & Integration Test Suite...")
    test_provider_detection()
    print("  ✓ Test 1: Provider detection & mock provider passed")
    test_validation_logic()
    print("  ✓ Test 2: Validation rules (1 LinkedIn, 3 X posts, slop check) passed")
    test_extract_valid_raw_json()
    print("  ✓ Test 3a: Extract valid raw JSON passed")
    test_extract_json_inside_fences()
    print("  ✓ Test 3b: Extract JSON inside code fences passed")
    test_extract_json_surrounding_text()
    print("  ✓ Test 3c: Extract JSON with surrounding text passed")
    test_extract_malformed_truncated_json()
    print("  ✓ Test 3d: Malformed/truncated JSON rejection passed")
    test_extract_unterminated_string()
    print("  ✓ Test 3e: Unterminated string error handling passed")
    test_retry_after_json_failure()
    print("  ✓ Test 3f: Retry with correction prompt after JSON failure passed")
    test_final_failure_when_json_remains_unrecoverable()
    print("  ✓ Test 3g: Final failure after 3 failed JSON attempts passed")
    test_generator_mocked_end_to_end()
    print("  ✓ Test 4: Generator mock E2E, deduplication & file saving passed")
    test_real_llm_provider_report()
    print("  ✓ Test 5: Real provider credentials state checked")
    print("\nALL POST GENERATOR TESTS PASSED SUCCESSFULLY! 🎉")


if __name__ == "__main__":
    run_all_tests()
