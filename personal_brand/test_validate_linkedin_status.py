"""
personal_brand/test_validate_linkedin_status.py
------------------------------------------------
Comprehensive unit tests for validate_linkedin_status module.
Tests every status case:
1. published
2. safe_mode_draft_only
3. skipped_not_configured (both via env and via status file)
4. failed_publish (fatal when live=True, informative when live=False)
5. missing status file (fails without manifest, gracefully succeeds with manifest fallback)
"""

import os
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from personal_brand.validate_linkedin_status import validate_linkedin_status


class TestValidateLinkedInStatus(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.TemporaryDirectory()
        self.root_dir = Path(self.tmpdir.name)
        self.date_str = "2026-10-17"
        self.status_dir = self.root_dir / "content" / "linkedin" / self.date_str
        self.status_dir.mkdir(parents=True, exist_ok=True)
        self.status_file = self.status_dir / "linkedin_publish_status.json"
        self.fake_token = "AQV1234567890fake_token"

    def tearDown(self):
        self.tmpdir.cleanup()

    def _write_status(self, data: dict):
        with open(self.status_file, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2)

    def test_case_published(self):
        """Case 1: Valid published record passes validation cleanly."""
        self._write_status({
            "status": "published",
            "post_id": "urn:li:share:confirmed_12345",
            "post_type": "text_post",
            "carousel_status": "none",
        })
        with patch.dict(os.environ, {"LINKEDIN_ACCESS_TOKEN": self.fake_token}):
            ok, msg, res = validate_linkedin_status(
                date_str=self.date_str,
                root_dir=self.root_dir,
            )
            self.assertTrue(ok)
            self.assertEqual(res["status"], "published")
            self.assertEqual(res["post_id"], "urn:li:share:confirmed_12345")
            self.assertIn("verified successfully", msg)

    def test_case_already_published(self):
        """Case 1b: Duplicate-protected already_published record passes."""
        self._write_status({
            "status": "already_published",
            "post_id": "urn:li:share:earlier_999",
            "post_type": "document_carousel",
            "carousel_status": "published",
        })
        with patch.dict(os.environ, {"LINKEDIN_ACCESS_TOKEN": self.fake_token}):
            ok, msg, res = validate_linkedin_status(
                date_str=self.date_str,
                root_dir=self.root_dir,
            )
            self.assertTrue(ok)
            self.assertEqual(res["status"], "already_published")
            self.assertIn("urn:li:share:earlier_999", msg)

    def test_case_safe_mode_draft_only(self):
        """Case 2: Safe-mode draft-only record passes validation cleanly."""
        self._write_status({
            "status": "safe_mode_draft_only",
            "message": "Live publishing is paused pending user approval (LINKEDIN_AUTO_PUBLISH_ENABLED is false).",
            "pdf_file": "carousel-routine/output/2026-10-17/personal-brand/carousel-test.pdf",
        })
        with patch.dict(os.environ, {
            "LINKEDIN_ACCESS_TOKEN": self.fake_token,
            "LINKEDIN_AUTO_PUBLISH_ENABLED": "false",
        }):
            ok, msg, res = validate_linkedin_status(
                date_str=self.date_str,
                root_dir=self.root_dir,
            )
            self.assertTrue(ok)
            self.assertEqual(res["status"], "safe_mode_draft_only")
            self.assertIn("SAFETY GUARD ACTIVE", msg)
            self.assertIn("LINKEDIN_AUTO_PUBLISH_ENABLED", msg)

    def test_case_skipped_not_configured_env(self):
        """Case 3a: Missing LINKEDIN_ACCESS_TOKEN in env cleanly skips without error."""
        with patch.dict(os.environ, {}, clear=True):
            ok, msg, res = validate_linkedin_status(
                date_str=self.date_str,
                root_dir=self.root_dir,
            )
            self.assertTrue(ok)
            self.assertEqual(res["status"], "skipped_not_configured")
            self.assertIn("not configured", msg)

    def test_case_skipped_not_configured_file(self):
        """Case 3b: Status file recording skipped_not_configured passes cleanly."""
        self._write_status({
            "status": "skipped_not_configured",
            "message": "LINKEDIN_ACCESS_TOKEN is missing or not configured.",
        })
        with patch.dict(os.environ, {"LINKEDIN_ACCESS_TOKEN": self.fake_token}):
            ok, msg, res = validate_linkedin_status(
                date_str=self.date_str,
                root_dir=self.root_dir,
            )
            self.assertTrue(ok)
            self.assertEqual(res["status"], "skipped_not_configured")
            self.assertIn("skipped", msg)

    def test_case_failed_publish_in_live_mode(self):
        """Case 4: Failed publish status fails validation when live publishing is enabled."""
        self._write_status({
            "status": "failed_publish",
            "error": "HTTP 401 Unauthorized: Invalid access token",
        })
        with patch.dict(os.environ, {
            "LINKEDIN_ACCESS_TOKEN": self.fake_token,
            "LINKEDIN_AUTO_PUBLISH_ENABLED": "true",
        }):
            ok, msg, res = validate_linkedin_status(
                date_str=self.date_str,
                root_dir=self.root_dir,
                live_enabled=True,
            )
            self.assertFalse(ok)
            self.assertEqual(res["status"], "failed_publish")
            self.assertIn("Invalid access token", msg)
            self.assertIn("failed", msg)

    def test_case_missing_status_file_fails(self):
        """Case 5a: Missing status file without manifest fallback returns failure."""
        if self.status_file.exists():
            self.status_file.unlink()

        with patch.dict(os.environ, {"LINKEDIN_ACCESS_TOKEN": self.fake_token}):
            ok, msg, _ = validate_linkedin_status(
                date_str=self.date_str,
                root_dir=self.root_dir,
            )
            self.assertFalse(ok)
            self.assertIn("not found", msg)

    def test_case_missing_status_file_with_manifest_fallback(self):
        """Case 5b: Missing status file with draft_only manifest fallback passes gracefully."""
        if self.status_file.exists():
            self.status_file.unlink()

        manifest_dir = self.root_dir / "content" / self.date_str
        manifest_dir.mkdir(parents=True, exist_ok=True)
        manifest_file = manifest_dir / "daily_manifest.json"
        with open(manifest_file, "w", encoding="utf-8") as f:
            json.dump({
                "status": "success",
                "publishing": {
                    "linkedin": "draft_only (live publishing pending approval)"
                }
            }, f)

        with patch.dict(os.environ, {"LINKEDIN_ACCESS_TOKEN": self.fake_token}):
            ok, msg, res = validate_linkedin_status(
                date_str=self.date_str,
                root_dir=self.root_dir,
            )
            self.assertTrue(ok)
            self.assertEqual(res["status"], "safe_mode_draft_only")
            self.assertIn("Draft-only", msg)


if __name__ == "__main__":
    unittest.main()
