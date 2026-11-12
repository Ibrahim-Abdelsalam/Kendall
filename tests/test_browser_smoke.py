"""Headless Browser Smoke Test Suite for Kendall (Plot Twist).

Tests using Playwright:
  1. App loads with zero console errors and no API-key or credential requests.
  2. Every variable loads (all 12 variables).
  3. Every guided investigation case file runs (Cases 1 through 4).
  4. Core controls: Pinned coordinate, Region draw, Period selection, Seasonal filter,
     Projection toggle (Flat vs Globe), and Copy-link hash restore.
  5. Ocean cell click with land-only variable shows a clear 'MASKED / NO DATA' state.
"""

import os
import sys
import time
import pytest
from playwright.sync_api import sync_playwright

BRAVE_PATH = "/Applications/Brave Browser.app/Contents/MacOS/Brave Browser"
APP_URL = "http://localhost:8000/index.html"

ALL_VARIABLES = [
    "gpm_precip",
    "gldas_precip",
    "gldas_soil_moist",
    "gldas_temp",
    "gldas_evap",
    "merra2_aod",
    "gldas_swe",
    "gldas_snow_depth",
    "merra2_ts",
    "merra2_wind",
    "merra2_ps",
    "merra2_tqv",
]


@pytest.fixture(scope="module")
def browser_context():
    """Launch headless Chromium/Brave browser."""
    if not os.path.exists(BRAVE_PATH):
        pytest.skip(f"Browser executable not found at {BRAVE_PATH}")

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


def test_app_loads_zero_errors_no_api_keys(browser_context):
    """Verify app loads cleanly with zero console errors and no external API key requests."""
    page = browser_context.new_page()
    console_errors = []
    network_requests = []

    page.on("console", lambda msg: console_errors.append(msg.text) if msg.type == "error" else None)
    page.on("pageerror", lambda exc: console_errors.append(str(exc)))
    page.on("request", lambda req: network_requests.append(req.url))

    page.goto(APP_URL)
    page.wait_for_function("() => window.plotTwist && window.plotTwist.state && window.plotTwist.state.map")
    page.wait_for_timeout(500)

    # Dismiss intro screen
    btn_start = page.query_selector("#btn-intro-start")
    if btn_start and btn_start.is_visible():
        btn_start.click()
        page.evaluate("() => { const el = document.getElementById('intro-overlay'); if (el) { el.classList.add('hidden'); el.style.display = 'none'; } }")

    # Assert zero console errors
    assert len(console_errors) == 0, f"Console errors detected: {console_errors}"

    # Assert no API keys, tokens, or credentials in any request URL
    for url in network_requests:
        lower_url = url.lower()
        assert "api_key" not in lower_url, f"API key param leaked in URL: {url}"
        assert "token=" not in lower_url, f"Auth token leaked in URL: {url}"
        assert "password" not in lower_url, f"Password leaked in URL: {url}"

    page.close()


def test_every_variable_loads(browser_context):
    """Verify every one of the 12 planetary variables loads and renders."""
    page = browser_context.new_page()
    page.goto(APP_URL)
    page.wait_for_function("() => window.plotTwist && window.plotTwist.state && window.plotTwist.state.map")
    page.evaluate("() => { const el = document.getElementById('intro-overlay'); if (el) { el.classList.add('hidden'); el.style.display = 'none'; } }")

    for var_id in ALL_VARIABLES:
        # Click variable button via data-varid
        selector = f'button.var-btn[data-varid="{var_id}"]'
        page.wait_for_selector(selector, timeout=5000)
        page.click(selector)
        page.wait_for_timeout(300)

        # Check that state updated
        active_id = page.evaluate("() => window.plotTwist.state.currentVarId")
        assert active_id == var_id, f"Expected activeVarId {var_id}, got {active_id}"

        # Check badge
        badge_text = page.inner_text("#active-var-badge")
        assert len(badge_text) > 0

    page.close()


