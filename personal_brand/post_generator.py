"""
personal_brand/post_generator.py
--------------------------------
Personal Brand Content Generator for Lakshya.
Generates:
1. One high-quality LinkedIn post
2. One 7-slide carousel content spec (consumed by carousel_builder.py)
3. Three distinct X posts (interesting, contrarian, builder takeaway)

Reuses OpenRouter/Gemini API callers if credentials exist, supports mock provider
for testing, enforces anti-AI-slop rules, source integrity, and deduplication logging.
"""

from pathlib import Path
import json
import os
import re
import urllib
import urllib.request
import urllib.error
import ssl
import datetime
import socket
import time
from typing import Dict, Any, List, Optional, Tuple, Callable

from .deduplication import PersonalBrandLog
from .research import load_env_file

SSL_CTX = ssl.create_default_context()
SSL_CTX.check_hostname = False
SSL_CTX.verify_mode = ssl.CERT_NONE

# Banned Anti-AI-Slop Words & Phrases
BANNED_SLOP = [
    "game changer", "game-changer", "revolutionary", "unlock", "leverage",
    "leverages", "10x", "future of work", "delve", "tapestry", "disruptive",
    "paradigm shift", "supercharge", "excited to share", "thought leader",
    "groundbreaking", "unprecedented", "synergy", "unleash", "transformative",
    "world-class", "journey", "ecosystem"
]


FREE_MODELS: Dict[str, List[str]] = {
    "openrouter": [
        "openrouter/free",
        "google/gemma-4-31b-it:free",
        "google/gemma-4-26b-a4b-it:free",
        "liquid/lfm-2.5-2.6b:free",
        "nvidia/nemotron-3.5-lightning:free",
    ],
    "groq": ["llama-3.3-70b-versatile", "llama3-8b-8192", "llama-3.1-8b-instant"],
    "gemini": ["gemini-2.5-flash", "gemini-3.5-flash", "gemini-2.0-flash", "gemini-1.5-flash"],
    "anthropic": []  # Anthropic is paid-only, blocked in free_only mode
}


def fetch_openrouter_free_models(timeout: float = 5.0) -> List[str]:
    """Dynamically fetches active 0-cost ($0 input, $0 output) free models from OpenRouter API catalog."""
    url = "https://openrouter.ai/api/v1/models"
    req = urllib.request.Request(url, headers={"User-Agent": "PersonalBrandPipeline/1.0"})
    try:
        with urllib.request.urlopen(req, context=SSL_CTX, timeout=timeout) as res:
            data = json.loads(res.read().decode("utf-8"))
            models = data.get("data", [])
            free_ids = []
            for m in models:
                mid = m.get("id", "")
                pricing = m.get("pricing", {})
                prompt_cost = float(pricing.get("prompt", 0))
                completion_cost = float(pricing.get("completion", 0))
                if prompt_cost == 0 and completion_cost == 0:
                    if mid not in free_ids:
                        free_ids.append(mid)
            return free_ids
    except Exception:
        return []


def extract_and_parse_json(raw_response: str) -> Dict[str, Any]:
    """
    Robustly extracts and parses JSON from an LLM response string.
    Handles:
    - Markdown code fences (```json ... ``` or ``` ... ```)
    - Surrounding text before/after JSON
    - Unescaped newlines/control characters in strings (via strict=False)
    - Trailing commas
    - Invalid escape sequences
    Raises ValueError if JSON is unrecoverable or malformed.
    """
    if not raw_response or not raw_response.strip():
        raise ValueError("LLM returned an empty response.")

    text = raw_response.strip()
    candidates = []

    # 1. Extract content inside markdown code fences ```json ... ``` or ``` ... ```
    fence_matches = re.findall(r"```(?:json)?\s*([\s\S]*?)\s*```", text, re.IGNORECASE)
    for fm in fence_matches:
        if fm.strip():
            candidates.append(fm.strip())

    # 2. Extract substring between first '{' and last '}'
    first_brace = text.find("{")
    last_brace = text.rfind("}")
    if first_brace != -1 and last_brace != -1 and last_brace > first_brace:
        extracted = text[first_brace:last_brace + 1].strip()
        if extracted not in candidates:
            candidates.append(extracted)

    # 3. Fallback: raw trimmed text
    if text not in candidates:
        candidates.append(text)

    last_error = None
    for cand in candidates:
        # Attempt A: Standard JSON parse
        try:
            return json.loads(cand)
        except Exception as e:
            last_error = e

        # Attempt B: Non-strict JSON parse (allows unescaped control chars / literal newlines in strings)
        try:
            return json.loads(cand, strict=False)
        except Exception as e:
            last_error = e

        # Attempt C: Remove trailing commas before } or ] and fix invalid backslashes, then non-strict parse
        cleaned = re.sub(r',\s*([\}\]])', r'\1', cand)
        cleaned = re.sub(r'\\(?!["\\/bfnrt]|u[0-9a-fA-F]{4})', r'\\\\', cleaned)
        try:
            return json.loads(cleaned, strict=False)
        except Exception as e:
            last_error = e

    raise ValueError(f"LLM returned invalid JSON: {last_error}")


