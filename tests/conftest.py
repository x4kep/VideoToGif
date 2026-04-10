"""Shared test fixtures for GIF Studio.

WHY THIS FILE EXISTS:
conftest.py is pytest's mechanism for sharing fixtures across test files.
Fixtures defined here are automatically available to every test in every
subdirectory — no imports needed.

KEY DESIGN DECISIONS:
1. We generate test images programmatically (not committed as files) so tests
   are self-contained and properties (dimensions, transparency) are precise.
2. We clear the global image_jobs dict before each test to prevent state
   leaking between tests — the #1 cause of flaky test suites.
3. We auto-skip macOS-only tests on other platforms so the suite runs
   everywhere without manual marker management.
"""

import io
import os
import sys

import pytest
from PIL import Image


# ---------------------------------------------------------------------------
# Platform handling: auto-skip macOS-only tests on Linux/Windows
# ---------------------------------------------------------------------------
def pytest_collection_modifyitems(config, items):
    """Automatically skip tests marked @pytest.mark.macos_only on non-macOS."""
    if sys.platform == "darwin":
        return  # nothing to skip on macOS
    skip_mac = pytest.mark.skip(reason="Requires macOS with Vision framework")
    for item in items:
        if "macos_only" in item.keywords:
            item.add_marker(skip_mac)


# ---------------------------------------------------------------------------
# Flask app & client fixtures
# ---------------------------------------------------------------------------
@pytest.fixture
def app():
    """Provide a Flask app instance with isolated global state.

    WHY: The app uses module-level dicts (image_jobs, jobs) to track work.
    Without clearing them, test A's results leak into test B, causing
    order-dependent failures — the hardest bugs to debug.
    """
    # Import here (not at top) so the module is loaded fresh per test
    import app as app_module

    app_module.image_jobs.clear()
    app_module.app.config["TESTING"] = True
    yield app_module.app
    app_module.image_jobs.clear()


@pytest.fixture
def client(app):
    """Flask test client — sends HTTP requests without a real server.

    WHY: Flask's test client processes requests in-process, making
    integration tests fast (~milliseconds) and deterministic (no network).
    """
    return app.test_client()


# ---------------------------------------------------------------------------
# Sample image fixtures
# ---------------------------------------------------------------------------
@pytest.fixture
def sample_png_bytes():
    """100x100 RGBA PNG with a 10px transparent border around a red square.

    WHY programmatic generation instead of a fixture file:
    1. No binary blobs in git — keeps the repo clean
    2. Properties are documented by code — you can read exactly what
       the image looks like
    3. The 10px transparent border lets us assert auto-crop shrinks
       the image to 80x80
    """
    img = Image.new("RGBA", (100, 100), (0, 0, 0, 0))
    # Draw an 80x80 red square centered (from 10,10 to 90,90)
    for x in range(10, 90):
        for y in range(10, 90):
            img.putpixel((x, y), (255, 0, 0, 255))
    buf = io.BytesIO()
    img.save(buf, "PNG")
    buf.seek(0)
    return buf.getvalue()


@pytest.fixture
def sample_jpg_bytes():
    """100x100 solid blue JPEG.

    WHY: JPEGs don't support transparency. This tests that the route
    handles RGB input correctly and doesn't crash trying to access
    an alpha channel that doesn't exist.
    """
    img = Image.new("RGB", (100, 100), (0, 0, 255))
    buf = io.BytesIO()
    img.save(buf, "JPEG")
    buf.seek(0)
    return buf.getvalue()


@pytest.fixture
def sample_small_png_bytes():
    """10x10 solid green PNG — minimal image for fast tests."""
    img = Image.new("RGBA", (10, 10), (0, 255, 0, 255))
    buf = io.BytesIO()
    img.save(buf, "PNG")
    buf.seek(0)
    return buf.getvalue()