def test_every_case_file_runs(browser_context):
    """Verify all 4 guided tour case files run with verdicts and coordinates."""
    page = browser_context.new_page()
    page.goto(APP_URL)
    page.wait_for_function("() => window.plotTwist && window.plotTwist.state && window.plotTwist.state.map")
    page.evaluate("() => { const el = document.getElementById('intro-overlay'); if (el) { el.classList.add('hidden'); el.style.display = 'none'; } }")

    # Tour through all 4 cases programmatically
    for case_idx in range(4):
        page.evaluate("(idx) => window.kendall.launchTourStep(idx)", case_idx)
        page.wait_for_timeout(600)

        pill_text = page.inner_text("#tour-step-pill")
        assert f"CASE {case_idx + 1} OF 4" in pill_text

        # Verify case title exists and non-empty
        title = page.inner_text("#tour-title")
        assert len(title) > 0

        # Verify rate and verdict updated
        rate_val = page.inner_text("#val-rate")
        assert len(rate_val) > 0

    page.close()


def test_controls_pin_draw_period_season_proj_and_share(browser_context):
    """Verify pin, region draw, period, season, projection, and URL hash restoration."""
    page = browser_context.new_page()
    page.goto(APP_URL)
    page.wait_for_function("() => window.plotTwist && window.plotTwist.state && window.plotTwist.state.map")
    page.evaluate("() => { const el = document.getElementById('intro-overlay'); if (el) { el.classList.add('hidden'); el.style.display = 'none'; } }")

    # 1. Period chip
    page.click('button.chip-btn[data-period="2014-2025"]')
    page.wait_for_timeout(400)
    period_badge = page.inner_text("#period-badge")
    assert "2014 – 2025" in period_badge or "2014" in period_badge

    # 2. Season filter
    page.click('button.chip-btn[data-season="JJA"]')
    page.wait_for_timeout(400)
    season_badge = page.inner_text("#season-badge")
    assert "JJA" in season_badge

    # 3. Projection toggle (switch to flat, then back to globe)
    page.click("#btn-proj-flat")
    page.wait_for_timeout(1100)
    assert "active" in page.get_attribute("#btn-proj-flat", "class")

    page.click("#btn-proj-globe")
    page.wait_for_timeout(1100)
    assert "active" in page.get_attribute("#btn-proj-globe", "class")

    # 4. Region Draw Mode Toggle
    page.click("#btn-draw-region")
    page.wait_for_timeout(300)
    assert not page.is_hidden("#draw-mode-banner")
    page.click("#btn-exit-draw")
    page.wait_for_timeout(300)
    assert page.is_hidden("#draw-mode-banner")

    # 5. Share link hash generation and restore
    page.click("#btn-share-link")
    page.wait_for_timeout(300)
    url_hash = page.evaluate("() => window.location.hash")
    assert len(url_hash) > 0
    assert "start=2014" in url_hash
    assert "season=JJA" in url_hash

    # Open fresh page with hash and assert restoration
    page_fresh = browser_context.new_page()
    page_fresh.goto(f"{APP_URL}{url_hash}")
    page_fresh.wait_for_function("() => window.plotTwist && window.plotTwist.state && window.plotTwist.state.map")
    page_fresh.wait_for_timeout(600)

    restored_start = page_fresh.evaluate("() => window.plotTwist.state.startYear")
    restored_season = page_fresh.evaluate("() => window.plotTwist.state.seasonFilter")
    assert restored_start == 2014
    assert restored_season == "JJA"

    page.close()
    page_fresh.close()


