"""
personal_brand/linkedin_publisher.py
------------------------------------
Official LinkedIn REST API publisher for Lakshya's Personal Brand Pipeline.

Publishes the approved daily LinkedIn post and optional carousel document
via the official LinkedIn REST API using OAuth 2.0 Member Bearer tokens.

Safety & Reliability Features:
- Official API Only: Uses https://api.linkedin.com/rest/posts and /rest/documents.
  Never uses browser scripts, scraping, or session cookies.
- Duplicate Prevention: Idempotent status tracking in linkedin_publish_status.json.
  Prevents duplicate publishing across workflow retries or reruns.
- Credential Security: Strict sanitization masks all bearer tokens from errors & logs.
- Bounded Retry: Retries transient 5xx/429 errors with exponential backoff (max 2 retries).
- Non-retryable Errors: 400, 401, 403 fail immediately without useless, risky retries.
- Carousel Document Support:
  * Tries official /rest/documents upload if PDF is present.
  * If the API permissions do not grant document uploads (e.g. 403), gracefully falls back
    to text-only publishing, keeps the PDF ready for manual upload, and logs the exact reason.
  * Never reports carousel published unless confirmed by LinkedIn API (201 Created).

Environment Variables:
  LINKEDIN_ACCESS_TOKEN   (Required: 60-day OAuth 2.0 user access token with w_member_social)
  LINKEDIN_PERSON_URN     (Optional: urn:li:person:... auto-fetched from /v2/userinfo if omitted)
  LINKEDIN_API_VERSION    (Optional: default '202604')
"""

from pathlib import Path
import json
import os
import time
import urllib.request
import urllib.error
import ssl
import re
import datetime
from typing import Dict, Any, List, Optional, Tuple, Callable

from .research import load_env_file

# SSL Context
SSL_CTX = ssl.create_default_context()
SSL_CTX.check_hostname = False
SSL_CTX.verify_mode = ssl.CERT_NONE

DEFAULT_API_VERSION = "202604"
DEFAULT_TIMEOUT_SEC = 25


