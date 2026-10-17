"""
personal_brand/test_linkedin_publisher.py
-----------------------------------------
Unit tests for LinkedInPublisher module.
All tests use mock HTTP clients or temporary files.
Zero real network requests or credentials required.
"""

import unittest
import tempfile
import json
import os
from pathlib import Path
from unittest.mock import patch

from personal_brand.linkedin_publisher import LinkedInPublisher


class TestLinkedInPublisher(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.TemporaryDirectory()
        self.root_path = Path(self.tmpdir.name)
        self.date_str = "2026-10-17"
        self.fake_token = "AQV1234567890abcdefghijklmnopqrstuvwxyzSECRET1234"

    def tearDown(self):
        self.tmpdir.cleanup()

    def test_masked_status_and_sanitization(self):
        """Test credential masking and error sanitization."""
        with patch.dict(os.environ, {"LINKEDIN_ACCESS_TOKEN": self.fake_token}):
            publisher = LinkedInPublisher(root_dir=self.root_path)
            masked = publisher.get_masked_status()
            self.assertTrue(masked["configured"])
            self.assertIn("...", masked["access_token"])
            self.assertNotIn(self.fake_token, masked["access_token"])

            # Test error sanitization
            raw_err = f"API error with token {self.fake_token} rejected"
            sanitized = publisher._sanitize_error(raw_err)
            self.assertNotIn(self.fake_token, sanitized)
            self.assertIn("[REDACTED_LINKEDIN_TOKEN]", sanitized)

    def test_get_author_urn_from_override(self):
        """Test author URN resolution from explicit LINKEDIN_PERSON_URN."""
        with patch.dict(os.environ, {
            "LINKEDIN_ACCESS_TOKEN": self.fake_token,
            "LINKEDIN_PERSON_URN": "urn:li:person:lakshya_custom_id"
        }):
            publisher = LinkedInPublisher(root_dir=self.root_path)
            urn = publisher.get_author_urn()
            self.assertEqual(urn, "urn:li:person:lakshya_custom_id")

    def test_get_author_urn_from_userinfo(self):
        """Test author URN resolution dynamically via /v2/userinfo mock."""
        def mock_client(url, method="GET", headers=None, data=None, timeout=25):
            self.assertEqual(url, "https://api.linkedin.com/v2/userinfo")
            self.assertEqual(headers.get("Authorization"), f"Bearer {self.fake_token}")
            resp_body = json.dumps({
                "sub": "user_abc_789",
                "name": "Lakshya Goyal",
                "email": "lakshya@example.com"
            }).encode("utf-8")
            return 200, {"Content-Type": "application/json"}, resp_body

        with patch.dict(os.environ, {"LINKEDIN_ACCESS_TOKEN": self.fake_token}):
            publisher = LinkedInPublisher(root_dir=self.root_path, custom_http_client=mock_client)
            urn = publisher.get_author_urn()
            self.assertEqual(urn, "urn:li:person:user_abc_789")

    def test_publish_text_post_success(self):
        """Test successful text-only post publication."""
        calls = []

        def mock_client(url, method="GET", headers=None, data=None, timeout=25):
            calls.append((url, method))
            if "userinfo" in url:
                return 200, {}, json.dumps({"sub": "user_123"}).encode("utf-8")
            if "rest/posts" in url:
                payload = json.loads(data.decode("utf-8"))
                self.assertEqual(payload["author"], "urn:li:person:user_123")
                self.assertIn("Hello world", payload["commentary"])
                self.assertNotIn("content", payload)  # No media attachment
                return 201, {"x-restli-id": "urn:li:share:99887766"}, b"{}"
            return 404, {}, b"Not found"

        with patch.dict(os.environ, {"LINKEDIN_ACCESS_TOKEN": self.fake_token}):
            publisher = LinkedInPublisher(root_dir=self.root_path, custom_http_client=mock_client)
            res = publisher.publish_daily_package(
                post_text="## Hello world\n\nThis is a real LinkedIn test.",
                topic="AI Engineering",
                date_str=self.date_str,
            )

            self.assertEqual(res["status"], "published")
            self.assertEqual(res["post_id"], "urn:li:share:99887766")
            self.assertEqual(res["post_type"], "text_post")

            # Check status file was persisted
            status_file = self.root_path / "content" / "linkedin" / self.date_str / "linkedin_publish_status.json"
            self.assertTrue(status_file.exists())
            with open(status_file, "r") as f:
                saved = json.load(f)
                self.assertEqual(saved["post_id"], "urn:li:share:99887766")

    def test_duplicate_prevention(self):
        """Test duplicate posting is blocked when already published."""
        # Create an existing published status file
        status_dir = self.root_path / "content" / "linkedin" / self.date_str
        status_dir.mkdir(parents=True, exist_ok=True)
        status_file = status_dir / "linkedin_publish_status.json"
        with open(status_file, "w") as f:
            json.dump({
                "date": self.date_str,
                "status": "published",
                "post_id": "urn:li:share:existing_12345",
                "post_type": "text_post"
            }, f)

        # Publisher should not make any HTTP calls
        def failing_mock(url, **kwargs):
            self.fail("HTTP call made despite post already being published!")

        with patch.dict(os.environ, {"LINKEDIN_ACCESS_TOKEN": self.fake_token}):
            publisher = LinkedInPublisher(root_dir=self.root_path, custom_http_client=failing_mock)
            res = publisher.publish_daily_package(
                post_text="New text",
                topic="Duplicate topic",
                date_str=self.date_str
            )

            self.assertEqual(res["status"], "already_published")
            self.assertEqual(res["post_id"], "urn:li:share:existing_12345")

    def test_carousel_document_upload_and_post_success(self):
        """Test complete document carousel upload and publication."""
        # Create fake PDF
        pdf_file = self.root_path / "carousel-test.pdf"
        pdf_file.write_bytes(b"%PDF-1.4 test binary data")

        endpoints_called = []

        def mock_client(url, method="GET", headers=None, data=None, timeout=25):
            endpoints_called.append((url, method))
            if "userinfo" in url:
                return 200, {}, json.dumps({"sub": "user_456"}).encode("utf-8")
            if "rest/documents" in url and "initializeUpload" in url:
                return 200, {}, json.dumps({
                    "value": {
                        "uploadUrl": "https://upload.linkedin.com/signed-url/123",
                        "document": "urn:li:document:doc_abc_999"
                    }
                }).encode("utf-8")
            if "signed-url" in url and method == "PUT":
                self.assertEqual(data, b"%PDF-1.4 test binary data")
                return 201, {}, b""
            if "rest/posts" in url and method == "POST":
                payload = json.loads(data.decode("utf-8"))
                self.assertEqual(payload["content"]["media"]["id"], "urn:li:document:doc_abc_999")
                return 201, {"x-restli-id": "urn:li:share:carousel_post_555"}, b"{}"
            return 404, {}, b"Not found"

        with patch.dict(os.environ, {"LINKEDIN_ACCESS_TOKEN": self.fake_token}):
            publisher = LinkedInPublisher(root_dir=self.root_path, custom_http_client=mock_client)
            res = publisher.publish_daily_package(
                post_text="Check out this 7-slide carousel!",
                topic="AI Agents",
                date_str=self.date_str,
                carousel_pdf_path=pdf_file,
            )

            self.assertEqual(res["status"], "published")
            self.assertEqual(res["post_id"], "urn:li:share:carousel_post_555")
            self.assertEqual(res["post_type"], "document_carousel")
            self.assertEqual(res["carousel_status"], "published")

    def test_carousel_denied_falls_back_to_text_post(self):
        """
        When document upload is denied (e.g. 403 Forbidden), the publisher MUST:
        1. Gracefully fall back to text-only post
        2. Preserve PDF for manual upload
        3. Never report carousel published
        """
        pdf_file = self.root_path / "carousel-test.pdf"
        pdf_file.write_bytes(b"%PDF-1.4 test binary data")

        def mock_client(url, method="GET", headers=None, data=None, timeout=25):
            if "userinfo" in url:
                return 200, {}, json.dumps({"sub": "user_789"}).encode("utf-8")
            if "rest/documents" in url:
                # Return 403 Forbidden on document upload
                return 403, {}, b'{"message": "DOCUMENT_FORBIDDEN: Permission not granted"}'
            if "rest/posts" in url:
                payload = json.loads(data.decode("utf-8"))
                # Verify it fell back to text-only (no content media id)
                self.assertNotIn("content", payload)
                return 201, {"x-restli-id": "urn:li:share:fallback_text_post"}, b"{}"
            return 404, {}, b"Not found"

        with patch.dict(os.environ, {"LINKEDIN_ACCESS_TOKEN": self.fake_token}):
            publisher = LinkedInPublisher(root_dir=self.root_path, custom_http_client=mock_client)
            res = publisher.publish_daily_package(
                post_text="Important daily insight.",
                topic="Architecture",
                date_str=self.date_str,
                carousel_pdf_path=pdf_file,
            )

            self.assertEqual(res["status"], "published")
            self.assertEqual(res["post_id"], "urn:li:share:fallback_text_post")
            self.assertEqual(res["post_type"], "text_post")
            self.assertEqual(res["carousel_status"], "unsupported_manual_ready")
            self.assertIn("DOCUMENT_FORBIDDEN", res["carousel_error"])
            self.assertEqual(res["pdf_file"], str(pdf_file))

    def test_non_retryable_fatal_client_error(self):
        """Test 401 Unauthorized fails immediately without retrying."""
        call_count = 0

        def mock_client(url, method="GET", headers=None, data=None, timeout=25):
            nonlocal call_count
            call_count += 1
            if "userinfo" in url:
                return 200, {}, json.dumps({"sub": "user_123"}).encode("utf-8")
            if "rest/posts" in url:
                return 401, {}, b'{"message": "Expired access token"}'
            return 404, {}, b""

        with patch.dict(os.environ, {"LINKEDIN_ACCESS_TOKEN": self.fake_token}):
            publisher = LinkedInPublisher(root_dir=self.root_path, custom_http_client=mock_client)
            res = publisher.publish_daily_package(
                post_text="Text",
                topic="Topic",
                date_str=self.date_str
            )

            self.assertEqual(res["status"], "failed_publish")
            self.assertIn("401", res["error"])
            # Should have called userinfo (1) + post (1), no retries
            self.assertEqual(call_count, 2)

    def test_dry_run_mode(self):
        """Test dry run makes zero network calls and generates mock IDs."""
        publisher = LinkedInPublisher(dry_run=True, root_dir=self.root_path)
        res = publisher.publish_daily_package(
            post_text="Sample text",
            topic="Test Topic",
            date_str="2026-10-18"
        )
        self.assertEqual(res["status"], "published")
        self.assertEqual(res["post_id"], "urn:li:share:dry_run_post_123")


if __name__ == "__main__":
    unittest.main()
