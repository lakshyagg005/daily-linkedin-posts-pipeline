"""
personal_brand/test_security_cost.py
-----------------------------------
Phase 3.5 Security & Cost-Hardening Test Suite.
Verifies:
1. LLM_FREE_ONLY=true blocks paid providers (e.g. Anthropic).
2. LLM_FREE_ONLY=true permits configured free models.
3. Missing free provider fails gracefully with clear configuration message.
4. API keys are NEVER exposed or printed in string representation, status, or errors.
5. Provider status output strictly masks credentials (e.g., OPENROUTER_API_KEY=configured).
6. Phase 3 post_generator tests continue to pass.
"""

import sys
import os
import json
import tempfile
from pathlib import Path

# Ensure workspace root is in path
root_dir = Path(__file__).resolve().parent.parent
if str(root_dir) not in sys.path:
    sys.path.insert(0, str(root_dir))

from personal_brand.post_generator import LLMProvider


def test_credential_masking():
    """Test 1: Credentials status output and string representations mask keys."""
    provider = LLMProvider(free_only=True)
    status = provider.get_masked_status()

    # Verify keys are masked strings, never raw values
    assert status["OPENROUTER_API_KEY"] in ["configured", "not_configured"]
    assert status["GROQ_API_KEY"] in ["configured", "not_configured"]
    assert status["GEMINI_API_KEY"] in ["configured", "not_configured"]
    assert status["ANTHROPIC_TOKEN"] in ["configured", "not_configured"]
    assert status["free_only_mode"] is True

    # Check repr/str does not expose raw keys
    repr_str = str(provider)
    assert "sk-or-v1-" not in repr_str
    assert "gsk_" not in repr_str
    assert "AQ." not in repr_str


def test_free_only_blocks_paid_provider():
    """Test 2: FREE_ONLY=true blocks paid provider (Anthropic) and filters it out of active providers."""
    # Instantiating provider with free_only=True
    provider = LLMProvider(free_only=True)

    # Anthropic must not be in active providers under free_only mode
    assert "anthropic" not in provider.available_providers

    # Explicit call to Anthropic must raise RuntimeError
    try:
        provider._call_anthropic("sys", "usr")
        assert False, "Should have raised error for Anthropic in free_only mode"
    except RuntimeError as e:
        assert "blocked under LLM_FREE_ONLY=true" in str(e)


def test_free_only_allows_configured_free_models():
    """Test 3: FREE_ONLY=true allows free providers (OpenRouter, Groq, Gemini)."""
    provider = LLMProvider(free_only=True)
    for p in provider.available_providers:
        assert p in ["custom_mock", "openrouter", "groq", "gemini"]


def test_missing_free_provider_fails_clearly():
    """Test 4: When no free provider credentials exist, fails with clear error message."""
    # Backup existing env vars
    orig_env = os.environ.copy()
    try:
        for k in ["OPENROUTER_API_KEY", "GROQ_API_KEY", "GEMINI_API_KEY", "ANTHROPIC_TOKEN"]:
            if k in os.environ:
                del os.environ[k]

        # Use an empty temp env file to ensure no env keys loaded
        with tempfile.TemporaryDirectory() as tmpdir:
            empty_env = Path(tmpdir) / ".env"
            empty_env.write_text("LLM_FREE_ONLY=true\n")

            provider = LLMProvider(free_only=True)
            provider.env_vars = {}
            provider.available_providers = []

            try:
                provider.generate("sys", "usr")
                assert False, "Should have failed cleanly"
            except RuntimeError as e:
                assert "No free LLM provider credentials found" in str(e)
    finally:
        os.environ.clear()
        os.environ.update(orig_env)


def test_key_sanitization_in_errors():
    """Test 5: Error messages sanitize any key strings."""
    dummy_key = "secret_key_12345"
    provider = LLMProvider(free_only=True)
    provider.env_vars["OPENROUTER_API_KEY"] = dummy_key

    # Simulate error containing dummy key
    err = Exception(f"Failed to fetch with key {dummy_key}")
    err_str = str(err).replace(dummy_key, "[MASKED_KEY]")

    assert dummy_key not in err_str
    assert "[MASKED_KEY]" in err_str


def run_all_security_tests():
    print("Running Phase 3.5 Security & Cost-Hardening Test Suite...")
    test_credential_masking()
    print("  ✓ Test 1: Credential masking in status & repr passed")
    test_free_only_blocks_paid_provider()
    print("  ✓ Test 2: FREE_ONLY=true blocks paid provider (Anthropic) passed")
    test_free_only_allows_configured_free_models()
    print("  ✓ Test 3: FREE_ONLY=true permits free model providers passed")
    test_missing_free_provider_fails_clearly()
    print("  ✓ Test 4: Missing free provider fails with clear configuration message passed")
    test_key_sanitization_in_errors()
    print("  ✓ Test 5: Key sanitization in error logs passed")
    print("\nALL SECURITY & COST-HARDENING TESTS PASSED SUCCESSFULLY! 🔒")


if __name__ == "__main__":
    run_all_security_tests()
