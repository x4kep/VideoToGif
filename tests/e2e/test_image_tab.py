"""End-to-end tests for the Image tab using Playwright.

WHAT: Drives a real Chromium browser against a running Flask server.
Tests the full user workflow: upload → configure → process → download.

WHY E2E TESTS EXIST (and why we keep them minimal):
- They catch bugs that unit and integration tests CANNOT:
  * JavaScript errors in upload handlers or FormData construction
  * CSS issues that hide buttons or results from the user
  * Race conditions in the async sequential processing loop
  * DOM wiring: does clicking "Process" actually trigger the fetch?
- They are EXPENSIVE: slow (~seconds each), brittle (sensitive to
  DOM changes), and require a running server + browser.
- Rule of thumb: 5-10 E2E tests covering critical happy paths.
  Don't duplicate what integration tests already cover.

PREREQUISITES:
  pip install pytest-playwright
  playwright install chromium
"""

import os
import signal
import subprocess
import sys
import time

import pytest

pytestmark = pytest.mark.e2e


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def el_has_class(locator, cls):
    """Check if a Playwright locator's element has a CSS class."""
    return locator.evaluate(f"el => el.classList.contains('{cls}')")


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------
@pytest.fixture(scope="session")
def server():
    """Start Flask dev server on a test port for E2E tests.

    WHY scope="session": Starting/stopping the server per test would be
    too slow. We start once for the entire test session and share it.

    WHY a separate port (5050): Avoids conflicting with a dev server
    that might be running on 5001.
    """
    env = {**os.environ, "PORT": "5050"}
    proc = subprocess.Popen(
        [sys.executable, "app.py"],
        cwd=os.path.dirname(os.path.dirname(os.path.dirname(__file__))),
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
def test_image(tmp_path):
    """Create a test PNG file on disk for Playwright file uploads.

    WHY on disk (not BytesIO): Playwright's set_input_files() needs
    a real file path — it simulates the OS file picker.
    """
    from PIL import Image
    img = Image.new("RGBA", (100, 100), (255, 0, 0, 255))
    path = tmp_path / "test_upload.png"
    img.save(str(path))
    return str(path)


@pytest.fixture
def test_images(tmp_path):
    """Create multiple test images for bulk upload tests."""
    from PIL import Image
    paths = []
    for i in range(3):
        img = Image.new("RGBA", (50, 50), (i * 80, 100, 0, 255))
        p = tmp_path / f"batch_{i}.png"
        img.save(str(p))
        paths.append(str(p))
    return paths


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------
class TestImageTabWorkflow:

    def test_upload_and_process_single_image(self, page, server, test_image):
        """CRITICAL PATH: Upload one image → process → result appears.

        This is the single most important E2E test. If this fails,
        the core feature is broken.
        """
        page.goto(server)
        page.click("[data-tab='image']")

        # Upload via hidden file input
        page.locator("#imgFileInput").set_input_files(test_image)

        # File should appear in list, Process should be enabled
        assert el_has_class(page.locator("#imgDropZone"), "has-file")
        assert page.locator("#imgProcessBtn").is_enabled()

        # Process
        page.click("#imgProcessBtn")

        # Wait for result image to appear in the batch grid
        page.wait_for_selector("#imgResultsGrid .batch-item img", timeout=15000)

        # Verify result
        assert page.locator("#imgResultsGrid .batch-item img").is_visible()
        assert page.locator("#imgResultsGrid .batch-item-dl").is_visible()

    def test_bulk_upload_shows_download_all(self, page, server, test_images):
        """Upload 3 images → process → 'Download All' button appears.

        WHY: Download All only shows when 2+ images succeed. This tests
        the counter logic and ZIP download wiring.
        """
        page.goto(server)
        page.click("[data-tab='image']")

        page.locator("#imgFileInput").set_input_files(test_images)
        page.click("#imgProcessBtn")

        # Wait for last result
        page.wait_for_selector(
            "#imgResultsGrid .batch-item:nth-child(3) img",
            timeout=30000,
        )

        # Download All should be visible
        assert page.locator("#imgDownloadAll").is_visible()

    def test_bg_removal_toggle_reveals_options(self, page, server):
        """Checking 'Remove background' shows the bg type radio group.

        WHY: Tests JavaScript event wiring — the change listener on
        #imgRemoveBg must toggle #imgBgOptions visibility.
        """
        page.goto(server)
        page.click("[data-tab='image']")

        # Open settings
        page.click("#imgSettingsToggle")
        page.wait_for_selector("#imgSettingsBody.open")

        # BG options hidden initially
        assert not page.locator("#imgBgOptions").is_visible()

        # Toggle remove BG — the checkbox is hidden by CSS (custom toggle),
        # so we click the parent label/span instead
        page.locator("#imgRemoveBg").evaluate("el => el.click()")

        # Options should appear
        page.wait_for_selector("#imgBgOptions", state="visible", timeout=3000)
        assert page.locator("#imgBgOptions").is_visible()

        # Select Custom → color picker appears
        page.locator("input[name='imgBgType'][value='custom']").evaluate("el => el.click()")
        page.wait_for_selector("#imgBgColorRow", state="visible", timeout=3000)
        assert page.locator("#imgBgColorRow").is_visible()

    def test_clear_all_resets_state(self, page, server, test_image):
        """After processing, 'Clear all' should reset everything.

        WHY: Tests that the reset handler properly clears:
        - The file list and drop zone state
        - The results grid
        - The Process button (back to disabled)
        Without this, users can't start fresh after a batch.
        """
        page.goto(server)
        page.click("[data-tab='image']")

        # Upload and process
        page.locator("#imgFileInput").set_input_files(test_image)
        page.click("#imgProcessBtn")
        page.wait_for_selector("#imgResultsGrid .batch-item img", timeout=15000)

        # Clear
        page.click("#imgResetBtn")

        # Verify reset state
        assert page.locator("#imgResultsGrid").inner_html().strip() == ""
        assert not page.locator("#imgProcessBtn").is_enabled()
        assert not el_has_class(page.locator("#imgDropZone"), "has-file")

    def test_settings_panel_toggles(self, page, server):
        """Settings panel should expand/collapse on click.

        WHY: Basic UI interaction test. If the toggle JS breaks,
        users can't access any processing options.
        """
        page.goto(server)
        page.click("[data-tab='image']")

        # Initially closed
        assert not el_has_class(page.locator("#imgSettingsBody"), "open")

        # Click to open
        page.click("#imgSettingsToggle")
        assert el_has_class(page.locator("#imgSettingsBody"), "open")

        # Click to close
        page.click("#imgSettingsToggle")
        assert not el_has_class(page.locator("#imgSettingsBody"), "open")