class LLMProvider:
    """
    Abstraction for LLM API calls with security credential masking,
    cost safety checks (FREE_ONLY mode), dynamic free model resolution,
    exponential backoff for transient errors, and circuit-breaker provider fallback.
    """

    def __init__(
        self,
        custom_caller: Optional[Callable[[str, str], str]] = None,
        free_only: Optional[bool] = None
    ):
        self.custom_caller = custom_caller
        self.env_vars = load_env_file()
        self.last_used_provider: Optional[str] = None
        self.disabled_providers: Dict[str, str] = {}
        self.disabled_models: set = set()
        self.provider_statuses: Dict[str, str] = {}
        self.disable_backoff_sleep: bool = False

        # Determine free_only setting (default True if unset)
        if free_only is not None:
            self.free_only = free_only
        else:
            raw_fo = os.environ.get("LLM_FREE_ONLY") or os.environ.get("FREE_ONLY") or self.env_vars.get("LLM_FREE_ONLY", "true")
            self.free_only = str(raw_fo).lower() in ("true", "1", "yes", "y")

        self.available_providers = self._detect_providers()
        self.provider_name = self.available_providers[0] if self.available_providers else "none"

    def mark_provider_disabled(self, provider: str, reason: str) -> None:
        """Marks a provider as disabled/unavailable for the remainder of the current run."""
        self.disabled_providers[provider] = reason
        self.provider_statuses[provider] = reason

    def _get_key(self, key_name: str) -> Optional[str]:
        return os.environ.get(key_name) or self.env_vars.get(key_name)

    def _detect_providers(self) -> List[str]:
        if self.custom_caller is not None:
            return ["custom_mock"]
        
        # OpenRouter is PRIMARY free provider
        providers = []
        if self._get_key("OPENROUTER_API_KEY"):
            providers.append("openrouter")
        if self._get_key("GROQ_API_KEY"):
            providers.append("groq")
        if self._get_key("GEMINI_API_KEY"):
            providers.append("gemini")
        if self._get_key("ANTHROPIC_TOKEN"):
            if not self.free_only:
                providers.append("anthropic")

        return providers

    def is_configured(self) -> bool:
        return len(self.available_providers) > 0

    def get_masked_status(self) -> Dict[str, Any]:
        """Returns provider configuration status with all credentials strictly masked."""
        statuses = {}
        for p in ["openrouter", "groq", "gemini", "anthropic"]:
            key_name = {
                "openrouter": "OPENROUTER_API_KEY",
                "groq": "GROQ_API_KEY",
                "gemini": "GEMINI_API_KEY",
                "anthropic": "ANTHROPIC_TOKEN"
            }[p]
            has_key = bool(self._get_key(key_name))
            if p in self.disabled_providers:
                statuses[p] = self.disabled_providers[p]
            elif has_key and p in self.available_providers:
                statuses[p] = self.provider_statuses.get(p, "AVAILABLE")
            else:
                statuses[p] = "NOT_CONFIGURED"

        return {
            "OPENROUTER_API_KEY": "configured" if bool(self._get_key("OPENROUTER_API_KEY")) else "not_configured",
            "GROQ_API_KEY": "configured" if bool(self._get_key("GROQ_API_KEY")) else "not_configured",
            "GEMINI_API_KEY": "configured" if bool(self._get_key("GEMINI_API_KEY")) else "not_configured",
            "ANTHROPIC_TOKEN": "configured" if bool(self._get_key("ANTHROPIC_TOKEN")) else "not_configured",
            "free_only_mode": self.free_only,
            "active_providers": [p for p in self.available_providers if p not in self.disabled_providers],
            "provider_statuses": statuses
        }

    def get_provider_status_report(self) -> str:
        """Generates a human-readable provider status report with masked credentials."""
        lines = ["Provider Status:"]
        status_map = self.get_masked_status()["provider_statuses"]
        for p in ["openrouter", "groq", "gemini", "anthropic"]:
            if p == "anthropic" and self.free_only:
                continue
            lines.append(f"- {p}: {status_map.get(p, 'NOT_CONFIGURED')}")
        return "\n".join(lines)

    def __repr__(self) -> str:
        active = [p for p in self.available_providers if p not in self.disabled_providers]
        return f"LLMProvider(free_only={self.free_only}, active_providers={active}, disabled={self.disabled_providers})"

    def __str__(self) -> str:
        return self.__repr__()

    def _sanitize_error(self, err: Any) -> str:
        err_str = str(err)
        for k in ["OPENROUTER_API_KEY", "GROQ_API_KEY", "GEMINI_API_KEY", "ANTHROPIC_TOKEN"]:
            val = self._get_key(k)
            if val and len(val) > 4:
                err_str = err_str.replace(val, "[MASKED_KEY]")
        return err_str

    def _call_with_retry(
        self,
        func: Callable[[], str],
        max_retries: int = 2,
        backoff_delays: Optional[List[float]] = None
    ) -> str:
        if backoff_delays is None:
            if getattr(self, "disable_backoff_sleep", False) or os.environ.get("TEST_MODE") == "1":
                backoff_delays = [0.0, 0.0, 0.0]
            else:
                backoff_delays = [2.0, 5.0, 10.0]

        attempt = 0
        while True:
            try:
                return func()
            except urllib.error.HTTPError as e:
                # Deterministic errors (401, 403, 404, 400) should NOT be retried
                if e.code in (401, 403, 404, 400):
                    raise e
                # Transient errors: 429, 5xx
                if attempt < max_retries and (e.code == 429 or e.code >= 500):
                    delay = backoff_delays[min(attempt, len(backoff_delays) - 1)]
                    print(f"[WARN] Transient HTTP {e.code} error. Retrying in {delay}s (Attempt {attempt+1}/{max_retries})...")
                    if delay > 0:
                        time.sleep(delay)
                    attempt += 1
                    continue
                raise e
            except (urllib.error.URLError, TimeoutError, socket.timeout) as e:
                if attempt < max_retries:
                    delay = backoff_delays[min(attempt, len(backoff_delays) - 1)]
                    print(f"[WARN] Transient network/timeout error ({e}). Retrying in {delay}s (Attempt {attempt+1}/{max_retries})...")
                    if delay > 0:
                        time.sleep(delay)
                    attempt += 1
                    continue
                raise e

    def generate(
        self,
        system_prompt: str,
        user_prompt: str,
        exclude_providers: Optional[List[str]] = None
    ) -> str:
        if self.custom_caller:
            self.last_used_provider = "custom_mock"
            return self.custom_caller(system_prompt, user_prompt)

        if not self.is_configured():
            if self.free_only:
                raise RuntimeError(
                    "No free LLM provider credentials found or allowed under LLM_FREE_ONLY=true. "
                    "Please configure OPENROUTER_API_KEY, GROQ_API_KEY, or GEMINI_API_KEY."
                )
            else:
                raise RuntimeError(
                    "No valid LLM provider credentials found. "
                    "Please configure OPENROUTER_API_KEY, GROQ_API_KEY, GEMINI_API_KEY, or ANTHROPIC_TOKEN."
                )

        exclude_set = set(exclude_providers or [])
        candidate_providers = [
            p for p in self.available_providers
            if p not in self.disabled_providers and p not in exclude_set
        ]

        if not candidate_providers:
            report = self.get_provider_status_report()
            print(f"\n{report}")
            raise RuntimeError(f"No available active LLM providers remaining.\n{report}")

        errors = []
        for provider in candidate_providers:
            try:
                if provider == "openrouter":
                    res = self._call_openrouter(system_prompt, user_prompt)
                elif provider == "groq":
                    res = self._call_groq(system_prompt, user_prompt)
                elif provider == "gemini":
                    res = self._call_gemini(system_prompt, user_prompt)
                elif provider == "anthropic":
                    res = self._call_anthropic(system_prompt, user_prompt)
                else:
                    continue
                self.last_used_provider = provider
                self.provider_statuses[provider] = "AVAILABLE"
                return res
            except Exception as e:
                err_str = self._sanitize_error(e)
                err_msg = f"Provider '{provider}' call failed: {err_str}"
                print(f"[WARN] {err_msg}. Falling back to next available provider...")
                errors.append(err_msg)

        report = self.get_provider_status_report()
        print(f"\n{report}")
        raise RuntimeError(f"All configured LLM providers failed:\n" + "\n".join(errors) + f"\n\n{report}")

    def _call_openrouter(self, system_prompt: str, user_prompt: str) -> str:
        if "openrouter" in self.disabled_providers:
            raise RuntimeError(f"OpenRouter is disabled: {self.disabled_providers['openrouter']}")

        api_key = self._get_key("OPENROUTER_API_KEY")
        if not api_key:
            self.mark_provider_disabled("openrouter", "UNAVAILABLE (Missing API Key)")
            raise RuntimeError("OPENROUTER_API_KEY not configured.")

        url = "https://openrouter.ai/api/v1/chat/completions"
        headers = {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json"
        }

        # Candidate free models resolution
        dynamic_free_list = fetch_openrouter_free_models()
        dynamic_free_set = set(dynamic_free_list)

        candidate_models = ["openrouter/free"]
        for dm in dynamic_free_list:
            if dm not in candidate_models:
                candidate_models.append(dm)

        for sm in FREE_MODELS["openrouter"]:
            if sm not in candidate_models:
                candidate_models.append(sm)

        candidate_models = [m for m in candidate_models if m not in self.disabled_models]
        last_err = None

        for m in candidate_models:
            # Under free_only mode, only allow openrouter/free, models ending with :free, or verified dynamic $0 cost models
            if self.free_only and m not in dynamic_free_set and not m.endswith(":free") and m != "openrouter/free":
                continue

            for use_json_format in [True, False]:
                payload = {
                    "model": m,
                    "messages": [
                        {"role": "system", "content": system_prompt},
                        {"role": "user", "content": user_prompt}
                    ],
                    "max_tokens": 4000
                }
                if use_json_format:
                    payload["response_format"] = {"type": "json_object"}

                def _do_request():
                    req = urllib.request.Request(url, data=json.dumps(payload).encode("utf-8"), headers=headers, method="POST")
                    with urllib.request.urlopen(req, context=SSL_CTX, timeout=45) as res:
                        resp = json.loads(res.read().decode("utf-8"))
                        if resp and "choices" in resp and len(resp["choices"]) > 0:
                            msg = resp["choices"][0].get("message", {})
                            content = msg.get("content") or msg.get("reasoning")
                            if content and isinstance(content, str) and content.strip():
                                return content.strip()
                        raise RuntimeError(f"Empty response from OpenRouter model {m}")

                try:
                    res_content = self._call_with_retry(_do_request)
                    if res_content:
                        return res_content
                except urllib.error.HTTPError as http_err:
                    last_err = http_err
                    if http_err.code in (401, 403):
                        self.mark_provider_disabled("openrouter", f"UNAVAILABLE (HTTP {http_err.code})")
                        raise RuntimeError(f"OpenRouter authentication failed: HTTP {http_err.code}")
                    elif http_err.code == 404:
                        self.disabled_models.add(m)
                        break  # Move to next model
                    elif http_err.code == 400 and use_json_format:
                        continue  # Try without json_object response_format
                    else:
                        break
                except Exception as e:
                    last_err = e
                    continue

        if "openrouter" not in self.disabled_providers:
            self.mark_provider_disabled("openrouter", f"UNAVAILABLE (All free models failed: {self._sanitize_error(last_err)})")
        raise RuntimeError(f"OpenRouter models failed. Last error: {self._sanitize_error(last_err)}")

    def _call_groq(self, system_prompt: str, user_prompt: str) -> str:
        if "groq" in self.disabled_providers:
            raise RuntimeError(f"Groq is disabled: {self.disabled_providers['groq']}")

        api_key = self._get_key("GROQ_API_KEY")
        if not api_key:
            self.mark_provider_disabled("groq", "UNAVAILABLE (Missing API Key)")
            raise RuntimeError("GROQ_API_KEY not configured.")

        url = "https://api.groq.com/openai/v1/chat/completions"
        headers = {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json"
        }
        models = [m for m in FREE_MODELS["groq"] if m not in self.disabled_models]
        last_err = None

        for m in models:
            payload = {
                "model": m,
                "messages": [
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt}
                ],
                "max_tokens": 4000,
                "response_format": {"type": "json_object"}
            }

            def _do_request():
                req = urllib.request.Request(url, data=json.dumps(payload).encode("utf-8"), headers=headers, method="POST")
                with urllib.request.urlopen(req, context=SSL_CTX, timeout=45) as res:
                    resp = json.loads(res.read().decode("utf-8"))
                    if resp and "choices" in resp and len(resp["choices"]) > 0:
                        return resp["choices"][0]["message"]["content"]
                    raise RuntimeError(f"Empty response from Groq model {m}")

            try:
                res_content = self._call_with_retry(_do_request)
                if res_content:
                    return res_content
            except urllib.error.HTTPError as http_err:
                last_err = http_err
                if http_err.code in (401, 403):
                    self.mark_provider_disabled("groq", f"UNAVAILABLE (HTTP {http_err.code})")
                    raise RuntimeError(f"Groq API returned HTTP {http_err.code}")
                elif http_err.code == 404:
                    self.disabled_models.add(m)
                    continue
            except Exception as e:
                last_err = e
                continue

        if "groq" not in self.disabled_providers:
            self.mark_provider_disabled("groq", f"UNAVAILABLE (All models failed: {self._sanitize_error(last_err)})")
        raise RuntimeError(f"Groq models failed. Last error: {self._sanitize_error(last_err)}")

    def _call_gemini(self, system_prompt: str, user_prompt: str) -> str:
        if "gemini" in self.disabled_providers:
            raise RuntimeError(f"Gemini is disabled: {self.disabled_providers['gemini']}")

        api_key = self._get_key("GEMINI_API_KEY")
        if not api_key:
            self.mark_provider_disabled("gemini", "UNAVAILABLE (Missing API Key)")
            raise RuntimeError("GEMINI_API_KEY not configured.")

        models = [m for m in FREE_MODELS["gemini"] if m not in self.disabled_models]
        last_err = None

        for m in models:
            url = f"https://generativelanguage.googleapis.com/v1beta/models/{m}:generateContent?key={api_key}"
            headers = {"Content-Type": "application/json"}
            payload = {
                "contents": [{
                    "parts": [{"text": f"{system_prompt}\n\nUSER REQUEST:\n{user_prompt}"}]
                }],
                "generationConfig": {"response_mime_type": "application/json"}
            }

            def _do_request():
                req = urllib.request.Request(url, data=json.dumps(payload).encode("utf-8"), headers=headers, method="POST")
                with urllib.request.urlopen(req, context=SSL_CTX, timeout=45) as res:
                    resp = json.loads(res.read().decode("utf-8"))
                    if resp and "candidates" in resp and len(resp["candidates"]) > 0:
                        return resp["candidates"][0]["content"]["parts"][0]["text"]
                    raise RuntimeError(f"Empty response from Gemini model {m}")

            try:
                res_content = self._call_with_retry(_do_request)
                if res_content:
                    return res_content
            except urllib.error.HTTPError as http_err:
                last_err = http_err
                if http_err.code in (401, 403):
                    self.mark_provider_disabled("gemini", f"UNAVAILABLE (HTTP {http_err.code})")
                    raise RuntimeError(f"Gemini API returned HTTP {http_err.code}")
                elif http_err.code == 404:
                    self.disabled_models.add(m)
                    continue
            except Exception as e:
                last_err = e
                continue

        if "gemini" not in self.disabled_providers:
            self.mark_provider_disabled("gemini", "UNAVAILABLE (HTTP 404 / All models failed)")
        raise RuntimeError(f"Gemini models failed. Last error: {self._sanitize_error(last_err)}")

    def _call_anthropic(self, system_prompt: str, user_prompt: str) -> str:
        if self.free_only:
            raise RuntimeError("Anthropic provider is a paid-only service and is blocked under LLM_FREE_ONLY=true.")

        token = self._get_key("ANTHROPIC_TOKEN")
        url = "https://api.anthropic.com/v1/messages"
        headers = {
            "x-api-key": token,
            "anthropic-version": "2023-06-01",
            "Content-Type": "application/json"
        }
        payload = {
            "model": "claude-3-5-sonnet-20241022",
            "system": system_prompt,
            "messages": [{"role": "user", "content": user_prompt}],
            "max_tokens": 4000
        }
        req = urllib.request.Request(url, data=json.dumps(payload).encode("utf-8"), headers=headers, method="POST")
        with urllib.request.urlopen(req, context=SSL_CTX, timeout=45) as res:
            resp = json.loads(res.read().decode("utf-8"))
            return resp["content"][0]["text"]