def test_ocean_click_land_variable_shows_masked(browser_context):
    """Clicking an ocean cell with land-only variable (GLDAS Soil Moisture) shows MASKED state."""
    page = browser_context.new_page()
    page.goto(APP_URL)
    page.wait_for_function("() => window.plotTwist && window.plotTwist.state && window.plotTwist.state.map")
    page.evaluate("() => { const el = document.getElementById('intro-overlay'); if (el) { el.classList.add('hidden'); el.style.display = 'none'; } }")

    # Switch to land-only variable (gldas_soil_moist)
    page.click('button.var-btn[data-varid="gldas_soil_moist"]')
    page.wait_for_timeout(500)

    # Select Tropical Atlantic Ocean cell: lat 0.0, lon -30.0
    page.evaluate("() => window.kendall.selectPoint(0.0, -30.0)")
    page.wait_for_timeout(800)

    rate_text = page.inner_text("#val-rate")
    status_text = page.inner_text("#verdict-status-text")
    print(f"Ocean cell with land variable - Rate text: '{rate_text}', Status: '{status_text}'")

    # Must display MASKED or clear no-data state
    assert rate_text == "MASKED" or "MASKED" in status_text or "ICE / OCEAN" in status_text
    assert "state-neutral" in page.get_attribute("#verdict-card", "class")

    page.close()


def test_analysis_counter_milestones_and_resets(browser_context):
    """Verify analysis counter pill, expanded popover, milestones (5, 10, 20), deduplication, and resets."""
    page = browser_context.new_page()
    page.goto(APP_URL)
    page.wait_for_function("() => window.kendall && window.kendall.state && window.kendall.state.map")
    page.evaluate("() => { const el = document.getElementById('intro-overlay'); if (el) { el.classList.add('hidden'); el.style.display = 'none'; } }")

    # 1. Initial State: pill shows 0 looks, popover hidden, toast hidden
    pill_text = page.inner_text("#looks-pill-text")
    assert pill_text == "0 looks", f"Expected '0 looks', got '{pill_text}'"
    assert page.is_hidden("#looks-popover")
    assert page.is_hidden("#looks-milestone-toast")

    # 2. Popover Expand on click / hover & Collapse on Esc or click away
    page.click("#looks-pill")
    page.wait_for_timeout(200)
    assert not page.is_hidden("#looks-popover")

    # Press Escape to collapse
    page.keyboard.press("Escape")
    page.wait_for_timeout(200)
    assert page.is_hidden("#looks-popover")

    # Expand again and test click away
    page.click("#looks-pill")
    page.wait_for_timeout(200)
    assert not page.is_hidden("#looks-popover")
    page.mouse.click(500, 300)
    page.wait_for_timeout(200)
    assert page.is_hidden("#looks-popover")

    # 3. Simulate analysis choices up to 5 looks
    for _ in range(5):
        page.evaluate("() => window.kendall.recordAnalysisChoice()")
    page.wait_for_timeout(300)

    # Verify pill updated to 5 looks with warning state
    assert page.inner_text("#looks-pill-text") == "5 looks"
    pill_class = page.get_attribute("#looks-pill", "class")
    assert "has-warning" in pill_class

    # Verify 5-look Toast appeared with correct wording
    assert not page.is_hidden("#looks-milestone-toast")
    toast_text = page.inner_text("#milestone-toast-text")
    assert "You have tested 5 combinations" in toast_text
    assert "up to about 23% because looks overlap and are not fully independent" in toast_text
    assert "challenge author" not in toast_text.lower()

    # Dismiss toast via close button
    page.click("#btn-close-milestone-toast")
    page.wait_for_timeout(400)
    assert page.is_hidden("#looks-milestone-toast")

    # 4. Advance to 10 looks -> 10-look toast appears (40%)
    for _ in range(5):
        page.evaluate("() => window.kendall.recordAnalysisChoice()")
    page.wait_for_timeout(300)
    assert page.inner_text("#looks-pill-text") == "10 looks"
    assert not page.is_hidden("#looks-milestone-toast")
    toast_text_10 = page.inner_text("#milestone-toast-text")
    assert "up to about 40% because looks overlap and are not fully independent" in toast_text_10
    page.click("#btn-close-milestone-toast")
    page.wait_for_timeout(400)

    # 5. Advance to 20 looks -> 20-look toast appears (64%)
    for _ in range(10):
        page.evaluate("() => window.kendall.recordAnalysisChoice()")
    page.wait_for_timeout(300)
    assert page.inner_text("#looks-pill-text") == "20 looks"
    assert not page.is_hidden("#looks-milestone-toast")
    toast_text_20 = page.inner_text("#milestone-toast-text")
    assert "up to about 64% because looks overlap and are not fully independent" in toast_text_20
    page.click("#btn-close-milestone-toast")
    page.wait_for_timeout(400)

    # 6. Manual Reset Counter in expanded popover
    page.click("#looks-pill")
    page.wait_for_timeout(200)
    assert not page.is_hidden("#looks-popover")
    page.click("#btn-reset-counter")
    page.wait_for_timeout(200)
    assert page.inner_text("#looks-pill-text") == "0 looks"

    # 7. Milestone deduplication: reaching 5 looks again must NOT re-show toast
    for _ in range(5):
        page.evaluate("() => window.kendall.recordAnalysisChoice()")
    page.wait_for_timeout(300)
    assert page.inner_text("#looks-pill-text") == "5 looks"
    assert page.is_hidden("#looks-milestone-toast"), "Milestone 5 toast re-triggered within same session!"

    # 8. Reset when Case File starts
    page.evaluate("() => window.kendall.launchTourStep(0)")
    page.wait_for_timeout(500)
    assert page.inner_text("#looks-pill-text") == "0 looks", "Counter was not reset when case file launched"

    # 9. Verify changing variable, region, period, season does NOT reset counter
    page.evaluate("() => window.kendall.recordAnalysisChoice()")
    page.evaluate("() => window.kendall.recordAnalysisChoice()")
    assert page.inner_text("#looks-pill-text") == "2 looks"

    # Change variable
    page.click('button.var-btn[data-varid="gldas_precip"]')
    page.wait_for_timeout(300)
    assert page.evaluate("() => window.kendall.state.analysisChoicesCount") >= 2

    # Change season
    page.click('button.chip-btn[data-season="DJF"]')
    page.wait_for_timeout(300)
    assert page.evaluate("() => window.kendall.state.analysisChoicesCount") >= 2

    # Change period
    page.click('button.chip-btn[data-period="2000-2013"]')
    page.wait_for_timeout(300)
    assert page.evaluate("() => window.kendall.state.analysisChoicesCount") >= 2

    # 10. Inactivity timer reset
    page.evaluate("() => window.kendall.resetAnalysisCounter()")
    page.evaluate("() => window.kendall.recordAnalysisChoice()")
    assert page.inner_text("#looks-pill-text") == "1 look"
    # Call inactivity reset handler directly to simulate 3-minute timeout
    page.evaluate("() => window.kendall.resetAnalysisCounter()")
    page.wait_for_timeout(100)
    assert page.inner_text("#looks-pill-text") == "0 looks"

    page.close()


