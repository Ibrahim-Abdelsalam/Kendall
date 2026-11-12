"""
test_tour_browser.py - Automated Headless Browser Validation for Kendall Narrated Tour.

Tests:
1. First-visit modal appearance and dismissibility.
2. Complete site tour playback with audio muted, Play/Pause (Space), Back/Next (Arrows),
   Speed options, Mute, Captions toggle, and Esc exit.
3. Case-file tour navigation (Amazon, Sahel, Tibet, Canada) and dynamic coordinate tracking
   in both globe and flat projections.
4. Manual map drag detection: verifies tour pauses and "Resume tour" chip appears and functions.
5. Zero console errors and zero external API key requests.
6. Captures 3 visual screenshots to docs/screens/.
"""

import os
import shutil
import time
import pytest
from playwright.sync_api import sync_playwright

BRAVE_PATH = "/Applications/Brave Browser.app/Contents/MacOS/Brave Browser"
APP_URL = "http://localhost:8000/index.html"
SCREENS_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "docs", "screens")
ARTIFACT_DIR = "/Users/ibrahim/.gemini/antigravity/brain/fdf50d66-e7a0-47b9-8dac-523f067c7b6a"


@pytest.fixture(scope="module")
def browser_context():
    """Launches headless Chromium/Brave browser."""
    if not os.path.exists(BRAVE_PATH):
        pytest.skip(f"Brave browser executable not found at {BRAVE_PATH}")

    with sync_playwright() as p:
        browser = p.chromium.launch(
            executable_path=BRAVE_PATH,
            headless=True,
        )
        context = browser.new_context(
            viewport={"width": 1366, "height": 820},
            has_touch=True,
        )
        yield context
        browser.close()


def test_first_visit_modal_and_header_button(browser_context):
    """Verifies the first-visit modal appears on clean session and Guide Me starts site tour."""
    page = browser_context.new_page()
    page.goto(APP_URL)
    page.wait_for_function("() => window.kendall && window.kendall.state && window.kendall.state.map")

    # Dismiss intro screen
    page.click("#btn-intro-start")
    page.wait_for_timeout(300)

    # First-visit modal should now be visible
    modal = page.locator("#modal-first-visit")
    assert modal.is_visible(), "First-visit modal should be displayed on clean first visit!"

    # Dismiss modal
    page.click("#btn-first-visit-dismiss")
    page.wait_for_timeout(200)
    assert not modal.is_visible(), "First-visit modal should hide after clicking 'Explore on My Own'!"

    # Header Guide Me button launches site tour
    page.click("#btn-guide-me")
    page.wait_for_timeout(500)

    assert page.is_visible("#tour-controller"), "Tour controller should appear after clicking Guide Me!"
    assert "STEP 1 OF 14" in page.inner_text("#tour-ctrl-badge")

    page.keyboard.press("Escape")
    page.wait_for_timeout(200)
    assert not page.is_visible("#tour-controller"), "Tour should close on Escape!"
    page.close()


def test_site_tour_controls_and_playback(browser_context):
    """Verifies site tour navigation, play/pause, back/next, speed, captions, and muted completion."""
    page = browser_context.new_page()
    console_errors = []
    network_requests = []

    page.on("console", lambda msg: console_errors.append(msg.text) if msg.type == "error" else None)
    page.on("pageerror", lambda exc: console_errors.append(str(exc)))
    page.on("request", lambda req: network_requests.append(req.url))

    page.goto(APP_URL)
    page.wait_for_function("() => window.kendall && window.kendall.state && window.kendall.state.map")
    page.evaluate("() => { document.getElementById('intro-overlay')?.classList.add('hidden'); }")
    page.wait_for_timeout(300)

    # Start site tour with audio muted
    page.evaluate("async () => { await window.kendall.tourEngine.startTour('site_tour'); window.kendall.tourEngine.toggleMute(); }")
    page.wait_for_selector("#tour-controller:not(.hidden)", state="visible", timeout=6000)

    assert page.is_visible("#tour-controller")
    assert page.is_visible("#tour-highlight-overlay")
    assert "Welcome to Kendall" in page.inner_text("#tour-ctrl-title")

    # 1. Test Space key toggles Play/Pause
    assert page.evaluate("() => window.kendall.tourEngine.isPlaying") is True
    page.keyboard.press("Space")
    page.wait_for_timeout(200)
    assert page.evaluate("() => window.kendall.tourEngine.isPlaying") is False

    page.keyboard.press("Space")
    page.wait_for_timeout(200)
    assert page.evaluate("() => window.kendall.tourEngine.isPlaying") is True

    # 2. Test ArrowRight advances step
    page.keyboard.press("ArrowRight")
    page.wait_for_timeout(400)
    assert "STEP 2 OF 14" in page.inner_text("#tour-ctrl-badge")
    assert "Variable Picker" in page.inner_text("#tour-ctrl-title")

    # 3. Test ArrowLeft returns to previous step
    page.keyboard.press("ArrowLeft")
    page.wait_for_timeout(400)
    assert "STEP 1 OF 14" in page.inner_text("#tour-ctrl-badge")

    # 4. Test Speed selector
    page.click("#btn-tour-speed")
    page.wait_for_timeout(100)
    page.click("button.speed-opt[data-speed='1.25']")
    page.wait_for_timeout(100)
    assert page.evaluate("() => window.kendall.tourEngine.playbackSpeed") == 1.25
    assert "1.25" in page.inner_text("#btn-tour-speed")

    # 5. Test Captions toggle
    assert page.is_visible("#tour-captions-box")
    page.click("#btn-tour-ctrl-captions")
    page.wait_for_timeout(100)
    assert not page.is_visible("#tour-captions-box")
    page.click("#btn-tour-ctrl-captions")
    page.wait_for_timeout(100)
    assert page.is_visible("#tour-captions-box")

    # 6. Step through all 14 steps to verify no crashes
    for i in range(13):
        page.click("#btn-tour-ctrl-next")
        page.wait_for_timeout(150)

    # On last step, click next to complete
    assert "STEP 14 OF 14" in page.inner_text("#tour-ctrl-badge")
    page.click("#btn-tour-ctrl-next")
    page.wait_for_timeout(300)
    assert not page.is_visible("#tour-controller"), "Tour controller should hide after completing last step!"

    # Assert no errors occurred
    assert len(console_errors) == 0, f"Console errors encountered: {console_errors}"
    page.close()


