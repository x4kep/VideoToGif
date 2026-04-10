"""Demo E2E test: Prompt Builder workflow.

Run with --headed to watch:
  python3 -m pytest tests/e2e/test_prompt_demo.py -v --headed
"""

import os
import signal
import subprocess
import sys
import time

import pytest

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
    ctx.set_default_timeout(30000)
    yield ctx
    ctx.close()


@pytest.fixture
def page(context):
    p = context.new_page()
    yield p
    p.close()


def el_has_class(locator, cls):
    return locator.evaluate(f"el => el.classList.contains('{cls}')")


class TestPromptBuilderWorkflow:

    def test_fill_subject_and_generate_prompt(self, page, server):
        """Type a subject → click Generate Prompt → verify output appears."""
        page.goto(server)
        page.wait_for_load_state("networkidle")
        page.wait_for_timeout(1500)

        # 1. Click Prompt Builder tab
        page.click("[data-tab='prompt']")
        page.wait_for_timeout(1000)

        # 2. Type a subject
        page.fill("#promptSubject", "A cute robot mascot with big eyes")
        page.wait_for_timeout(1500)

        # 3. Scroll down to see Generate button
        page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
        page.wait_for_timeout(500)

        # 4. Click Generate Prompt
        page.click("#generatePromptBtn")
        page.wait_for_timeout(2000)

        # 5. Verify prompt output appeared
        output = page.locator("#promptOutput")
        assert el_has_class(output, "active")
        text = output.text_content()
        assert "robot" in text.lower()
        assert "cartoon" in text.lower()  # default style

        # 6. Copy button should appear
        assert page.locator("#copyPromptBtn").is_visible()
        page.wait_for_timeout(3000)

    def test_select_action_chip_fills_textarea(self, page, server):
        """Click an action chip → textarea fills with that action."""
        page.goto(server)
        page.wait_for_load_state("networkidle")
        page.wait_for_timeout(1000)

        page.click("[data-tab='prompt']")
        page.wait_for_timeout(1000)

        # Click "Dancing" action chip
        page.click("#actionChips .chip[data-val='dancing happily']")
        page.wait_for_timeout(1500)

        # Textarea should be filled
        val = page.locator("#promptAction").input_value()
        assert val == "dancing happily"

        # Chip should be selected (highlighted)
        chip = page.locator("#actionChips .chip[data-val='dancing happily']")
        assert el_has_class(chip, "selected")
        page.wait_for_timeout(2000)

    def test_full_prompt_builder_flow(self, page, server):
        """Complete flow: subject → action → background → style → settings → generate."""
        page.goto(server)
        page.wait_for_load_state("networkidle")
        page.wait_for_timeout(1500)

        # 1. Prompt Builder tab
        page.click("[data-tab='prompt']")
        page.wait_for_timeout(1000)

        # 2. Type subject
        page.fill("#promptSubject", "A friendly cat wearing sunglasses")
        page.wait_for_timeout(1500)

        # 3. Select action: "Dancing"
        page.click("#actionChips .chip[data-val='dancing happily']")
        page.wait_for_timeout(1000)

        # 4. Scroll to Background section
        page.locator("#bgChips").scroll_into_view_if_needed()
        page.wait_for_timeout(500)

        # 5. Select background: "Green screen"
        page.click("#bgChips .chip[data-val='solid green screen']")
        page.wait_for_timeout(1000)

        # 6. Scroll to Style section
        page.locator("#styleChips").scroll_into_view_if_needed()
        page.wait_for_timeout(1000)

        # 7. Select style: "Pixel / Retro Game"
        page.click(".style-card[data-val='pixel art retro game 8-bit']")
        page.wait_for_timeout(1500)

        # 8. Scroll to Video Settings
        page.locator("#promptDuration").scroll_into_view_if_needed()
        page.wait_for_timeout(500)

        # 9. Set duration to 4s
        page.select_option("#promptDuration", "4 seconds")
        page.wait_for_timeout(500)

        # 10. Set camera to "Orbit"
        page.select_option("#promptCamera", "slowly orbiting")
        page.wait_for_timeout(1000)

        # 11. Scroll to Generate button
        page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
        page.wait_for_timeout(500)

        # 12. Click Generate Prompt
        page.click("#generatePromptBtn")
        page.wait_for_timeout(2000)

        # 13. Verify output
        output = page.locator("#promptOutput")
        assert el_has_class(output, "active")
        text = output.text_content()
        assert "cat" in text.lower()
        assert "dancing" in text.lower()
        assert "green screen" in text.lower()
        assert "pixel" in text.lower()
        assert "4 seconds" in text.lower()
        assert "orbiting" in text.lower()

        page.wait_for_timeout(3000)

    def test_custom_background_input(self, page, server):
        """Select Custom background → text input appears → type custom bg."""
        page.goto(server)
        page.wait_for_load_state("networkidle")
        page.wait_for_timeout(1000)

        page.click("[data-tab='prompt']")
        page.wait_for_timeout(1000)

        # Scroll to background section
        page.locator("#bgChips").scroll_into_view_if_needed()
        page.wait_for_timeout(500)

        # Custom bg input should be hidden initially
        assert not page.locator("#bgCustomRow").is_visible()

        # Click "Custom"
        page.click("#bgChips .chip[data-val='none']")
        page.wait_for_timeout(1000)

        # Custom input should appear
        assert page.locator("#bgCustomRow").is_visible()
        page.wait_for_timeout(500)

        # Type custom background
        page.fill("#promptBgCustom", "a sunset beach with palm trees")
        page.wait_for_timeout(2000)

        # Generate with subject
        page.fill("#promptSubject", "A surfing dog")
        page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
        page.wait_for_timeout(500)
        page.click("#generatePromptBtn")
        page.wait_for_timeout(2000)

        # Verify custom bg is in the prompt
        text = page.locator("#promptOutput").text_content()
        assert "sunset beach" in text.lower()
        page.wait_for_timeout(3000)

    def test_style_card_selection(self, page, server):
        """Click different style cards → verify only one is selected at a time."""
        page.goto(server)
        page.wait_for_load_state("networkidle")
        page.wait_for_timeout(1000)

        page.click("[data-tab='prompt']")
        page.wait_for_timeout(1000)

        # Scroll to style grid
        page.locator("#styleChips").scroll_into_view_if_needed()
        page.wait_for_timeout(1000)

        # Default: Cartoon is selected
        assert el_has_class(page.locator(".style-card[data-val='cartoon']"), "selected")

        # Click "Anime"
        page.click(".style-card[data-val='anime']")
        page.wait_for_timeout(1000)

        # Anime selected, Cartoon deselected
        assert el_has_class(page.locator(".style-card[data-val='anime']"), "selected")
        assert not el_has_class(page.locator(".style-card[data-val='cartoon']"), "selected")

        # Click "3D Mascot"
        page.click(".style-card[data-val='3D mascot']")
        page.wait_for_timeout(1000)

        # Only 3D Mascot selected
        assert el_has_class(page.locator(".style-card[data-val='3D mascot']"), "selected")
        assert not el_has_class(page.locator(".style-card[data-val='anime']"), "selected")
        page.wait_for_timeout(2000)

    def test_copy_prompt_to_clipboard(self, page, server):
        """Generate prompt → click Copy → toast notification appears."""
        page.goto(server)
        page.wait_for_load_state("networkidle")
        page.wait_for_timeout(1000)

        page.click("[data-tab='prompt']")
        page.wait_for_timeout(1000)

        # Fill subject and generate
        page.fill("#promptSubject", "A wizard casting spells")
        page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
        page.wait_for_timeout(500)
        page.click("#generatePromptBtn")
        page.wait_for_timeout(1500)

        # Click Copy
        page.click("#copyPromptBtn")
        page.wait_for_timeout(500)

        # Toast should appear briefly
        toast = page.locator("#copyToast")
        assert el_has_class(toast, "show")
        page.wait_for_timeout(2000)

    def test_empty_subject_shows_error(self, page, server):
        """Generate with empty subject → shows 'Please describe a subject'."""
        page.goto(server)
        page.wait_for_load_state("networkidle")
        page.wait_for_timeout(1000)

        page.click("[data-tab='prompt']")
        page.wait_for_timeout(1000)

        # Don't type anything, just click Generate
        page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
        page.wait_for_timeout(500)
        page.click("#generatePromptBtn")
        page.wait_for_timeout(1500)

        # Should show error message
        text = page.locator("#promptOutput").text_content()
        assert "please describe a subject" in text.lower()

        # Copy button should NOT appear for error
        assert not page.locator("#copyPromptBtn").is_visible()
        page.wait_for_timeout(2000)
