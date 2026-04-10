"""Demo E2E test: process images with background removal.

Run with --headed to watch:
  python3 -m pytest tests/e2e/test_image_demo.py -v --headed
"""

import os
import signal
import subprocess
import sys
import time

import pytest
from PIL import Image, ImageDraw

pytestmark = pytest.mark.e2e

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(__file__)))


@pytest.fixture(scope="session")
def server():
    env = {**os.environ, "PORT": "5050"}
    proc = subprocess.Popen(
        [sys.executable, "app.py"],
        cwd=PROJECT_ROOT,
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    time.sleep(3)
    yield "http://localhost:5050"
    proc.send_signal(signal.SIGTERM)
    try:
        proc.wait(timeout=5)
    except subprocess.TimeoutExpired:
        proc.kill()


@pytest.fixture
def context(browser):
    video_dir = os.path.join(PROJECT_ROOT, "test-results", "videos")
    os.makedirs(video_dir, exist_ok=True)
    ctx = browser.new_context(
        viewport={"width": 1280, "height": 1200},
        record_video_dir=video_dir,
        record_video_size={"width": 1280, "height": 1200},
    )
    ctx.set_default_timeout(60000)
    yield ctx
    ctx.close()


@pytest.fixture
def page(context):
    p = context.new_page()
    yield p
    p.close()


@pytest.fixture
def test_image_with_bg(tmp_path):
    """Create a 400x400 image with a blue background and a red circle subject.

    This gives bg removal something real to work with — the red circle
    is the 'subject' and the blue is the 'background' to remove.
    """
    img = Image.new("RGB", (400, 400), (30, 120, 200))  # blue bg
    draw = ImageDraw.Draw(img)
    # Red circle in center
    draw.ellipse([100, 100, 300, 300], fill=(220, 40, 40))
    # Small yellow square as detail
    draw.rectangle([170, 170, 230, 230], fill=(255, 220, 50))
    path = tmp_path / "test_subject.png"
    img.save(str(path))
    return str(path)


@pytest.fixture
def test_image_with_whitespace(tmp_path):
    """Create an image with lots of white border around a small subject."""
    img = Image.new("RGB", (500, 500), (255, 255, 255))
    draw = ImageDraw.Draw(img)
    draw.rectangle([150, 150, 350, 350], fill=(50, 180, 80))
    draw.ellipse([200, 200, 300, 300], fill=(200, 50, 100))
    path = tmp_path / "whitespace_image.png"
    img.save(str(path))
    return str(path)


@pytest.fixture
def multiple_test_images(tmp_path):
    """Create 3 different images for bulk upload demo."""
    paths = []
    colors = [
        ((30, 120, 200), (220, 40, 40), "blue_bg"),
        ((40, 160, 60), (255, 200, 50), "green_bg"),
        ((180, 50, 180), (255, 255, 255), "purple_bg"),
    ]
    for bg_color, subject_color, name in colors:
        img = Image.new("RGB", (300, 300), bg_color)
        draw = ImageDraw.Draw(img)
        draw.ellipse([60, 60, 240, 240], fill=subject_color)
        path = tmp_path / f"{name}.png"
        img.save(str(path))
        paths.append(str(path))
    return paths


class TestImageDemoWorkflow:

    def test_single_image_remove_bg_transparent(self, page, server, test_image_with_bg):
        """Upload image → remove bg → transparent background → download."""
        page.goto(server)
        page.wait_for_load_state("networkidle")
        page.wait_for_timeout(1500)

        # 1. Click Image tab
        page.click("[data-tab='image']")
        page.wait_for_timeout(1000)

        # 2. Upload image
        page.locator("#imgFileInput").set_input_files(test_image_with_bg)
        page.wait_for_timeout(2000)

        # 3. Open settings
        page.click("#imgSettingsToggle")
        page.wait_for_timeout(1000)

        # 4. Enable Remove Background
        page.locator("#imgRemoveBg").evaluate("el => el.click()")
        page.wait_for_timeout(1500)

        # Transparent is selected by default — verify it's visible
        assert page.locator("#imgBgOptions").is_visible()
        page.wait_for_timeout(1000)

        # 5. Scroll down and click Process
        page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
        page.wait_for_timeout(500)
        page.locator("#imgProcessBtn").click()
        page.wait_for_timeout(2000)

        # 6. Wait for result
        page.wait_for_selector("#imgResultsGrid .batch-item img", timeout=30000)
        page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
        page.wait_for_timeout(2000)

        # 7. Verify result — should show checkered bg (transparency)
        assert page.locator("#imgResultsGrid .batch-item img").is_visible()
        assert page.locator("#imgResultsGrid .batch-item-dl").is_visible()
        page.wait_for_timeout(4000)

    def test_single_image_remove_bg_custom_color(self, page, server, test_image_with_bg):
        """Upload image → remove bg → custom green background."""
        page.goto(server)
        page.wait_for_load_state("networkidle")
        page.wait_for_timeout(1500)

        # 1. Image tab
        page.click("[data-tab='image']")
        page.wait_for_timeout(1000)

        # 2. Upload
        page.locator("#imgFileInput").set_input_files(test_image_with_bg)
        page.wait_for_timeout(2000)

        # 3. Open settings
        page.click("#imgSettingsToggle")
        page.wait_for_timeout(1000)

        # 4. Enable Remove Background
        page.locator("#imgRemoveBg").evaluate("el => el.click()")
        page.wait_for_timeout(1000)

        # 5. Select Custom color
        page.locator("input[name='imgBgType'][value='custom']").evaluate("el => el.click()")
        page.wait_for_timeout(1000)

        # 6. Set color to bright green
        page.locator("#imgBgColor").evaluate("el => el.value = '#00ff00'")
        page.locator("#imgBgColor").dispatch_event("input")
        page.wait_for_timeout(1500)

        # 7. Process
        page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
        page.wait_for_timeout(500)
        page.locator("#imgProcessBtn").click()
        page.wait_for_timeout(2000)

        # 8. Wait for result
        page.wait_for_selector("#imgResultsGrid .batch-item img", timeout=30000)
        page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
        page.wait_for_timeout(2000)

        assert page.locator("#imgResultsGrid .batch-item img").is_visible()
        page.wait_for_timeout(4000)

    def test_trim_whitespace(self, page, server, test_image_with_whitespace):
        """Upload image with white borders → trim spacing → smaller result."""
        page.goto(server)
        page.wait_for_load_state("networkidle")
        page.wait_for_timeout(1500)

        page.click("[data-tab='image']")
        page.wait_for_timeout(1000)

        # Upload
        page.locator("#imgFileInput").set_input_files(test_image_with_whitespace)
        page.wait_for_timeout(2000)

        # Open settings
        page.click("#imgSettingsToggle")
        page.wait_for_timeout(1000)

        # Enable trim spacing
        page.locator("#imgTrimSpacing").evaluate("el => el.click()")
        page.wait_for_timeout(1500)

        # Process
        page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
        page.wait_for_timeout(500)
        page.locator("#imgProcessBtn").click()
        page.wait_for_timeout(2000)

        # Wait for result
        page.wait_for_selector("#imgResultsGrid .batch-item img", timeout=15000)
        page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
        page.wait_for_timeout(2000)

        # Result should show trimmed image (smaller than 500x500)
        assert page.locator("#imgResultsGrid .batch-item img").is_visible()
        info_text = page.locator("#imgResultsGrid .batch-item-name").text_content()
        assert "500" not in info_text  # dimensions should be smaller
        page.wait_for_timeout(4000)

    def test_bulk_upload_remove_bg_download_all(self, page, server, multiple_test_images):
        """Upload 3 images → remove bg → process all → Download All."""
        page.goto(server)
        page.wait_for_load_state("networkidle")
        page.wait_for_timeout(1500)

        page.click("[data-tab='image']")
        page.wait_for_timeout(1000)

        # Bulk upload 3 images
        page.locator("#imgFileInput").set_input_files(multiple_test_images)
        page.wait_for_timeout(2000)

        # Open settings + enable bg removal
        page.click("#imgSettingsToggle")
        page.wait_for_timeout(1000)
        page.locator("#imgRemoveBg").evaluate("el => el.click()")
        page.wait_for_timeout(1500)

        # Process all
        page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
        page.wait_for_timeout(500)
        page.locator("#imgProcessBtn").click()
        page.wait_for_timeout(2000)

        # Wait for all 3 results
        for i in range(60):
            page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
            if page.locator("#imgResultsGrid .batch-item img").count() >= 3:
                break
            page.wait_for_timeout(2000)

        page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
        page.wait_for_timeout(2000)

        # All 3 should be done
        assert page.locator("#imgResultsGrid .batch-item img").count() >= 3

        # Download All button should be visible
        assert page.locator("#imgDownloadAll").is_visible()
        page.wait_for_timeout(3000)

        # Click Download All
        page.locator("#imgDownloadAll").click()
        page.wait_for_timeout(3000)