def test_analysis_counter_mobile_layout(browser_context):
    """Verify on phone viewport (390x844) the looks pill sits off bottom sheet and panels."""
    page = browser_context.new_page()
    page.set_viewport_size({"width": 390, "height": 844})
    page.goto(APP_URL)
    page.wait_for_function("() => window.kendall && window.kendall.state && window.kendall.state.map")
    page.evaluate("() => { const el = document.getElementById('intro-overlay'); if (el) { el.classList.add('hidden'); el.style.display = 'none'; } }")
    page.wait_for_timeout(400)

    pill_box = page.locator("#looks-pill").bounding_box()
    sheet_box = page.locator("#panel-right").bounding_box()
    left_panel_box = page.locator("#panel-left").bounding_box()

    assert pill_box is not None
    assert sheet_box is not None
    assert left_panel_box is not None

    print(f"Mobile layout check: Pill: {pill_box}, Sheet: {sheet_box}, LeftPanel: {left_panel_box}")

    # The pill must be below left-panel and above the bottom sheet collapsed position
    assert pill_box["y"] >= left_panel_box["y"] + left_panel_box["height"], "Pill overlaps top variable panel!"
    assert pill_box["y"] + pill_box["height"] <= sheet_box["y"], "Pill overlaps bottom sheet!"

    page.close()

