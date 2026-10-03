"""
personal_brand/carousel_builder.py
----------------------------------
Builds a 7-slide personal-brand carousel for Lakshya.
Transforms structured content JSON into 7 HTML slides (1080x1080),
writes them to carousel-routine/temp/personal-brand/, and invokes the
existing renderer (render.js & render-pdf.js) to produce PNGs and PDF.
"""

from pathlib import Path
import json
import datetime
import hashlib
import subprocess
import sys
import argparse
from typing import Dict, Any, List, Optional

# Accent Color Palette for Lakshya's Personal Brand
ACCENT_PALETTE: List[str] = [
    "#0070F3",  # Electric Blue
    "#D9785B",  # Terracotta / Salmon
    "#10A37F",  # Emerald Mint
    "#7C5CFC",  # Deep Violet
    "#E4572E",  # Coral Orange
]


def select_accent_color(seed_string: str) -> str:
    """Deterministically select an accent color based on seed text hash."""
    h = hashlib.md5(seed_string.encode("utf-8")).hexdigest()
    idx = int(h, 16) % len(ACCENT_PALETTE)
    return ACCENT_PALETTE[idx]


def validate_image_quality(
    image_path_or_url: str,
    min_longest_side: int = 1600,
    min_bytes: int = 10000
) -> tuple[bool, str]:
    """
    Validates image resolution and quality for LinkedIn carousel standards.
    Requirements:
    - Target at least 1600px on the longest side for source visuals.
    - Reject any blurry, pixelated, stretched, or low-resolution images.
    - Maintain correct aspect ratio (0.3 <= aspect <= 3.0).
    """
    path = Path(image_path_or_url)
    if not path.exists() or not path.is_file():
        return False, "File does not exist"
    if path.stat().st_size < min_bytes:
        return False, f"File size too small ({path.stat().st_size} bytes)"

    try:
        from PIL import Image
        with Image.open(path) as img:
            w, h = img.size
            if w <= 0 or h <= 0:
                return False, "Invalid image dimensions"

            longest_side = max(w, h)
            if longest_side < min_longest_side:
                return False, f"Resolution too low ({w}x{h}, longest side {longest_side}px < {min_longest_side}px requirement)"

            aspect_ratio = w / h
            if aspect_ratio < 0.3 or aspect_ratio > 3.0:
                return False, f"Distorted aspect ratio ({aspect_ratio:.2f})"

            return True, "Valid high-resolution visual"
    except Exception as e:
        return False, f"Image quality check failed: {e}"


def get_base_css(accent_color: str) -> str:
    """Generates shared CSS tokens and base typography layout for 1080x1080 slides."""
    return f"""
    *, *::before, *::after {{ box-sizing: border-box; margin: 0; padding: 0; }}
    
    :root {{
        --bg-main: #F8F7F3;
        --text-primary: #111111;
        --text-secondary: #555555;
        --text-muted: #888888;
        --accent: {accent_color};
        --card-bg: #FFFFFF;
        --card-border: rgba(0, 0, 0, 0.07);
        --card-shadow: 0 16px 40px rgba(0, 0, 0, 0.04);
    }}

    body {{
        width: 1080px;
        height: 1080px;
        overflow: hidden;
        background-color: var(--bg-main);
        color: var(--text-primary);
        font-family: 'Inter', -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, Helvetica, Arial, sans-serif;
        position: relative;
        padding: 60px 70px;
        display: flex;
        flex-direction: column;
        justify-content: space-between;
    }}

    /* Header */
    .slide-header {{
        display: flex;
        justify-content: space-between;
        align-items: center;
        width: 100%;
        height: 50px;
        z-index: 10;
    }}

    .category-badge {{
        display: inline-flex;
        align-items: center;
        gap: 8px;
        font-size: 15px;
        font-weight: 700;
        letter-spacing: 2px;
        text-transform: uppercase;
        color: var(--text-secondary);
    }}

    .category-dot {{
        width: 10px;
        height: 10px;
        border-radius: 50%;
        background-color: var(--accent);
    }}

    .slide-number {{
        font-size: 15px;
        font-weight: 800;
        letter-spacing: 1px;
        color: var(--accent);
        background: rgba(0, 0, 0, 0.04);
        padding: 8px 16px;
        border-radius: 20px;
    }}

    /* Main Container */
    .slide-body {{
        flex: 1;
        display: flex;
        flex-direction: column;
        justify-content: center;
        margin: 40px 0;
        z-index: 5;
    }}

    /* Footer & Watermark */
    .slide-footer {{
        display: flex;
        justify-content: space-between;
        align-items: center;
        width: 100%;
        height: 40px;
        z-index: 10;
        border-top: 1px solid rgba(0, 0, 0, 0.06);
        padding-top: 20px;
    }}

    .source-label {{
        font-size: 16px;
        font-weight: 500;
        color: var(--text-muted);
        max-width: 500px;
        overflow: hidden;
        text-overflow: ellipsis;
        white-space: nowrap;
    }}

    .footer-right {{
        display: flex;
        align-items: center;
        gap: 24px;
    }}

    .watermark {{
        font-size: 14px;
        font-weight: 700;
        letter-spacing: 1.5px;
        text-transform: uppercase;
        color: var(--text-secondary);
        opacity: 0.85;
    }}

    .swipe-label {{
        font-size: 14px;
        font-weight: 800;
        letter-spacing: 2px;
        text-transform: uppercase;
        color: var(--text-primary);
    }}

    /* Typography Components */
    .title-huge {{
        font-size: 72px;
        font-weight: 900;
        line-height: 1.08;
        letter-spacing: -2.5px;
        color: var(--text-primary);
    }}

    .title-large {{
        font-size: 52px;
        font-weight: 800;
        line-height: 1.15;
        letter-spacing: -1.5px;
        color: var(--text-primary);
        margin-bottom: 24px;
    }}

    .text-accent {{
        color: var(--accent);
    }}

    .body-lead {{
        font-size: 28px;
        font-weight: 500;
        line-height: 1.4;
        color: var(--text-secondary);
        margin-top: 24px;
    }}

    /* Cards */
    .card {{
        background: var(--card-bg);
        border: 1px solid var(--card-border);
        box-shadow: var(--card-shadow);
        border-radius: 24px;
        padding: 40px;
    }}
    """