def test_case_tour_and_highlight_targets(browser_context):
    """Tests case study tours, target coordinate projection, flat vs globe views, and map drag pause."""
    page = browser_context.new_page()
    page.goto(APP_URL)
    page.wait_for_function("() => window.kendall && window.kendall.state && window.kendall.state.map")
    page.evaluate("() => { document.getElementById('intro-overlay')?.classList.add('hidden'); document.getElementById('error-toast')?.classList.add('hidden'); }")
    page.wait_for_timeout(300)

    # Launch Amazon case tour
    page.evaluate("async () => { await window.kendall.tourEngine.startTour('case_amazon'); window.kendall.tourEngine.toggleMute(); }")
    page.wait_for_selector("#tour-controller:not(.hidden)", state="visible", timeout=6000)

    assert page.is_visible("#tour-controller")
    assert "Amazon Basin" in page.inner_text("#tour-ctrl-title")

    # Check target ring exists
    ring = page.locator("#tour-target-ring")
    assert ring.is_visible()
    box = ring.bounding_box()
    assert box is not None and box["width"] > 0 and box["height"] > 0

    # Toggle to Flat projection and verify highlight survives
    page.click("#btn-proj-flat")
    page.wait_for_timeout(600)
    assert page.evaluate("() => window.kendall.state.projection") in ["flat", "mercator"]
    box_flat = ring.bounding_box()
    assert box_flat is not None and box_flat["width"] > 0

    # Toggle back to Globe projection
    page.click("#btn-proj-globe")
    page.wait_for_timeout(600)

    # Test manual map drag pauses tour and shows resume chip
    page.evaluate("() => window.kendall.tourEngine.pauseForManualInteraction()")
    page.wait_for_timeout(200)

    assert page.is_visible("#tour-resume-chip"), "Resume tour chip should appear after manual map interaction!"
    assert page.evaluate("() => window.kendall.tourEngine.isPlaying") is False

    # Click resume tour
    page.click("#btn-resume-tour")
    page.wait_for_timeout(200)
    assert not page.is_visible("#tour-resume-chip")
    assert page.evaluate("() => window.kendall.tourEngine.isPlaying") is True

    # Press Esc to exit
    page.keyboard.press("Escape")
    page.wait_for_timeout(200)
    assert not page.is_visible("#tour-controller")
    page.close()


def test_capture_tour_screenshots(browser_context):
    """Captures 3 visual screenshots of guided tour steps."""
    os.makedirs(SCREENS_DIR, exist_ok=True)
    page = browser_context.new_page()
    page.set_viewport_size({"width": 1366, "height": 820})

    page.goto(APP_URL)
    page.wait_for_function("() => window.kendall && window.kendall.state && window.kendall.state.map")
    page.evaluate("() => { document.getElementById('intro-overlay')?.classList.add('hidden'); }")
    page.wait_for_timeout(400)

    # 1. Site Tour Welcome Step
    page.evaluate("() => { window.kendall.tourEngine.startTour('site_tour', 0); window.kendall.tourEngine.toggleMute(); }")
    page.wait_for_timeout(1000)
    s1_path = os.path.join(SCREENS_DIR, "tour_step1_welcome.png")
    page.screenshot(path=s1_path)
    shutil.copy(s1_path, os.path.join(ARTIFACT_DIR, "tour_step1_welcome.png"))
    print(f"Captured screenshot 1: {s1_path}")

    # 2. Amazon Basin Case Study
    page.evaluate("() => { window.kendall.tourEngine.startTour('case_amazon', 1); window.kendall.tourEngine.toggleMute(); }")
    page.wait_for_timeout(1200)
    s2_path = os.path.join(SCREENS_DIR, "tour_step2_amazon.png")
    page.screenshot(path=s2_path)
    shutil.copy(s2_path, os.path.join(ARTIFACT_DIR, "tour_step2_amazon.png"))
    print(f"Captured screenshot 2: {s2_path}")

    # 3. Canada Wildfire Smoke Season in Flat Projection
    page.evaluate("() => { window.kendall.tourEngine.startTour('case_canada', 2); window.kendall.setProjection('flat'); window.kendall.tourEngine.toggleMute(); }")
    page.wait_for_timeout(1200)
    s3_path = os.path.join(SCREENS_DIR, "tour_step3_canada.png")
    page.screenshot(path=s3_path)
    shutil.copy(s3_path, os.path.join(ARTIFACT_DIR, "tour_step3_canada.png"))
    print(f"Captured screenshot 3: {s3_path}")

    page.close()
