#!/usr/bin/env python3
"""
run_personal_brand_daily.py
---------------------------
CLI launcher for Lakshya's Personal Brand Daily Content Pipeline.

Usage:
  python3 run_personal_brand_daily.py
  python3 run_personal_brand_daily.py --dry-run
  python3 run_personal_brand_daily.py --date 2026-09-30 --force
  python3 run_personal_brand_daily.py --skip-render
"""

import sys
import argparse
from pathlib import Path

# Ensure root directory is in sys.path
ROOT_DIR = Path(__file__).resolve().parent
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from personal_brand.orchestrator import PersonalBrandOrchestrator


def main():
    parser = argparse.ArgumentParser(description="Run Lakshya's Daily Personal Brand Content Pipeline")
    parser.add_argument("--date", type=str, help="Target date in YYYY-MM-DD format (defaults to today)")
    parser.add_argument("--dry-run", action="store_true", help="Inspect research & candidate selection without making LLM calls or saving files")
    parser.add_argument("--force", action="store_true", help="Overwrite existing daily output if it already exists")
    parser.add_argument("--skip-research", action="store_true", help="Skip live feed fetching and use default/offline candidate")
    parser.add_argument("--skip-render", action="store_true", help="Skip HTML slide rendering and PDF generation")

    args = parser.parse_args()

    try:
        orchestrator = PersonalBrandOrchestrator(
            date_str=args.date,
            dry_run=args.dry_run,
            force=args.force,
            skip_research=args.skip_research,
            skip_render=args.skip_render
        )
        result = orchestrator.execute_pipeline()
        
        if args.dry_run:
            print("\n[DRY RUN SUMMARY] Topic selected:", result.get("topic"))
        else:
            print("\n[SUCCESS SUMMARY]")
            print("  • Topic:    ", result.get("topic"))
            print("  • LinkedIn: ", result.get("linkedin_post"))
            print("  • X Posts:  ", len(result.get("x_posts", [])), "posts generated")
            print("  • PDF:      ", result.get("carousel", {}).get("pdf_file"))
    except Exception as e:
        print(f"\n❌ Pipeline failed: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()
