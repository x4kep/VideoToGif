"""Demo E2E test: convert a real video to GIF with background removal.

Run with --headed to watch:
  python3 -m pytest tests/e2e/test_video_demo.py -v --headed
"""

import os
import signal
import subprocess
import sys
import time

import pytest

pytestmark = pytest.mark.e2e

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(__file__)))
VIDEO_PATH = os.path.join(PROJECT_ROOT, "video.mp4")


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
    ctx.set_default_timeout(180000)
    yield ctx
    ctx.close()


@pytest.fixture
def page(context):
    p = context.new_page()
    yield p
    p.close()


class TestVideoDemoWorkflow:

    def test_video_to_gif_with_bg_removal(self, page, server):
        """Upload video.mp4 → remove bg → transparent → convert to GIF."""
        if not os.path.exists(VIDEO_PATH):
            pytest.skip("video.mp4 not found in project root")

        page.goto(server)
        page.wait_for_load_state("networkidle")
        page.wait_for_timeout(1500)

        # 1. Upload video
        page.locator("#fileInput").set_input_files(VIDEO_PATH)
        page.wait_for_timeout(2000)

        # 2. Open settings
        page.click("#settingsToggle")
        page.wait_for_timeout(1000)

        # 3. Configure: small + short for speed
        page.select_option("#optWidth", "320")
        page.wait_for_timeout(500)
        page.select_option("#optFps", "10")
        page.wait_for_timeout(500)
        page.fill("#optEnd", "2")
        page.wait_for_timeout(1000)

        # 4. Enable background removal (transparent bg is default)
        page.locator("#optRemoveBg").evaluate("el => el.click()")
        page.wait_for_timeout(1500)

        # 5. Scroll down and click Convert
        page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
        page.wait_for_timeout(500)
        page.locator("#convertBtn").click()
        page.wait_for_timeout(2000)

        # 6. Wait for result — scroll down periodically to see progress
        for _ in range(60):
            page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
            if page.locator("#videoResultsGrid .batch-item img").count() > 0:
                break
            page.wait_for_timeout(2000)

        # 7. Scroll to result and admire the transparent-bg GIF
        page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
        page.wait_for_timeout(2000)

        assert page.locator("#videoResultsGrid .batch-item img").is_visible()
        assert page.locator("#videoResultsGrid .batch-item-dl").is_visible()

        # Hold so you can see the GIF playing
        page.wait_for_timeout(5000)
