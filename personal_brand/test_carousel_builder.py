"""
personal_brand/test_carousel_builder.py
----------------------------------------
Test suite for Personal Brand CarouselBuilder.
Validates input checking, HTML slide generation, 1080x1080 canvas dimensions,
no Founders Wing branding, isolated output directories, and renderer execution.
"""

import sys
import os
import json
from pathlib import Path

# Ensure workspace root is in python path
root_dir = Path(__file__).resolve().parent.parent
if str(root_dir) not in sys.path:
    sys.path.insert(0, str(root_dir))

from personal_brand.carousel_builder import CarouselBuilder, get_sample_content


def test_input_validation():
    """Test 1: Fails gracefully if required structural keys are missing."""
    invalid_content = {"topic": "Incomplete Topic"}
    try:
        builder = CarouselBuilder(content=invalid_content, date_str="2026-09-30")
        assert False, "Should have raised ValueError for missing keys"
    except ValueError as e:
        assert "missing required carousel keys" in str(e)


def test_html_generation_and_isolation():
    """Test 2: Verifies HTML slides creation, 1080x1080 canvas, and zero Founders Wing references."""
    sample_content = get_sample_content()
    builder = CarouselBuilder(content=sample_content, date_str="2026-09-30")

    html_paths = builder.write_html_files()

    # Verify exactly 7 slides produced
    assert len(html_paths) == 7

    # Verify isolated temp directory
    assert "carousel-routine/temp/personal-brand" in str(builder.temp_dir)

    for idx, path in enumerate(html_paths, 1):
        assert path.exists()
        with open(path, "r", encoding="utf-8") as f:
            html_content = f.read()

        # Canvas check
        assert "1080" in html_content

        # Founders Wing anti-pattern check
        assert "founders wing" not in html_content.lower()
        assert "founderswing" not in html_content.lower()
        assert "prithal" not in html_content.lower()


def test_renderer_and_pdf_end_to_end():
    """Test 3: End-to-End PNG rendering & PDF stitching via carousel-routine infrastructure."""
    sample_content = get_sample_content()
    date_str = "2026-09-30"
    builder = CarouselBuilder(content=sample_content, date_str=date_str)

    result = builder.generate_all()

    # Check PNG outputs
    png_files = result["png_files"]
    assert len(png_files) == 7
    for p in png_files:
        assert Path(p).exists()
        assert Path(p).stat().st_size > 5000  # Valid PNG image size

    # Check PDF output
    pdf_file = Path(result["pdf_file"])
    assert pdf_file.exists()
    assert pdf_file.name == "carousel-20260930.pdf"
    assert pdf_file.stat().st_size > 10000  # Valid PDF size


def test_watermark_on_all_slides():
    """Test 4: Verifies Lakshya Goyal watermark appears on all 7 generated HTML slides inside safe area."""
    sample_content = get_sample_content()
    builder = CarouselBuilder(content=sample_content, date_str="2026-09-30")
    html_paths = builder.write_html_files()

    assert len(html_paths) == 7
    for idx, path in enumerate(html_paths, 1):
        with open(path, "r", encoding="utf-8") as f:
            html = f.read()

        # Watermark text check
        assert "Lakshya Goyal" in html, f"Slide {idx} missing 'Lakshya Goyal' watermark"
        # Safe area / footer positioning check
        assert 'class="watermark">Lakshya Goyal</div>' in html, f"Slide {idx} watermark element malformed"
        assert 'class="footer-right">' in html, f"Slide {idx} watermark not positioned in footer-right safe area"


def test_low_quality_visual_rejection():
    """Test 5: Verifies low-resolution/blurry visuals (<1600px) are rejected, high-resolution visuals (>=1600px) accepted."""
    import tempfile
    from PIL import Image

    builder = CarouselBuilder(content=get_sample_content(), date_str="2026-09-30")

    with tempfile.TemporaryDirectory() as tmpdir:
        # Create low-res image (200x200)
        low_res_path = Path(tmpdir) / "low_res.png"
        img_low = Image.new("RGB", (200, 200), color="blue")
        img_low.save(low_res_path)

        # Create high-res image (1600x1600)
        high_res_path = Path(tmpdir) / "high_res.png"
        img_high = Image.new("RGB", (1600, 1600), color="green")
        img_high.save(high_res_path)

        # Low-resolution visual MUST be rejected
        assert builder.validate_visual(str(low_res_path)) is False, "Low-resolution visual (<1600px) was not rejected"

        # High-resolution visual MUST be accepted
        assert builder.validate_visual(str(high_res_path)) is True, "High-resolution visual (>=1600px) was unexpectedly rejected"


def run_all_tests():
    print("Running Personal Brand CarouselBuilder Unit & E2E Test Suite...")
    test_input_validation()
    print("  ✓ Test 1: Input validation passed")
    test_html_generation_and_isolation()
    print("  ✓ Test 2: 7 HTML slides, 1080x1080 canvas & path isolation passed")
    test_renderer_and_pdf_end_to_end()
    print("  ✓ Test 3: E2E PNG rendering & PDF stitching passed")
    test_watermark_on_all_slides()
    print("  ✓ Test 4: Lakshya Goyal watermark present on all 7 slides in safe area passed")
    test_low_quality_visual_rejection()
    print("  ✓ Test 5: Low-quality visual rejection (<1600px) passed")
    print("\nALL CAROUSEL BUILDER TESTS PASSED SUCCESSFULLY! 🎉")


if __name__ == "__main__":
    run_all_tests()

