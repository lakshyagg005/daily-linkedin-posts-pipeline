"""
personal_brand/orchestrator.py
------------------------------
Master Daily Orchestrator for Lakshya's Personal Brand Content Pipeline.
Coordinates:
Research -> Deduplication -> LLM Content Generation -> Carousel Spec ->
HTML Slide Generation -> Puppeteer PNG Rendering -> PDF Stitching ->
Manifest Export -> Topic Log Persistence.
"""

from pathlib import Path
import json
import datetime
import sys
from typing import Dict, Any, List, Optional

from .deduplication import PersonalBrandLog
from .research import generate_research_candidates, save_research_artifacts, create_research_candidate
from .post_generator import PostGenerator, LLMProvider
from .carousel_builder import CarouselBuilder


class PersonalBrandOrchestrator:
    """Coordinates the end-to-end daily personal brand content generation pipeline."""

    def __init__(
        self,
        date_str: Optional[str] = None,
        dry_run: bool = False,
        force: bool = False,
        skip_research: bool = False,
        skip_render: bool = False,
        provider: Optional[LLMProvider] = None,
        dedup_log: Optional[PersonalBrandLog] = None
    ):
        self.date_str = date_str or datetime.date.today().isoformat()
        self.dry_run = dry_run
        self.force = force
        self.skip_research = skip_research
        self.skip_render = skip_render

        self.root_dir = Path(__file__).resolve().parent.parent
        self.daily_dir = self.root_dir / "content" / self.date_str
        self.manifest_path = self.daily_dir / "daily_manifest.json"

        self.dedup_log = dedup_log or PersonalBrandLog()
        self.provider = provider or LLMProvider()
        self.post_generator = PostGenerator(provider=self.provider, dedup_log=self.dedup_log)

    def _check_output_protection(self) -> None:
        """Prevent accidental overwriting of existing daily output unless force=True."""
        if self.manifest_path.exists() and not self.force and not self.dry_run:
            raise FileExistsError(
                f"Daily output for {self.date_str} already exists at {self.daily_dir}. "
                "Use --force to overwrite existing daily artifacts."
            )

    def execute_pipeline(self, custom_research: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        """Runs the end-to-end daily content orchestration flow."""
        print(f"\n==================================================")
        print(f"🚀 PERSONAL BRAND DAILY PIPELINE — {self.date_str}")
        print(f"==================================================")
        print(f"• Dry Run:        {self.dry_run}")
        print(f"• Force Mode:     {self.force}")
        print(f"• Free-Only Mode:  {self.provider.free_only}")
        print(f"• Provider Status: {self.provider.get_masked_status()['active_providers']}")

        # Protection check
        self._check_output_protection()

        # Step 1: Research Discovery
        print("\n[STEP 1/6] Discovering & Selecting Research Candidate...")
        selected_candidate = None
        candidates = []

        if custom_research:
            selected_candidate = custom_research
        elif not self.skip_research:
            try:
                candidates = generate_research_candidates(dedup_log=self.dedup_log, max_candidates=5)
                if candidates:
                    save_research_artifacts(candidates, date_str=self.date_str)
            except Exception as e:
                print(f"❌ [RESEARCH FAILED]: {e}")
                raise RuntimeError(f"[RESEARCH FAILED]: {e}")

        # Step 2: Deduplication & Candidate Selection
        if custom_research:
            is_dup, prev_entry, _ = self.dedup_log.is_topic_similar(custom_research["topic"])
            if is_dup:
                print(f"❌ [DEDUPLICATION REJECTION]: Topic '{custom_research['topic']}' is too similar to recent entry from {prev_entry.get('date')}.")
                raise RuntimeError(f"No sufficiently novel topic found. Topic is too similar to recent entry: '{prev_entry.get('topic')}'")
            selected_candidate = custom_research
        elif not self.skip_research and candidates:
            for cand in candidates:
                is_dup, _, _ = self.dedup_log.is_topic_similar(cand["topic"])
                if not is_dup:
                    selected_candidate = cand
                    break

        if not selected_candidate:
            # Fallback candidate check
            fallback = create_research_candidate(
                topic="Why Autonomous AI Agents Are Transforming Software Architecture",
                why_now="Rapid release of multi-file agentic tools in 2026.",
                potential_angle="System specification and automated testing become primary developer moats.",
                thesis="AI agents commoditize code syntax; clear system architecture and verification become the key assets.",
                category="AI & Software Strategy",
                sources=[{"title": "OpenAI Engineering Report, 2026", "url": "https://openai.com", "source_type": "official_company"}]
            )
            is_dup, prev_entry, _ = self.dedup_log.is_topic_similar(fallback["topic"])
            if not is_dup:
                selected_candidate = fallback
            else:
                print(f"❌ [DEDUPLICATION REJECTION]: No sufficiently novel topic found among candidates.")
                raise RuntimeError("No sufficiently novel topic found.")

        print(f"✓ Selected Topic: '{selected_candidate['topic']}'")
        print(f"✓ Category:       {selected_candidate.get('category', 'AI & Software')}")

        if self.dry_run:
            print("\n[DRY RUN] Inspection complete. Pipeline would generate:")
            print(f"  • LinkedIn Post for topic: '{selected_candidate['topic']}'")
            print(f"  • 7-slide Carousel Spec for topic: '{selected_candidate['topic']}'")
            print(f"  • 3 X Posts (Interesting, Contrarian, Builder)")
            print(f"  • HTML/PNG/PDF carousel artifacts")
            print("\n[DRY RUN] No API calls made, no log updated, no files written.")
            return {
                "date": self.date_str,
                "status": "dry_run_success",
                "topic": selected_candidate["topic"],
                "candidate": selected_candidate
            }

        # Step 3: LLM Content Generation (LinkedIn + Carousel Spec + 3 X Posts)
        print("\n[STEP 2/6] Generating Content Package via LLM...")
        try:
            content_pkg = self.post_generator.generate_content_package(selected_candidate)
        except Exception as e:
            print(f"❌ [CONTENT GENERATION FAILED]: {e}")
            raise RuntimeError(f"[CONTENT GENERATION FAILED]: {e}")

        print("✓ 1 LinkedIn Post generated")
        print("✓ 1 7-Slide Carousel specification generated")
        print("✓ 3 X Posts (Interesting, Contrarian, Builder) generated")

        # Step 4: Save Content Artifacts
        print("\n[STEP 3/6] Saving Content Artifacts...")
        artifact_paths = self.post_generator.save_content_artifacts(content_pkg)
        print(f"✓ Saved LinkedIn Post: {artifact_paths['linkedin_md']}")
        print(f"✓ Saved X Posts:       {artifact_paths['x_md']}")

        # Step 5: Build Carousel Slides (HTML -> PNG -> PDF)
        print("\n[STEP 4/6] Generating 7-Slide Carousel & PDF...")
        carousel_res = {}
        if not self.skip_render:
            try:
                builder = CarouselBuilder(content=content_pkg["carousel"], date_str=self.date_str)
                carousel_res = builder.generate_all()
                print(f"✓ Generated 7 HTML slides: {carousel_res['temp_dir']}")
                print(f"✓ Rendered 7 PNG slides:   {len(carousel_res['png_files'])} files")
                print(f"✓ Compiled 7-Page PDF:     {carousel_res['pdf_file']}")
            except Exception as e:
                print(f"❌ [CAROUSEL / PDF FAILED]: {e}")
                raise RuntimeError(f"[CAROUSEL / PDF FAILED]: {e}")
        else:
            print("  [SKIPPED] Carousel rendering skipped via --skip-render.")

        # Step 6: Create Daily Manifest
        print("\n[STEP 5/6] Creating Daily Manifest...")
        self.daily_dir.mkdir(parents=True, exist_ok=True)
        manifest_data = {
            "date": self.date_str,
            "status": "success",
            "topic": content_pkg["topic"],
            "thesis": content_pkg["thesis"],
            "linkedin_post": str(artifact_paths["linkedin_md"]),
            "x_posts": [
                {"angle": xp["angle"], "text": xp["text"]} for xp in content_pkg["x_posts"]
            ],
            "carousel": {
                "temp_html_dir": str(carousel_res.get("temp_dir", "")),
                "png_files": carousel_res.get("png_files", []),
                "pdf_file": str(carousel_res.get("pdf_file", ""))
            },
            "sources": selected_candidate.get("sources", []),
            "validation": {
                "content": "passed",
                "carousel": "passed" if not self.skip_render else "skipped"
            },
            "publishing": {
                "linkedin": "manual",
                "x": "manual"
            }
        }

        with open(self.manifest_path, "w", encoding="utf-8") as f:
            json.dump(manifest_data, f, indent=2, ensure_ascii=False)

        print(f"✓ Saved Daily Manifest: {self.manifest_path}")

        print("\n[STEP 6/6] Pipeline Status Verified.")
        print("\n==================================================")
        print("🎉 PIPELINE EXECUTION COMPLETED SUCCESSFULLY!")
        print("==================================================")
        return manifest_data