class CarouselBuilder:
    """Validates content input and generates 7 HTML slides, PNGs, and PDF."""

    def __init__(self, content: Dict[str, Any], date_str: Optional[str] = None):
        self.content = content
        self.date_str = date_str or content.get("date") or datetime.date.today().isoformat()
        self.topic = content.get("topic", "Technology Breakdown")
        self.category = content.get("category", "AI & Software").upper()
        self.accent_color = select_accent_color(self.date_str + self.topic)

        # Base directories
        self.root_dir = Path(__file__).resolve().parent.parent
        self.carousel_routine_dir = self.root_dir / "carousel-routine"
        self.temp_dir = self.carousel_routine_dir / "temp" / "personal-brand"
        self.output_dir = self.carousel_routine_dir / "output" / self.date_str / "personal-brand"

        self.validate_input()

    def validate_input(self) -> None:
        """Validates that required structural fields exist in content dictionary."""
        required_keys = ["topic", "hook", "context", "misunderstanding", "evidence", "why_it_matters", "builder_takeaway", "final_insight"]
        missing = [k for k in required_keys if k not in self.content]
        if missing:
            raise ValueError(f"Content input missing required carousel keys: {missing}")

    def validate_visual(self, image_path: Optional[str] = None) -> bool:
        """
        Validates visual quality for carousel usage.
        Requirements:
        - Image must exist and be valid PNG/JPEG/WebP
        - Target at least 1600px on the longest side
        - Correct aspect ratio (no extreme stretch)
        - Rejects low-resolution/blurry visuals automatically
        """
        if not image_path:
            return False
        valid, reason = validate_image_quality(image_path, min_longest_side=1600)
        if not valid:
            print(f"  ⚠️ [VISUAL REJECTED]: {reason}")
        return valid

    def _format_source_label(self) -> str:
        """Format source label from content sources list if present."""
        sources = self.content.get("sources", [])
        if sources and isinstance(sources, list) and len(sources) > 0:
            first = sources[0]
            title = first.get("title", "")
            if title:
                return f"Source: {title}"
        return ""

    def build_slide_1(self) -> str:
        """Slide 1: HOOK"""
        hook = self.content["hook"]
        headline = hook.get("headline", self.topic)
        subtitle = hook.get("subtitle", "")
        css = get_base_css(self.accent_color)

        return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8"/>
