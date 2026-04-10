"""Accessibility tests using Pa11y.

WHAT: Runs Pa11y (a Node.js tool) against the running app to check
for WCAG 2.1 AA compliance violations.

WHY ACCESSIBILITY TESTING MATTERS:
- ~15-20% of users have some form of disability (visual, motor, cognitive)
- WCAG compliance is legally required in many jurisdictions (ADA, EAA, etc.)
- Catches INVISIBLE bugs that functional tests never find:
  * Missing form labels (screen readers can't identify inputs)
  * Insufficient color contrast (low-vision users can't read text)
  * Missing ARIA attributes (keyboard-only users can't navigate)
  * Images without alt text

HOW Pa11y WORKS:
1. Launches a headless Chrome browser
2. Loads the page and waits for rendering
3. Runs HTML_CodeSniffer against the DOM
4. Reports WCAG violations as errors, warnings, or notices

PREREQUISITES:
  npm install (installs pa11y from package.json)
"""

import json
import os
import signal
import subprocess
import sys
import time

import pytest

pytestmark = pytest.mark.a11y


@pytest.fixture(scope="module")
def server():
    """Start Flask server for accessibility auditing."""
    env = {**os.environ, "PORT": "5051"}
    proc = subprocess.Popen(
        [sys.executable, "app.py"],
        cwd=os.path.dirname(os.path.dirname(os.path.dirname(__file__))),
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    time.sleep(3)
    yield "http://localhost:5051"
    proc.send_signal(signal.SIGTERM)
    try:
        proc.wait(timeout=5)
    except subprocess.TimeoutExpired:
        proc.kill()


def run_pa11y(url, standard="WCAG2AA"):
    """Run Pa11y and return parsed JSON results.

    WHY we call Pa11y via subprocess instead of using a Python library:
    Pa11y is the gold standard for automated a11y testing. There's no
    Python equivalent with the same rule coverage. Calling it via
    subprocess keeps our test runner as pytest while leveraging the
    best tool for the job.
    """
    result = subprocess.run(
        ["npx", "pa11y", "--reporter", "json", "--standard", standard, url],
        capture_output=True,
        text=True,
        timeout=120,
        cwd=os.path.dirname(os.path.dirname(os.path.dirname(__file__))),
    )
    if result.stdout.strip():
        try:
            return json.loads(result.stdout)
        except json.JSONDecodeError:
            return []
    return []


@pytest.fixture(scope="module")
def pa11y_results(server):
    """Run Pa11y once per module and share results across tests.

    WHY: Pa11y takes 10-30s to run. Running it once and caching the
    results means we can write multiple assertions without waiting.
    """
    return run_pa11y(server)


class TestAccessibility:
    """WCAG 2.1 AA compliance checks."""

    def test_homepage_no_critical_errors(self, pa11y_results):
        """The main page should have zero WCAG 2.1 AA errors.

        WHY: Errors (not warnings) are definite violations — things
        that WILL prevent some users from using the app. Zero tolerance.

        NOTE: On first run, this will likely FAIL because the current
        HTML has known issues (missing form labels, no ARIA roles).
        That's the point — fix them one by one to learn a11y best practices.
        """
        errors = [r for r in pa11y_results if r.get("type") == "error"]

        if errors:
            messages = "\n".join(
                f"  [{e.get('code', '?')}] {e.get('message', '?')}\n"
                f"    selector: {e.get('selector', 'N/A')}\n"
                f"    context:  {e.get('context', 'N/A')[:100]}"
                for e in errors[:10]
            )
            total = len(errors)
            pytest.fail(
                f"Pa11y found {total} WCAG 2.1 AA error(s):\n\n{messages}"
                + (f"\n  ... and {total - 10} more" if total > 10 else "")
            )

    def test_warnings_below_threshold(self, pa11y_results):
        """Warnings should decrease over time. Start permissive, tighten.

        WHY: Warnings are potential issues, not definite violations.
        We don't fail on every warning immediately — instead, we set
        a threshold and ratchet it down as we fix issues.
        """
        warnings = [r for r in pa11y_results if r.get("type") == "warning"]

        threshold = 30
        if len(warnings) > threshold:
            sample = "\n".join(
                f"  - {w.get('message', '?')[:80]}"
                for w in warnings[:5]
            )
            pytest.fail(
                f"Too many a11y warnings: {len(warnings)} (threshold: {threshold})\n"
                f"Sample:\n{sample}"
            )