def validate_content_package(data: Dict[str, Any]) -> Tuple[bool, List[str]]:
    """Quality control validation for generated content package."""
    errors = []

    # Check top level
    for k in ["date", "topic", "thesis", "linkedin", "carousel", "x_posts"]:
        if k not in data or not data[k]:
            errors.append(f"Missing top-level key: {k}")

    if errors:
        return False, errors

    # Check LinkedIn post
    linkedin = data.get("linkedin", {})
    caption = linkedin.get("caption", "")
    if not caption or len(caption) < 100:
        errors.append("LinkedIn caption is missing or too short (<100 chars).")

    # Check Carousel Spec (Must match carousel_builder.py requirements)
    carousel = data.get("carousel", {})
    req_c_keys = ["hook", "context", "misunderstanding", "evidence", "why_it_matters", "builder_takeaway", "final_insight"]
    for ck in req_c_keys:
        if ck not in carousel or not carousel[ck]:
            errors.append(f"Carousel missing required field: {ck}")

    # Check X Posts (Exactly 3 posts with distinct angles)
    x_posts = data.get("x_posts", [])
    if not isinstance(x_posts, list) or len(x_posts) != 3:
        errors.append(f"x_posts must be a list of exactly 3 items, got {len(x_posts) if isinstance(x_posts, list) else 0}.")
    else:
        angles = [p.get("angle", "").lower() for p in x_posts if isinstance(p, dict)]
        if len(set(angles)) < 3:
            errors.append(f"X posts must have 3 distinct angles, got: {angles}")
        for idx, xp in enumerate(x_posts):
            text = xp.get("text", "") if isinstance(xp, dict) else ""
            if not text or len(text) > 300:
                errors.append(f"X post #{idx+1} text missing or exceeds 300 chars.")

    # Check Founders Wing anti-patterns
    raw_str = json.dumps(data).lower()
    if "founders wing" in raw_str or "founderswing" in raw_str or "prithal" in raw_str:
        errors.append("Content contains Founders Wing references.")

    # Check Anti-AI-Slop words
    found_slop = [w for w in BANNED_SLOP if w in raw_str]
    if found_slop:
        errors.append(f"Content contains banned AI slop words: {found_slop}")

    return len(errors) == 0, errors