<meta name="viewport" content="width=1080, height=1080"/>
<link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;500;700;800;900&display=swap" rel="stylesheet"/>
<style>{css}</style>
</head>
<body>
  <div class="slide-header">
    <div class="category-badge">
      <div class="category-dot"></div>
      <span>{self.category}</span>
    </div>
    <div class="slide-number">01 / 07</div>
  </div>
  <div class="slide-body">
    <div class="title-huge">{headline}</div>
    {f'<div class="body-lead">{subtitle}</div>' if subtitle else ''}
  </div>
  <div class="slide-footer">
    <div class="source-label">{self._format_source_label()}</div>
    <div class="footer-right">
      <div class="watermark">Lakshya Goyal</div>
      <div class="swipe-label">SWIPE &rarr;</div>
    </div>
  </div>
</body>
</html>"""

    def build_slide_2(self) -> str:
        """Slide 2: CONTEXT"""
        ctx_data = self.content["context"]
        headline = ctx_data.get("headline", "What Changed")
        points = ctx_data.get("points", [])
        css = get_base_css(self.accent_color)

        points_html = ""
        for idx, pt in enumerate(points, 1):
            points_html += f"""
            <div style="display: flex; gap: 20px; align-items: flex-start; margin-bottom: 20px;">
                <div style="background: var(--accent); color: white; width: 36px; height: 36px; border-radius: 50%; display: flex; align-items: center; justify-content: center; font-weight: 800; font-size: 18px; flex-shrink: 0;">{idx}</div>
                <div style="font-size: 26px; font-weight: 500; color: var(--text-primary); line-height: 1.35;">{pt}</div>
            </div>"""

        return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8"/>
<meta name="viewport" content="width=1080, height=1080"/>
<link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;500;700;800;900&display=swap" rel="stylesheet"/>
<style>{css}</style>
</head>
<body>
  <div class="slide-header">
    <div class="category-badge">
      <div class="category-dot"></div>
      <span>THE SHIFT</span>
    </div>
    <div class="slide-number">02 / 07</div>
  </div>
  <div class="slide-body">
    <div class="title-large">{headline}</div>
    <div class="card" style="margin-top: 10px;">
      {points_html}
    </div>
  </div>
  <div class="slide-footer">
    <div class="source-label">{self._format_source_label()}</div>
    <div class="footer-right">
      <div class="watermark">Lakshya Goyal</div>
      <div class="swipe-label">SWIPE &rarr;</div>
    </div>
  </div>
</body>
</html>"""

    def build_slide_3(self) -> str:
        """Slide 3: MISUNDERSTANDING"""
        m_data = self.content["misunderstanding"]
        myth = m_data.get("myth", "")
        reality = m_data.get("reality", "")
        css = get_base_css(self.accent_color)

        return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8"/>
<meta name="viewport" content="width=1080, height=1080"/>
<link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;500;700;800;900&display=swap" rel="stylesheet"/>
<style>{css}</style>
</head>
<body>
  <div class="slide-header">
    <div class="category-badge">
      <div class="category-dot"></div>
      <span>MISCONCEPTION VS REALITY</span>
    </div>
    <div class="slide-number">03 / 07</div>
  </div>
  <div class="slide-body">
    <div class="title-large">The Misunderstood Part</div>
    <div style="display: flex; flex-direction: column; gap: 24px; margin-top: 10px;">
      <div class="card" style="background: rgba(220, 38, 38, 0.04); border-color: rgba(220, 38, 38, 0.15);">
        <div style="font-size: 16px; font-weight: 800; letter-spacing: 2px; color: #DC2626; text-transform: uppercase; margin-bottom: 10px;">What most people think</div>
        <div style="font-size: 28px; font-weight: 600; color: var(--text-primary); line-height: 1.35;">"{myth}"</div>
      </div>
      <div class="card" style="border-left: 6px solid var(--accent);">
        <div style="font-size: 16px; font-weight: 800; letter-spacing: 2px; color: var(--accent); text-transform: uppercase; margin-bottom: 10px;">What is actually happening</div>
        <div style="font-size: 28px; font-weight: 700; color: var(--text-primary); line-height: 1.35;">"{reality}"</div>
      </div>
    </div>
  </div>
  <div class="slide-footer">
    <div class="source-label">{self._format_source_label()}</div>
    <div class="footer-right">
      <div class="watermark">Lakshya Goyal</div>
      <div class="swipe-label">SWIPE &rarr;</div>
    </div>
  </div>