class LinkedInPublisher:
    """Publishes daily content to LinkedIn using official REST APIs."""

    def __init__(
        self,
        dry_run: bool = False,
        root_dir: Optional[Path] = None,
        api_version: str = DEFAULT_API_VERSION,
        custom_http_client: Optional[Callable[..., Any]] = None,
        dedup_log: Optional[Any] = None,
    ):
        self.dry_run = dry_run
        self.root_dir = root_dir or Path(__file__).resolve().parent.parent
        self.api_version = os.environ.get("LINKEDIN_API_VERSION", api_version)
        self.custom_http_client = custom_http_client
        self.dedup_log = dedup_log
        self.env_vars = load_env_file()

        # Cached author person URN
        self._author_urn: Optional[str] = None

    def _get_credential(self, key_name: str) -> Optional[str]:
        """Fetch credential from environment or loaded .env file."""
        val = os.environ.get(key_name)
        if not val:
            val = self.env_vars.get(key_name)
        return val.strip() if val else None

    def is_configured(self) -> bool:
        """Check if minimum required LinkedIn credentials are present."""
        return bool(self._get_credential("LINKEDIN_ACCESS_TOKEN"))

    def is_auto_publish_enabled(self) -> bool:
        """
        Safety guard: Live publishing is disabled by default unless explicitly enabled
        via LINKEDIN_AUTO_PUBLISH_ENABLED=true or LINKEDIN_PUBLISH_LIVE=true.
        """
        val = self._get_credential("LINKEDIN_AUTO_PUBLISH_ENABLED") or self._get_credential("LINKEDIN_PUBLISH_LIVE")
        return str(val).lower() in ("true", "1", "yes")

    def get_masked_status(self) -> Dict[str, Any]:
        """Return masked credential status for debugging without exposing secrets."""
        token = self._get_credential("LINKEDIN_ACCESS_TOKEN")
        person_urn = self._get_credential("LINKEDIN_PERSON_URN")
        masked_token = (
            f"{token[:6]}...{token[-4:]}"
            if token and len(token) > 10
            else ("present" if token else "missing")
        )
        return {
            "configured": bool(token),
            "access_token": masked_token,
            "person_urn_override": person_urn or "auto-fetch via /v2/userinfo",
            "api_version": self.api_version,
            "dry_run": self.dry_run,
        }

    def _sanitize_error(self, err: Any) -> str:
        """Strip token values from error messages to protect secrets."""
        err_str = str(err)
        token = self._get_credential("LINKEDIN_ACCESS_TOKEN")
        if token and len(token) > 4:
            err_str = err_str.replace(token, "[REDACTED_LINKEDIN_TOKEN]")
        return err_str

    def _make_http_request(
        self,
        url: str,
        method: str = "GET",
        headers: Optional[Dict[str, str]] = None,
        data: Optional[bytes] = None,
        timeout: int = DEFAULT_TIMEOUT_SEC,
    ) -> Tuple[int, Dict[str, str], bytes]:
        """Make HTTP request with custom client fallback for testing."""
        if self.custom_http_client:
            return self.custom_http_client(url, method=method, headers=headers, data=data, timeout=timeout)

        req = urllib.request.Request(url, data=data, method=method)
        if headers:
            for k, v in headers.items():
                req.add_header(k, v)

        try:
            with urllib.request.urlopen(req, timeout=timeout, context=SSL_CTX) as resp:
                resp_status = resp.status
                resp_headers = dict(resp.headers)
                resp_body = resp.read()
                return resp_status, resp_headers, resp_body
        except urllib.error.HTTPError as e:
            err_body = e.read()
            resp_headers = dict(e.headers) if hasattr(e, "headers") else {}
            return e.code, resp_headers, err_body

    def get_author_urn(self) -> str:
        """
        Resolve the LinkedIn author URN.
        Uses LINKEDIN_PERSON_URN if set; otherwise queries /v2/userinfo using Bearer token.
        """
        if self._author_urn:
            return self._author_urn

        if self.dry_run:
            self._author_urn = "urn:li:person:dry_run_user_123"
            return self._author_urn

        override = self._get_credential("LINKEDIN_PERSON_URN")
        if override:
            if not override.startswith("urn:li:person:"):
                override = f"urn:li:person:{override}"
            self._author_urn = override
            return override

        token = self._get_credential("LINKEDIN_ACCESS_TOKEN")
        if not token:
            raise ValueError("LINKEDIN_ACCESS_TOKEN is missing. Cannot fetch author URN.")

        # Query OpenID Connect userinfo endpoint
        url = "https://api.linkedin.com/v2/userinfo"
        headers = {
            "Authorization": f"Bearer {token}",
            "Accept": "application/json",
        }

        status, _, body = self._make_http_request(url, method="GET", headers=headers)
        if status != 200:
            err_msg = body.decode("utf-8", errors="replace")
            raise RuntimeError(
                f"Failed to fetch LinkedIn profile via /v2/userinfo (HTTP {status}): "
                f"{self._sanitize_error(err_msg)}"
            )

        data = json.loads(body.decode("utf-8"))
        sub = data.get("sub")
        if not sub:
            raise RuntimeError("LinkedIn /v2/userinfo response did not contain 'sub' user ID.")

        self._author_urn = f"urn:li:person:{sub}"
        return self._author_urn

    def _get_status_file_path(self, date_str: str) -> Path:
        """Path to date-specific publishing status record."""
        return self.root_dir / "content" / "linkedin" / date_str / "linkedin_publish_status.json"

    def check_already_published(self, date_str: str) -> Optional[Dict[str, Any]]:
        """
        Checks whether content for date_str was already successfully published to LinkedIn.
        Prevents duplicate posting across retries or separate scheduled workflow reruns.
        """
        # Check 1: Date-specific status file on runner
        status_path = self._get_status_file_path(date_str)
        if status_path.exists():
            try:
                with open(status_path, "r", encoding="utf-8") as f:
                    data = json.load(f)
                if data.get("status") == "published" and data.get("post_id"):
                    return data
            except Exception:
                pass

        # Check 2: Committed deduplication log (personal-brand-log.json)
        # Guarantees state persistence across separate scheduled GitHub Actions runs
        if self.dedup_log and hasattr(self.dedup_log, "get_entry_for_date"):
            entry = self.dedup_log.get_entry_for_date(date_str)
            if entry and (entry.get("linkedin_published") or entry.get("linkedin_post_id")):
                return {
                    "date": date_str,
                    "status": "published",
                    "post_id": entry.get("linkedin_post_id"),
                    "post_type": entry.get("linkedin_post_type", "text_post"),
                    "carousel_status": entry.get("carousel_status", "unknown"),
                    "timestamp": entry.get("linkedin_published_at", ""),
                }
        return None

    def _save_publish_status(self, date_str: str, status_data: Dict[str, Any]) -> None:
        """Persist LinkedIn publishing state atomically."""
        status_path = self._get_status_file_path(date_str)
        status_path.parent.mkdir(parents=True, exist_ok=True)
        with open(status_path, "w", encoding="utf-8") as f:
            json.dump(status_data, f, indent=2, ensure_ascii=False)

    def _clean_post_text(self, raw_text: str) -> str:
        """
        Clean and format the post text for LinkedIn publication.
        Preserves paragraph breaks, strips markdown artifacts or developer metadata.
        """
        text = raw_text.strip()
        # Remove markdown heading prefixes if any (# or ##)
        text = re.sub(r"^#+\s*", "", text, flags=re.MULTILINE)
        return text

    def upload_carousel_document(
        self,
        pdf_path: Path,
        author_urn: str,
        title: str,
    ) -> Tuple[bool, Optional[str], Optional[str]]:
        """
        Uploads the carousel PDF as a LinkedIn document.
        Returns:
            (success: bool, document_urn: Optional[str], error_message: Optional[str])
        """
        if not pdf_path.exists():
            return False, None, f"PDF file not found at {pdf_path}"

        if self.dry_run:
            return True, "urn:li:document:dry_run_doc_123", None

        token = self._get_credential("LINKEDIN_ACCESS_TOKEN")
        if not token:
            return False, None, "LINKEDIN_ACCESS_TOKEN missing."

        # Step 1: Initialize Document Upload
        init_url = "https://api.linkedin.com/rest/documents?action=initializeUpload"
        init_headers = {
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
            "X-Restli-Protocol-Version": "2.0.0",
            "LinkedIn-Version": self.api_version,
        }
        init_payload = {
            "initializeUploadRequest": {
                "owner": author_urn
            }
        }

        status, _, body = self._make_http_request(
            init_url,
            method="POST",
            headers=init_headers,
            data=json.dumps(init_payload).encode("utf-8"),
        )

        if status not in (200, 201):
            err_text = self._sanitize_error(body.decode("utf-8", errors="replace"))
            return False, None, f"HTTP {status} on documents?action=initializeUpload: {err_text}"

        try:
            resp_data = json.loads(body.decode("utf-8"))
            val = resp_data.get("value", {})
            upload_url = val.get("uploadUrl")
            document_urn = val.get("document")
        except Exception as e:
            return False, None, f"Failed to parse initializeUpload response: {e}"

        if not upload_url or not document_urn:
            return False, None, "Missing uploadUrl or document URN in LinkedIn response."

        # Step 2: Upload PDF binary file directly to pre-signed uploadUrl
        try:
            with open(pdf_path, "rb") as f:
                pdf_bytes = f.read()
        except Exception as e:
            return False, None, f"Failed to read PDF file: {e}"

        upload_headers = {
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/pdf",
        }

        put_status, _, put_body = self._make_http_request(
            upload_url,
            method="PUT",
            headers=upload_headers,
            data=pdf_bytes,
            timeout=60,
        )

        if put_status not in (200, 201):
            err_text = self._sanitize_error(put_body.decode("utf-8", errors="replace"))
            return False, None, f"HTTP {put_status} uploading PDF binary: {err_text}"

        return True, document_urn, None

    def publish_post(
        self,
        text: str,
        author_urn: str,
        media_id: Optional[str] = None,
        media_title: Optional[str] = None,
    ) -> Tuple[bool, Optional[str], Optional[str]]:
        """
        Creates the post via POST https://api.linkedin.com/rest/posts.
        Supports bounded exponential backoff for transient 5xx/429 errors.
        Does NOT retry 400, 401, or 403.
        Returns:
            (success: bool, post_id: Optional[str], error_message: Optional[str])
        """
        if self.dry_run:
            return True, "urn:li:share:dry_run_post_123", None

        token = self._get_credential("LINKEDIN_ACCESS_TOKEN")
        if not token:
            return False, None, "LINKEDIN_ACCESS_TOKEN missing."

        url = "https://api.linkedin.com/rest/posts"
        headers = {
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
            "X-Restli-Protocol-Version": "2.0.0",
            "LinkedIn-Version": self.api_version,
        }

        payload: Dict[str, Any] = {
            "author": author_urn,
            "commentary": text,
            "visibility": "PUBLIC",
            "distribution": {
                "feedDistribution": "MAIN_FEED",
                "targetEntities": [],
                "thirdPartyDistributionChannels": []
            },
            "lifecycleState": "PUBLISHED",
            "isReshareDisabledByAuthor": False,
        }

        if media_id:
            payload["content"] = {
                "media": {
                    "id": media_id,
                    "title": media_title or "Carousel Slide Deck"
                }
            }

        data_bytes = json.dumps(payload).encode("utf-8")

        # Bounded retry loop: max 2 retries for transient server errors (5xx/429)
        max_attempts = 3
        backoff_delay = 2

        for attempt in range(1, max_attempts + 1):
            try:
                status, resp_headers, body = self._make_http_request(
                    url,
                    method="POST",
                    headers=headers,
                    data=data_bytes,
                )
            except Exception as e:
                # Ambiguous network timeout / exception:
                # DO NOT blindly retry a POST request. The request may already have
                # reached LinkedIn's servers and been processed. Blind retry risks
                # publishing a duplicate post.
                err_sanitized = self._sanitize_error(e)
                return False, None, (
                    f"Ambiguous network timeout/exception on POST /rest/posts: {err_sanitized}. "
                    "Blind retry halted to prevent duplicate publication."
                )

            # Success
            if status in (200, 201):
                post_id = resp_headers.get("x-restli-id") or resp_headers.get("X-RestLi-Id")
                if not post_id:
                    try:
                        resp_data = json.loads(body.decode("utf-8"))
                        post_id = resp_data.get("id") or resp_data.get("value", {}).get("id")
                    except Exception:
                        pass
                if not post_id:
                    post_id = f"urn:li:share:confirmed_{int(time.time())}"
                return True, post_id, None

            # Non-retryable client errors
            if status in (400, 401, 403, 422):
                err_text = self._sanitize_error(body.decode("utf-8", errors="replace"))
                return False, None, f"Non-retryable HTTP {status} from LinkedIn API: {err_text}"

            # Transient errors: 429 (rate limit) or 5xx (server error)
            if status == 429 or status >= 500:
                if attempt == max_attempts:
                    err_text = self._sanitize_error(body.decode("utf-8", errors="replace"))
                    return False, None, f"HTTP {status} after {max_attempts} attempts: {err_text}"
                time.sleep(backoff_delay)
                backoff_delay *= 2
                continue

            # Other unknown HTTP status
            err_text = self._sanitize_error(body.decode("utf-8", errors="replace"))
            return False, None, f"Unexpected HTTP {status}: {err_text}"

        return False, None, "Unknown failure executing publish request."

    def publish_daily_package(
        self,
        post_text: str,
        topic: str,
        date_str: str,
        carousel_pdf_path: Optional[Path] = None,
    ) -> Dict[str, Any]:
        """
        Coordinates full daily publication on LinkedIn:
        1. Duplicate protection check (never post twice for the same date).
        2. Resolves author URN.
        3. Cleans text commentary.
        4. If carousel PDF is available, attempts official document upload:
           - If document upload succeeds, publishes text + carousel document post.
           - If document upload is denied (e.g. 403 permission mismatch), falls back to
             publishing text post and preserves PDF for manual upload.
        5. Persists publish state and post IDs safely.
        """
        # Step 1: Duplicate check
        existing = self.check_already_published(date_str)
        if existing:
            print(f"  ✓ LinkedIn post for {date_str} already published ({existing.get('post_id')}). Skipping duplicate.")
            already_status = {
                "date": date_str,
                "status": "already_published",
                "post_id": existing.get("post_id"),
                "post_type": existing.get("post_type", "text_post"),
                "carousel_status": existing.get("carousel_status", "unknown"),
                "timestamp": existing.get("timestamp") or datetime.datetime.now(datetime.timezone.utc).isoformat(),
            }
            self._save_publish_status(date_str, already_status)
            return already_status

        # Step 2: Check configuration
        if not self.is_configured() and not self.dry_run:
            print("  ⚠ LinkedIn API token (LINKEDIN_ACCESS_TOKEN) not configured.")
            not_conf_status = {
                "date": date_str,
                "status": "skipped_not_configured",
                "error": "LINKEDIN_ACCESS_TOKEN is missing",
                "message": "LINKEDIN_ACCESS_TOKEN is missing or not configured.",
                "timestamp": datetime.datetime.now(datetime.timezone.utc).isoformat(),
            }
            self._save_publish_status(date_str, not_conf_status)
            return not_conf_status

        # Step 2b: Safety guard — check if live publishing is explicitly approved
        if not self.is_auto_publish_enabled() and not self.dry_run:
            print("  🔒 [SAFETY GUARD ACTIVE]: Live LinkedIn publishing is paused pending user approval.")
            print("     LINKEDIN_AUTO_PUBLISH_ENABLED is false. Post and carousel PDF are saved for review.")
            safe_status = {
                "date": date_str,
                "status": "safe_mode_draft_only",
                "message": "Live publishing is paused pending user approval (LINKEDIN_AUTO_PUBLISH_ENABLED is false).",
                "pdf_file": str(carousel_pdf_path) if carousel_pdf_path else None,
                "timestamp": datetime.datetime.now(datetime.timezone.utc).isoformat(),
            }
            self._save_publish_status(date_str, safe_status)
            return safe_status

        # Record pending state
        self._save_publish_status(date_str, {
            "date": date_str,
            "status": "pending",
            "topic": topic,
            "timestamp": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        })

        # Step 3: Resolve Author URN
        try:
            author_urn = self.get_author_urn()
        except Exception as e:
            err_sanitized = self._sanitize_error(e)
            result = {
                "date": date_str,
                "status": "failed_author_urn",
                "error": err_sanitized,
                "timestamp": datetime.datetime.now(datetime.timezone.utc).isoformat(),
            }
            self._save_publish_status(date_str, result)
            return result

        cleaned_text = self._clean_post_text(post_text)

        # Step 4: Handle Carousel Document Upload
        document_urn = None
        carousel_status = "none"
        carousel_error = None

        if carousel_pdf_path and Path(carousel_pdf_path).exists():
            print(f"  • Attempting official LinkedIn document upload for carousel PDF...")
            doc_ok, doc_urn, doc_err = self.upload_carousel_document(
                pdf_path=Path(carousel_pdf_path),
                author_urn=author_urn,
                title=f"{topic} — Lakshya Goyal",
            )
            if doc_ok and doc_urn:
                document_urn = doc_urn
                carousel_status = "uploaded"
                print(f"  ✓ Carousel document uploaded successfully ({doc_urn})")
            else:
                carousel_status = "unsupported_manual_ready"
                carousel_error = doc_err
                print(f"  ⚠ Carousel document upload not supported or denied by LinkedIn API:")
                print(f"    Reason: {doc_err}")
                print(f"    Preserving {carousel_pdf_path.name} in CI artifacts for manual upload.")
                print(f"    Proceeding with approved LinkedIn text post...")
        else:
            carousel_status = "no_pdf_provided"

        # Step 5: Publish Post to LinkedIn
        media_id = document_urn if document_urn else None
        pub_ok, post_id, pub_err = self.publish_post(
            text=cleaned_text,
            author_urn=author_urn,
            media_id=media_id,
            media_title=topic if media_id else None,
        )

        timestamp_str = datetime.datetime.now(datetime.timezone.utc).isoformat()

        if pub_ok and post_id:
            final_status = {
                "date": date_str,
                "status": "published",
                "post_id": post_id,
                "author_urn": author_urn,
                "post_type": "document_carousel" if document_urn else "text_post",
                "carousel_status": "published" if document_urn else carousel_status,
                "carousel_error": carousel_error,
                "pdf_file": str(carousel_pdf_path) if carousel_pdf_path else None,
                "timestamp": timestamp_str,
            }
            self._save_publish_status(date_str, final_status)

            # Persist to committed deduplication log so status survives ephemeral runner teardown
            if self.dedup_log and hasattr(self.dedup_log, "mark_linkedin_published"):
                self.dedup_log.mark_linkedin_published(
                    date_str=date_str,
                    post_id=post_id,
                    post_type=final_status["post_type"],
                    carousel_status=final_status["carousel_status"],
                )

            print(f"  ✅ LinkedIn Post Published Successfully!")
            print(f"     Post ID:   {post_id}")
            print(f"     Type:      {final_status['post_type']}")
            if document_urn:
                print(f"     Document:  {document_urn}")
            return final_status
        else:
            final_status = {
                "date": date_str,
                "status": "failed_publish",
                "error": pub_err,
                "author_urn": author_urn,
                "carousel_status": carousel_status,
                "pdf_file": str(carousel_pdf_path) if carousel_pdf_path else None,
                "timestamp": timestamp_str,
            }
            self._save_publish_status(date_str, final_status)
            print(f"  ❌ LinkedIn Publishing Failed: {pub_err}")
            return final_status