class PostGenerator:
    """Generates 1 LinkedIn post, 1 Carousel spec, and 3 X posts from research candidate."""

    def __init__(
        self,
        provider: Optional[LLMProvider] = None,
        dedup_log: Optional[PersonalBrandLog] = None
    ):
        self.provider = provider or LLMProvider()
        self.dedup_log = dedup_log or PersonalBrandLog()

    def generate_content_package(self, research_data: Dict[str, Any]) -> Dict[str, Any]:
        """Generates, validates, and logs personal-brand content package."""
        topic = research_data.get("topic", "")
        thesis = research_data.get("thesis", "")
        date_str = research_data.get("date") or datetime.date.today().isoformat()

        # Check deduplication prior to generation
        is_dup, prev_entry, _ = self.dedup_log.is_topic_similar(topic)
        if is_dup:
            raise ValueError(f"Topic '{topic}' is too similar to recent entry from {prev_entry.get('date')}: '{prev_entry.get('topic')}'")

        system_prompt = """
You are the primary copywriter for Lakshya's personal brand.
Lakshya is a young builder learning about technology, writing for software developers, founders, tech builders, and ambitious generalists. He researches, explains, and shares what he finds interesting — he does NOT lecture from authority.

Your goal is to write 1 LinkedIn post, 1 7-slide Carousel specification, and 3 X/Twitter posts based STRICTLY on the provided research.

BANNED WORDS (STRICTLY FORBIDDEN - NEVER USE ANY OF THESE WORDS):
"game changer", "game-changer", "revolutionary", "unlock", "leverage", "leverages", "10x", "future of work", "delve", "tapestry", "disruptive", "paradigm shift", "supercharge", "excited to share", "thought leader", "groundbreaking", "unprecedented", "synergy", "unleash", "transformative", "world-class", "journey", "ecosystem".

CRITICAL SOURCE RULES:
1. Read the source carefully. If it is a PRE-EVENT ANNOUNCEMENT (e.g. speaker lineup, agenda preview, upcoming panel), do NOT write as if the event already happened. Use future tense: "will explore", "is set to discuss". NEVER say "highlighted", "revealed", "shared" if the talk hasn't happened yet.
2. Only make factual claims that are DIRECTLY stated in the source material. Do NOT infer, extrapolate, or fabricate details not in the source.
3. If the source mentions specific numbers, dollar amounts, partnerships, or milestones, USE THEM. They make content credible.
4. Do NOT fabricate quotes. If the final_insight quote is not from a real person, do NOT wrap it in quotation marks. Present it as a plain takeaway statement.

LINKEDIN POST RULES:
1. The caption MUST start with a strong hook line (question, surprising fact, or bold claim) that stops the scroll.
2. Format with SHORT paragraphs separated by blank lines (use \n\n). Never write a single wall-of-text paragraph.
3. Include at least one specific data point or fact from the source (a number, a dollar amount, a date, a company name with context).
4. Write in first person where natural: "I was reading about...", "What caught my attention...", "Here's what I think matters for builders..."
5. End with a specific, engaging CTA question — not generic like "What do you think?".
6. Tone: Curious builder sharing what he learned, NOT a corporate press release.

X POST RULES:
1. Each post MUST be a genuinely distinct thought — NOT a shortened version of the LinkedIn post.
2. The INTERESTING post should surface one specific surprising detail or number from the source.
3. The CONTRARIAN post must present a genuinely non-obvious take that would make someone pause. "Bigger isn't always better" is NOT contrarian.
4. The BUILDER post must give one concrete, specific action — not a platitude.
5. Each post should work as a standalone thought that doesn't need the LinkedIn post for context.

CAROUSEL RULES:
1. The evidence.stat field MUST be a short number or metric (e.g. "$5.5B", "750 MW", "84%", "10x"). It is rendered at 110px font size, so it MUST be very short (under 8 characters ideally, never more than 15). NEVER put a full sentence in stat.
2. The evidence.explanation field is where you put the context sentence explaining the stat.
3. Each slide must advance the argument — no repeating the same idea across slides.
4. The final_insight.quote should be a memorable takeaway (NOT in quotation marks unless it's a real quote from a named person).

GENERAL RULES:
1. Tone: Intelligent, concise, research-backed, practical, conversational, peer builder level.
2. NO fake personal achievements, NO fake startup metrics, NO fake customer/revenue claims.
3. Strictly ground factual claims in the supplied research sources.
4. NO Founders Wing references.

OUTPUT FORMAT:
Return ONLY valid JSON matching this exact structure:
{
  "date": "YYYY-MM-DD",
  "topic": "...",
  "thesis": "...",
  "category": "AI & Software",
  "linkedin": {
    "caption": "Full LinkedIn post text with \\n\\n between paragraphs. Start with hook. Include specific data. End with CTA.",
    "sources": [{"title": "...", "url": "..."}]
  },
  "carousel": {
    "date": "YYYY-MM-DD",
    "topic": "...",
    "category": "AI & Software",
    "thesis": "...",
    "hook": {"headline": "...", "subtitle": "..."},
    "context": {"headline": "...", "points": ["...", "...", "..."]},
    "misunderstanding": {"myth": "...", "reality": "..."},
    "evidence": {"stat": "SHORT NUMBER OR METRIC ONLY (e.g. $5.5B, 750MW, 84%)", "label": "...", "explanation": "..."},
    "why_it_matters": {"headline": "...", "implications": [{"target": "...", "desc": "..."}, ...]},
    "builder_takeaway": {"headline": "...", "actions": ["...", "...", "..."]},
    "final_insight": {"quote": "A memorable takeaway line (no quotation marks unless real quote from named person)", "cta": "Follow for practical AI + startup breakdowns."},
    "sources": [{"title": "...", "url": "..."}]
  },
  "x_posts": [
    {
      "angle": "interesting",
      "text": "One specific surprising detail from the source (max 280 chars)",
      "sources": []
    },
    {
      "angle": "contrarian",
      "text": "A genuinely non-obvious, debatable take (max 280 chars)",
      "sources": []
    },
    {
      "angle": "builder",
      "text": "One concrete, specific builder action (max 280 chars)",
      "sources": []
    }
  ]
}
"""

        user_prompt = f"""
RESEARCH INPUT DATA:
Date: {date_str}
Topic: {topic}
Why Now: {research_data.get('why_now', '')}
Potential Angle: {research_data.get('potential_angle', '')}
Thesis: {thesis}
Category: {research_data.get('category', 'AI & Software')}
Sources: {json.dumps(research_data.get('sources', []))}

IMPORTANT REMINDERS:
- Check if the source is a pre-event announcement or a post-event report. Frame tense accordingly.
- The carousel evidence.stat MUST be a short number/metric (under 15 chars), NOT a sentence.
- LinkedIn post MUST have multiple paragraphs (use \\n\\n), NOT one blob.
- Each X post must be a distinct standalone thought.
- Use specific numbers and facts from the source, not abstract generalities.

Generate the complete JSON package now.
"""

        last_errors = []
        failed_providers = []
        current_user_prompt = user_prompt

        for attempt in range(3):
            try:
                raw_response = self.provider.generate(system_prompt, current_user_prompt, exclude_providers=failed_providers)
            except Exception as gen_err:
                last_errors = [f"Provider generation error: {gen_err}"]
                break

            used_provider = getattr(self.provider, "last_used_provider", None)

            try:
                data = extract_and_parse_json(raw_response)
            except ValueError as parse_err:
                err_msg = str(parse_err)
                last_errors = [err_msg]
                if used_provider:
                    failed_providers.append(used_provider)
                current_user_prompt = (
                    user_prompt +
                    f"\n\nPREVIOUS GENERATION ATTEMPT FAILED: {err_msg}.\n"
                    "Please return ONLY a single valid, complete JSON object matching the required schema, "
                    "with properly escaped strings, no raw control characters, and no surrounding text or markdown code fences."
                )
                continue

            data["date"] = date_str

            valid, errors = validate_content_package(data)
            if valid:
                self.dedup_log.add_entry(
                    topic=topic,
                    angle=research_data.get("potential_angle", ""),
                    thesis=thesis,
                    linkedin_hook=data["carousel"]["hook"].get("headline", ""),
                    x_themes=[p["angle"] for p in data["x_posts"]],
                    sources=research_data.get("sources", []),
                    date_str=date_str
                )
                return data

            last_errors = errors
            current_user_prompt = (
                user_prompt +
                f"\n\nPREVIOUS GENERATION ATTEMPT FAILED QUALITY CONTROL:\n{errors}\n"
                "Please fix these issues and return ONLY a valid JSON package matching the required schema without any banned words."
            )

        raise ValueError(f"Content package failed editorial quality validation after 3 attempts: {last_errors}")

    def save_content_artifacts(self, package: Dict[str, Any]) -> Dict[str, Path]:
        """Saves generated content into structured directories content/linkedin/, content/x/, content/."""
        date_str = package.get("date") or datetime.date.today().isoformat()
        root_dir = Path(__file__).resolve().parent.parent

        linkedin_dir = root_dir / "content" / "linkedin" / date_str
        x_dir = root_dir / "content" / "x" / date_str
        daily_dir = root_dir / "content" / date_str

        linkedin_dir.mkdir(parents=True, exist_ok=True)
        x_dir.mkdir(parents=True, exist_ok=True)
        daily_dir.mkdir(parents=True, exist_ok=True)

        li_file = linkedin_dir / "linkedin_post.md"
        with open(li_file, "w", encoding="utf-8") as f:
            f.write(f"# LinkedIn Post — {date_str}\n\n")
            f.write(f"**Topic:** {package['topic']}\n\n")
            f.write("---\n\n")
            f.write(package["linkedin"]["caption"])

        x_json_file = x_dir / "x_posts.json"
        with open(x_json_file, "w", encoding="utf-8") as f:
            json.dump(package["x_posts"], f, indent=2, ensure_ascii=False)

        x_md_file = x_dir / "x_posts.md"
        with open(x_md_file, "w", encoding="utf-8") as f:
            f.write(f"# X / Twitter Posts — {date_str}\n\n")
            for idx, xp in enumerate(package["x_posts"], 1):
                f.write(f"### Post {idx} ({xp['angle'].upper()})\n\n")
                f.write(f"{xp['text']}\n\n")
                f.write("---\n\n")

        package_file = daily_dir / "daily_content_package.json"
        with open(package_file, "w", encoding="utf-8") as f:
            json.dump(package, f, indent=2, ensure_ascii=False)

        return {
            "linkedin_md": li_file,
            "x_json": x_json_file,
            "x_md": x_md_file,
            "package_json": package_file
        }