</body>
</html>"""

    def build_slide_4(self) -> str:
        """Slide 4: EVIDENCE"""
        ev_data = self.content["evidence"]
        stat = ev_data.get("stat", "")
        label = ev_data.get("label", "Key Benchmark / Stat")
        explanation = ev_data.get("explanation", "")
        image_path = ev_data.get("image_path") or ev_data.get("visual_url") or self.content.get("visual_url")
        css = get_base_css(self.accent_color)

        # High-quality visual validation check
        visual_html = ""
        if image_path and self.validate_visual(image_path):
            visual_html = f'<div style="margin-bottom: 20px;"><img src="{image_path}" style="max-height: 380px; width: 100%; object-fit: contain; border-radius: 16px;" alt="Visual Evidence"/></div>'

        # Adaptive font sizing: short stats (≤15 chars) get hero 110px treatment,
        # longer text falls back to readable 36px to prevent overflow/clipping
        if stat and len(stat) <= 15:
            stat_html = f'<div style="font-size: 110px; font-weight: 900; color: var(--accent); letter-spacing: -4px; line-height: 1;">{stat}</div>'
        elif stat:
            stat_html = f'<div style="font-size: 36px; font-weight: 800; color: var(--accent); line-height: 1.25;">{stat}</div>'
        else:
            stat_html = ''

        return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8"/>
<meta name="viewport" content="width=1080, height=1080"/>
<link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;500;700;800;900&display=swap" rel="stylesheet"/>
<style>{css}</style>
</head>
<body>
  <div class="slide-header">
    <div class="category-badge">
      <div class="category-dot"></div>
      <span>RESEARCH EVIDENCE</span>
    </div>
    <div class="slide-number">04 / 07</div>
  </div>
  <div class="slide-body">
    <div class="title-large">The Data & Proof</div>
    <div class="card" style="text-align: center; padding: 50px 40px;">
      {visual_html}
      {stat_html}
      <div style="font-size: 24px; font-weight: 800; letter-spacing: 1.5px; color: var(--text-primary); text-transform: uppercase; margin-top: 15px;">{label}</div>
      <div style="font-size: 26px; font-weight: 500; color: var(--text-secondary); margin-top: 20px; line-height: 1.4;">{explanation}</div>
    </div>
  </div>
  <div class="slide-footer">
    <div class="source-label">{self._format_source_label()}</div>
    <div class="footer-right">
      <div class="watermark">Lakshya Goyal</div>
      <div class="swipe-label">SWIPE &rarr;</div>
    </div>
  </div>
</body>
</html>"""

    def build_slide_5(self) -> str:
        """Slide 5: WHY IT MATTERS"""
        w_data = self.content["why_it_matters"]
        headline = w_data.get("headline", "Why It Matters")
        implications = w_data.get("implications", [])
        css = get_base_css(self.accent_color)

        cards_html = ""
        for imp in implications:
            target = imp.get("target", "Builders")
            desc = imp.get("desc", "")
            cards_html += f"""
            <div class="card" style="padding: 28px 36px; margin-bottom: 16px;">
                <div style="font-size: 15px; font-weight: 800; letter-spacing: 1.5px; color: var(--accent); text-transform: uppercase; margin-bottom: 6px;">For {target}</div>
                <div style="font-size: 24px; font-weight: 600; color: var(--text-primary); line-height: 1.35;">{desc}</div>
            </div>"""

        return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8"/>
<meta name="viewport" content="width=1080, height=1080"/>
<link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;500;700;800;900&display=swap" rel="stylesheet"/>
<style>{css}</style>
</head>
<body>
  <div class="slide-header">
    <div class="category-badge">
      <div class="category-dot"></div>
      <span>STRATEGIC IMPLICATIONS</span>
    </div>
    <div class="slide-number">05 / 07</div>
  </div>
  <div class="slide-body">
    <div class="title-large">{headline}</div>
    <div style="margin-top: 10px;">
      {cards_html}
    </div>
  </div>
  <div class="slide-footer">
    <div class="source-label">{self._format_source_label()}</div>
    <div class="footer-right">
      <div class="watermark">Lakshya Goyal</div>
      <div class="swipe-label">SWIPE &rarr;</div>
    </div>
  </div>
