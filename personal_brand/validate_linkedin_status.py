#!/usr/bin/env python3
"""
personal_brand/validate_linkedin_status.py
-----------------------------------------
Validates LinkedIn publishing status following daily pipeline execution.
Ensures:
1. Valid publishing records (published or already_published) pass.
2. Safe-mode / draft-only records (safe_mode_draft_only, draft_only) pass cleanly.
3. Skipped runs (skipped_not_configured) pass cleanly.
4. Genuine publishing failures are reported accurately with details.
5. Missing status records trigger an explicit failure (with daily_manifest fallback).
"""

import os
import sys
import json
import argparse
from pathlib import Path
from datetime import date
from typing import Optional, Dict, Any, Tuple


def validate_linkedin_status(
    date_str: Optional[str] = None,
    root_dir: Optional[Path] = None,
    live_enabled: Optional[bool] = None,
) -> Tuple[bool, str, Dict[str, Any]]:
    """
    Validate LinkedIn publishing status.
    Returns: (is_success, log_summary, status_dict)
    """
    if not date_str:
        date_str = date.today().isoformat()

    if root_dir is None:
        root_dir = Path(__file__).resolve().parent.parent

    if live_enabled is None:
        val = os.environ.get("LINKEDIN_AUTO_PUBLISH_ENABLED", "")
        live_enabled = str(val).lower() in ("true", "1", "yes")

    print(f"Checking LinkedIn publishing status for date: {date_str}")

    # Check if LinkedIn API token is configured in environment
    linkedin_token = os.environ.get("LINKEDIN_ACCESS_TOKEN")
    if not linkedin_token:
        msg = (
            "⚠ LINKEDIN_ACCESS_TOKEN not configured. Automated LinkedIn publishing was skipped.\n"
            "  To enable: generate your 60-day token and add LINKEDIN_ACCESS_TOKEN as a GitHub Secret."
        )
        print(msg)
        return True, msg, {"status": "skipped_not_configured"}

    status_path = root_dir / "content" / "linkedin" / date_str / "linkedin_publish_status.json"

    # Missing status file check with daily_manifest fallback
    if not status_path.exists():
        manifest_path = root_dir / "content" / date_str / "daily_manifest.json"
        if manifest_path.exists():
            try:
                with open(manifest_path, "r", encoding="utf-8") as mf:
                    manifest = json.load(mf)
                m_status = manifest.get("publishing", {}).get("linkedin", "")
                print(f"ℹ Manifest records LinkedIn publishing status: '{m_status}'")
                if "draft_only" in m_status or "skipped" in m_status:
                    msg = "Draft-only or skipped publishing recorded in manifest. Exiting cleanly."
                    print(f"  {msg}")
                    return True, msg, {"status": "safe_mode_draft_only", "manifest_status": m_status}
            except Exception:
                pass

        err_msg = f"❌ LinkedIn publish status file not found: {status_path}. Publishing may have failed."
        print(err_msg)
        return False, err_msg, {}

    try:
        with open(status_path, "r", encoding="utf-8") as f:
            status = json.load(f)
    except Exception as e:
        err_msg = f"❌ Could not parse status file {status_path}: {e}"
        print(err_msg)
        return False, err_msg, {}

    pub_status = status.get("status")
    post_id = status.get("post_id")
    post_type = status.get("post_type")
    carousel_status = status.get("carousel_status")

    if pub_status in ("published", "already_published") and post_id:
        lines = [
            "✅ LinkedIn post verified successfully!",
            f"  • Status:          {pub_status}",
            f"  • Post ID:         {post_id}",
            f"  • Post Type:       {post_type}",
            f"  • Carousel Status: {carousel_status}",
        ]
        msg = "\n".join(lines)
        print(msg)
        return True, msg, status

    elif pub_status in ("safe_mode_draft_only", "draft_only"):
        details = status.get("message", "Live publishing disabled.")
        lines = [
            "🔒 [SAFETY GUARD ACTIVE / DRAFT-ONLY MODE]: Live LinkedIn publishing is paused.",
            f"  • Status:          {pub_status}",
            f"  • Message:         {details}",
            "  • Note:            Post and carousel PDF are preserved for manual upload/review.",
            "  • To enable live:  Set LINKEDIN_AUTO_PUBLISH_ENABLED=true or trigger with publish_live=true.",
        ]
        msg = "\n".join(lines)
        print(msg)
        return True, msg, status

    elif pub_status == "skipped_not_configured":
        lines = [
            "⚠ LinkedIn publishing skipped: LINKEDIN_ACCESS_TOKEN is missing or not configured.",
            f"  • Status:          {pub_status}",
        ]
        msg = "\n".join(lines)
        print(msg)
        return True, msg, status

    else:
        err = status.get("error") or status.get("message") or "Unknown error"
        lines = [
            "❌ LinkedIn post publishing failed!",
            f"  • Status: {pub_status}",
            f"  • Error:  {err}",
        ]
        msg = "\n".join(lines)
        print(msg)
        # If live mode was requested, this is fatal
        if live_enabled:
            return False, msg, status
        else:
            return True, msg, status


def main() -> None:
    parser = argparse.ArgumentParser(description="Validate LinkedIn Publishing Status")
    parser.add_argument("--date", type=str, default=None, help="Date to check (YYYY-MM-DD)")
    parser.add_argument("--root-dir", type=str, default=None, help="Root directory of repository")
    parser.add_argument("--live", action="store_true", help="Assert that live publishing was enabled")
    args = parser.parse_args()

    root_dir = Path(args.root_dir) if args.root_dir else None
    live_flag = True if args.live else None

    ok, _, _ = validate_linkedin_status(
        date_str=args.date,
        root_dir=root_dir,
        live_enabled=live_flag,
    )

    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