</body>
</html>"""

    def build_slide_6(self) -> str:
        """Slide 6: BUILDER TAKEAWAY"""
        b_data = self.content["builder_takeaway"]
        headline = b_data.get("headline", "Builder Playbook")
        actions = b_data.get("actions", [])
        css = get_base_css(self.accent_color)

        actions_html = ""
        for idx, act in enumerate(actions, 1):
            actions_html += f"""
            <div style="display: flex; gap: 20px; align-items: flex-start; margin-bottom: 24px;">
                <div style="background: var(--text-primary); color: white; width: 40px; height: 40px; border-radius: 12px; display: flex; align-items: center; justify-content: center; font-weight: 800; font-size: 20px; flex-shrink: 0;">{idx}</div>
                <div style="font-size: 26px; font-weight: 600; color: var(--text-primary); line-height: 1.35;">{act}</div>
            </div>"""

        return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8"/>
<meta name="viewport" content="width=1080, height=1080"/>
<link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;500;700;800;900&display=swap" rel="stylesheet"/>
<style>{css}</style>
</head>
<body>
  <div class="slide-header">
    <div class="category-badge">
      <div class="category-dot"></div>
      <span>ACTION PLAN</span>
    </div>
    <div class="slide-number">06 / 07</div>
  </div>
  <div class="slide-body">
    <div class="title-large">{headline}</div>
    <div class="card" style="padding: 45px; margin-top: 10px;">
      {actions_html}
    </div>
  </div>
  <div class="slide-footer">
    <div class="source-label">{self._format_source_label()}</div>
    <div class="footer-right">
      <div class="watermark">Lakshya Goyal</div>
      <div class="swipe-label">SWIPE &rarr;</div>
    </div>
  </div>
</body>
</html>"""

    def build_slide_7(self) -> str:
        """Slide 7: FINAL INSIGHT + CTA"""
        f_data = self.content["final_insight"]
        quote = f_data.get("quote", "Build workflows, not just wrappers.")
        cta = f_data.get("cta", "Follow for practical AI + startup breakdowns.")
        css = get_base_css(self.accent_color)

        return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8"/>
<meta name="viewport" content="width=1080, height=1080"/>
<link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;500;700;800;900&display=swap" rel="stylesheet"/>
<style>{css}</style>
</head>
<body>
  <div class="slide-header">
    <div class="category-badge">
      <div class="category-dot"></div>
      <span>FINAL INSIGHT</span>
    </div>
    <div class="slide-number">07 / 07</div>
  </div>
  <div class="slide-body" style="text-align: center; align-items: center;">
    <div class="card" style="width: 100%; padding: 60px 40px; border-top: 6px solid var(--accent);">
      <div style="font-size: 44px; font-weight: 800; color: var(--text-primary); line-height: 1.25; letter-spacing: -1px;">"{quote}"</div>
    </div>
    <div style="margin-top: 40px; background: rgba(0,0,0,0.04); border-radius: 40px; padding: 18px 36px; display: inline-flex; align-items: center; gap: 12px;">
      <div style="width: 12px; height: 12px; border-radius: 50%; background: var(--accent);"></div>
      <div style="font-size: 20px; font-weight: 700; color: var(--text-primary);">{cta}</div>
    </div>
  </div>
  <div class="slide-footer">
    <div class="source-label">{self._format_source_label()}</div>
    <div class="footer-right">
      <div class="watermark">Lakshya Goyal</div>
      <div class="swipe-label">END</div>
    </div>
  </div>
</body>
</html>"""

    def build_slides(self) -> List[str]:
        """Generates all 7 HTML slide strings."""
        return [
            self.build_slide_1(),
            self.build_slide_2(),
            self.build_slide_3(),
            self.build_slide_4(),
            self.build_slide_5(),
            self.build_slide_6(),
            self.build_slide_7(),
        ]

    def write_html_files(self) -> List[Path]:
        """Writes 7 HTML slide files to carousel-routine/temp/personal-brand/."""
        self.temp_dir.mkdir(parents=True, exist_ok=True)
        slides_html = self.build_slides()

        written_paths = []
        for idx, html_content in enumerate(slides_html, 1):
            filename = f"slide-0{idx}.html"
            file_path = self.temp_dir / filename
            with open(file_path, "w", encoding="utf-8") as f:
                f.write(html_content)
            written_paths.append(file_path)

        return written_paths

    def render_pngs(self) -> List[Path]:
        """Executes carousel-routine/render.js to render 7 PNG slides."""
        render_js = self.carousel_routine_dir / "render.js"
        if not render_js.exists():
            raise FileNotFoundError(f"Renderer script not found at {render_js}")

        cmd = ["node", str(render_js), self.date_str, "personal-brand"]
        result = subprocess.run(cmd, capture_output=True, text=True, cwd=str(self.carousel_routine_dir))

        if result.returncode != 0:
            raise RuntimeError(f"render.js failed with code {result.returncode}:\n{result.stderr}\n{result.stdout}")

        png_files = sorted(list(self.output_dir.glob("slide-*.png")))
        if len(png_files) != 7:
            raise RuntimeError(f"Expected 7 PNG slides in {self.output_dir}, found {len(png_files)}")

        return png_files

    def render_pdf(self) -> Path:
        """Executes carousel-routine/render-pdf.js to produce 7-page PDF."""
        render_pdf_js = self.carousel_routine_dir / "render-pdf.js"
        if not render_pdf_js.exists():
            raise FileNotFoundError(f"PDF script not found at {render_pdf_js}")

        cmd = ["node", str(render_pdf_js), self.date_str, "personal-brand"]
        result = subprocess.run(cmd, capture_output=True, text=True, cwd=str(self.carousel_routine_dir))

        if result.returncode != 0:
            raise RuntimeError(f"render-pdf.js failed with code {result.returncode}:\n{result.stderr}\n{result.stdout}")

        date_compact = self.date_str.replace("-", "")
        pdf_path = self.output_dir / f"carousel-{date_compact}.pdf"

        if not pdf_path.exists():
            raise FileNotFoundError(f"Expected output PDF not found at {pdf_path}")

        return pdf_path

    def generate_all(self) -> Dict[str, Any]:
        """Orchestrates HTML generation, PNG rendering, and PDF stitching."""
        html_files = self.write_html_files()
        png_files = self.render_pngs()
        pdf_file = self.render_pdf()

        return {
            "date": self.date_str,
            "topic": self.topic,
            "accent_color": self.accent_color,
            "temp_dir": str(self.temp_dir),
            "output_dir": str(self.output_dir),
            "html_files": [str(p) for p in html_files],
            "png_files": [str(p) for p in png_files],
            "pdf_file": str(pdf_file),
        }


def get_sample_content() -> Dict[str, Any]:
    """Generates a neutral technology sample content dict for testing/demo."""
    return {
        "date": datetime.date.today().isoformat(),
        "topic": "Why Autonomous AI Coding Agents Are Redefining Software Engineering",
        "category": "AI & Software Strategy",
        "thesis": "AI coding assistants are transitioning from line-completion tools to autonomous workflow agents.",
        "hook": {
            "headline": "Most Software Teams Are Misunderstanding AI Coding Agents.",
            "subtitle": "It's no longer about writing syntax faster. It's about multi-file architecture."
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
            "reality": "AI agents elevate junior developers into systems architects, raising the bar for software quality."
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
                {"target": "Founders", "desc": "Product velocity increases by 3x, lowering the cost of initial MVP validation."},
                {"target": "Engineering Leaders", "desc": "Code quality depends on automated testing and strict architecture constraints."}
            ]
        },
        "builder_takeaway": {
            "headline": "The Builder Playbook for 2026",
            "actions": [
                "Invest heavily in automated unit & integration test coverage.",
                "Define explicit coding conventions and context files in your repositories.",
                "Treat AI agents as junior pair programmers, not autonomous magic."
            ]
        },
        "final_insight": {
            "quote": "The bottleneck is no longer how fast you can write code. It's how clearly you can specify software.",
            "cta": "Follow for practical AI + startup breakdowns."
        },
        "sources": [
            {"title": "OpenAI Engineering Report, 2026", "url": "https://openai.com", "source_type": "official_company"}
        ]
    }


def main():
    parser = argparse.ArgumentParser(description="Personal Brand 7-Slide Carousel Generator")
    parser.add_argument("--input", type=str, help="Path to structured content JSON file")
    parser.add_argument("--demo", action="store_true", help="Run in demo mode using neutral sample content")
    args = parser.parse_args()

    if args.demo or not args.input:
        print("Running CarouselBuilder in demo mode with sample technology content...")
        content = get_sample_content()
    else:
        with open(args.input, "r", encoding="utf-8") as f:
            content = json.load(f)

    builder = CarouselBuilder(content=content)
    result = builder.generate_all()

    print("\n✓ Personal Brand Carousel Built Successfully!")
    print(f"  • Date:        {result['date']}")
    print(f"  • Topic:       {result['topic']}")
    print(f"  • Accent:      {result['accent_color']}")
    print(f"  • Temp HTML:   {result['temp_dir']}")
    print(f"  • Output Dir:  {result['output_dir']}")
    print(f"  • PNG Slides:  7 files (1080x1080)")
    print(f"  • PDF Result:  {result['pdf_file']}")


if __name__ == "__main__":
    main()
