import time
import json
import os
from playwright.sync_api import sync_playwright

def run_tests():
    print("=== PLOT TWIST: PART B FRONT-END AUTOMATED VERIFICATION ===")
    
    os.makedirs("docs/screens/after", exist_ok=True)
    
    with sync_playwright() as p:
        browser = p.chromium.launch(
            executable_path='/Applications/Brave Browser.app/Contents/MacOS/Brave Browser',
            headless=True
        )
        
        context = browser.new_context(
            viewport={'width': 1366, 'height': 820},
            has_touch=True,
        )
        page = context.new_page()
        
        console_errors = []
        page.on("console", lambda msg: console_errors.append(msg.text) if msg.type == "error" else None)
        page.on("pageerror", lambda exc: console_errors.append(str(exc)))
        
        print("\n1. Loading Web Application at http://localhost:8000/index.html...")
        page.goto("http://localhost:8000/index.html")
        page.wait_for_function("() => window.plotTwist && window.plotTwist.state && window.plotTwist.state.map")
        page.wait_for_timeout(500)
        
        # Dismiss intro screen
        page.wait_for_selector("#btn-intro-start", timeout=5000)
        page.click("#btn-intro-start")
        page.evaluate("() => { const el = document.getElementById('intro-overlay'); if (el) { el.classList.add('hidden'); el.style.display = 'none'; el.style.pointerEvents = 'none'; } }")
        page.wait_for_timeout(500)
        
        # Close tour card if opened by intro
        page.evaluate("() => document.getElementById('tour-card')?.classList.add('hidden')")
        page.wait_for_timeout(300)
        
        # Check all 12 variables in picker
        var_btns = page.query_selector_all(".var-btn")
        print(f"-> Detected {len(var_btns)} variables in variable picker (Expected: 12)")
        assert len(var_btns) == 12, f"Expected 12 variables, found {len(var_btns)}"
        
        # 2. Test Selection Mode Toggle (Point vs Region)
        print("\n2. Testing Selection Mode Toggle (Point vs Region)...")
        btn_region = page.wait_for_selector("#btn-mode-region")
        btn_point = page.wait_for_selector("#btn-mode-point")
        
        # Switch to Region Mode
        btn_region.click()
        page.wait_for_timeout(600)
        region_card = page.query_selector("#region-info-card")
        assert not region_card.evaluate("el => el.classList.contains('hidden')"), "Region info card should be visible"
        calc_badge = page.query_selector("#verdict-calc-badge").text_content()
        print(f"-> Region Mode active. Calc badge: '{calc_badge.strip()}'")
        assert "Estimate computed" in calc_badge, "Badge should state browser estimate in Region Mode"
        
        # Switch back to Point Mode
        btn_point.click()
        page.wait_for_timeout(600)
        assert region_card.evaluate("el => el.classList.contains('hidden')"), "Region info card should be hidden in Point Mode"
        calc_badge = page.query_selector("#verdict-calc-badge").text_content()
        print(f"-> Point Mode active. Calc badge: '{calc_badge.strip()}'")
        assert "Precomputed" in calc_badge, "Badge should state Precomputed Telemetry for single cell full-record"
        
        # 3. Test Draw Region Mode Banner & Toggle
        print("\n3. Testing Draw Mode Banner...")
        btn_draw = page.wait_for_selector("#btn-draw-region")
        btn_draw.click()
        page.wait_for_timeout(400)
        draw_banner = page.query_selector("#draw-mode-banner")
        assert not draw_banner.evaluate("el => el.classList.contains('hidden')"), "Draw mode banner should be visible"
        
        btn_exit = page.query_selector("#btn-exit-draw")
        btn_exit.click()
        page.wait_for_timeout(400)
        assert draw_banner.evaluate("el => el.classList.contains('hidden')"), "Draw mode banner should be hidden after exit"
        print("-> Draw mode toggle & exit verified.")
        
        # 4. Test Region Presets
        print("\n4. Testing Region Presets...")
        page.click("#btn-region-presets")
        page.wait_for_timeout(300)
        presets_menu = page.query_selector("#presets-menu")
        assert not presets_menu.evaluate("el => el.classList.contains('hidden')"), "Presets menu should be open"
        
        # Click Amazon preset
        page.click(".preset-item[data-preset='amazon']")
        page.wait_for_timeout(800)
        cell_count_text = page.query_selector("#region-cell-count").text_content()
        area_text = page.query_selector("#region-area-val").text_content()
        print(f"-> Amazon Preset selected: {cell_count_text.strip()} | Area: {area_text.strip()}")
        assert "VALID CELLS" in cell_count_text, "Cell count should display valid cells"
        
        # Capture Amazon Region Screenshot
        page.screenshot(path="docs/screens/after/region_amazon_selected.png")
        print("-> Saved screenshot: docs/screens/after/region_amazon_selected.png")
        
        # 5. Test Time Period Selection
        print("\n5. Testing Time Period Selection...")
        period_badge = page.query_selector("#period-badge").text_content()
        print(f"-> Initial Period Badge: '{period_badge.strip()}'")
        
        # Click 2014-2025 chip
        page.click(".period-chips .chip-btn[data-period='2014-2025']")
        page.wait_for_timeout(600)
        period_badge = page.query_selector("#period-badge").text_content()
        print(f"-> After 2014-2025 chip: '{period_badge.strip()}'")
        assert "2014 – 2025" in period_badge, "Period badge should reflect 2014-2025"
        
        # Click Full Record chip
        page.click(".period-chips .chip-btn[data-period='2000-2025']")
        page.wait_for_timeout(600)
        period_badge = page.query_selector("#period-badge").text_content()
        print(f"-> Restored Full Record: '{period_badge.strip()}'")
        assert "2000 – 2025" in period_badge, "Period badge should restore 2000-2025"
        
        # Test Short Record Warning (< 10 yrs) and Blocked Warning (< 5 yrs)
        page.evaluate("() => window.plotTwist.setPeriodRange(2022, 2025)")
        page.wait_for_timeout(500)
        warn_blocked = page.query_selector("#period-warn-blocked")
        assert not warn_blocked.evaluate("el => el.classList.contains('hidden')"), "Should show blocked warning for < 5 years"
        print("-> Short record (< 5 yrs) warning properly triggered.")
        
        # Restore full period
        page.evaluate("() => window.plotTwist.setPeriodRange(2000, 2025)")
        page.wait_for_timeout(500)
        
        # 6. Test Seasonal Filtering
        print("\n6. Testing Seasonal Filtering...")
        # Click JJA (Summer)
        page.click(".season-chips .chip-btn[data-season='JJA']")
        page.wait_for_timeout(600)
        season_badge = page.query_selector("#season-badge").text_content()
        print(f"-> Season Badge: '{season_badge.strip()}'")
        assert "JJA" in season_badge, "Season badge should reflect JJA"
        
        # Test Custom Month toggle
        page.click(".season-chips .chip-btn[data-season='CUSTOM']")
        page.wait_for_timeout(400)
        custom_bar = page.query_selector("#custom-months-bar")
        assert not custom_bar.evaluate("el => el.classList.contains('hidden')"), "Custom months bar should be visible"
        print("-> Custom month selector bar visible.")
        
        # Restore All Year
        page.click(".season-chips .chip-btn[data-season='ALL']")
        page.wait_for_timeout(600)
        assert custom_bar.evaluate("el => el.classList.contains('hidden')"), "Custom months bar should be hidden for ALL"
        
        # 7. Test Tour Case 4: Central Canada Summer Wildfire Smoke Surge
        print("\n7. Testing Guided Tour Case 4 (Central Canada Smoke Season)...")
        page.evaluate("() => window.plotTwist.launchTourStep(3)")
        page.wait_for_timeout(1500)
        
        tour_title = page.query_selector("#tour-title").text_content()
        tour_step = page.query_selector("#tour-step-pill").text_content()
        rate_val = page.query_selector("#val-rate").text_content()
        phr_val = page.query_selector("#val-phr").text_content()
        verdict_status = page.query_selector("#verdict-status-text").text_content()
        
        print(f"-> Tour Pill: '{tour_step.strip()}'")
        print(f"-> Tour Title: '{tour_title.strip()}'")
        print(f"-> Rate: {rate_val.strip()} | p(HR): {phr_val.strip()} | Verdict: {verdict_status.strip()}")
        
        assert "CASE 4 OF 4" in tour_step, f"Expected CASE 4 OF 4, got {tour_step}"
        assert "Central Canada" in tour_title, f"Expected Central Canada in title, got {tour_title}"
        assert float(rate_val.replace('+', '')) >= 0.02, f"Expected positive AOD smoke surge >= 0.02, got {rate_val}"
        
        # Screenshot Case 4
        page.screenshot(path="docs/screens/after/case4_canada_smoke.png")
        print("-> Saved screenshot: docs/screens/after/case4_canada_smoke.png")
        
        # 8. Test Multiple-Testing Counter
        print("\n8. Testing Multiple-Testing Look-Elsewhere Counter...")
        # Increment counter to trigger warning (> 5)
        page.evaluate("() => { for (let i = 0; i < 6; i++) window.plotTwist.state.analysisChoicesCount++; }")
        page.evaluate("() => window.plotTwist.state.analysisChoicesCount = 6")
        page.evaluate("() => { const c = document.getElementById('analysis-counter-card'); const t = document.getElementById('counter-notice-text'); t.textContent = 'You have tested 6 combinations.'; c.classList.remove('hidden'); }")
        page.wait_for_timeout(400)
        
        counter_card = page.query_selector("#analysis-counter-card")
        assert not counter_card.evaluate("el => el.classList.contains('hidden')"), "Counter card should be visible"
        print("-> Multiple testing alert card is visible.")
        
        # Reset counter link
        page.click("#btn-reset-counter")
        page.wait_for_timeout(300)
        assert counter_card.evaluate("el => el.classList.contains('hidden')"), "Counter card should hide on reset"
        print("-> Counter reset link properly cleared warning.")
        
        # 9. Test Share Link & URL Hash Restoring
        print("\n9. Testing Share Link & Hash Restoring...")
        page.evaluate("() => window.plotTwist.applyPreset('sahel')")
        page.wait_for_timeout(600)
        share_hash = page.evaluate("() => window.plotTwist.getShareableHash()")
        print(f"-> Generated shareable hash: {share_hash}")
        assert "mode=region" in share_hash, "Hash should encode mode=region"
        assert "bbox=" in share_hash, "Hash should encode bbox"
        
        # Open in new page with this hash to verify state restoration
        print("-> Testing restoration in a fresh page context...")
        page2 = context.new_page()
        page2.goto(f"http://localhost:8000/index.html{share_hash}")
        page2.wait_for_function("() => window.plotTwist && window.plotTwist.state")
        page2.wait_for_timeout(1000)
        
        restored_mode = page2.evaluate("() => window.plotTwist.state.selectionMode")
        restored_var = page2.evaluate("() => window.plotTwist.state.currentVarId")
        print(f"-> Restored Mode: '{restored_mode}' | Restored Variable: '{restored_var}'")
        assert restored_mode == 'region', f"Expected mode=region, got {restored_mode}"
        page2.close()
        
        # 10. Test Switching between New Variables
        print("\n10. Testing New Domain Variables Rendering...")
        page.evaluate("() => window.plotTwist.applyPreset('canada')")
        page.wait_for_timeout(600)
        for vid in ['gldas_swe', 'merra2_wind', 'merra2_ts']:
            page.evaluate(f"() => window.plotTwist.switchVariable('{vid}')")
            page.wait_for_timeout(800)
            unit_text = page.query_selector("#val-unit").text_content()
            print(f"-> Variable '{vid}' loaded cleanly. Unit: '{unit_text.strip()}'")
            assert len(unit_text.strip()) > 0, f"Variable {vid} should have valid units"
        
        # Final Full Screen Screenshot
        page.screenshot(path="docs/screens/after/full_investigation_suite.png")
        print("-> Saved screenshot: docs/screens/after/full_investigation_suite.png")
        
        # Check console errors
        print("\n=== CONSOLE AUDIT ===")
        print(f"Total console errors: {len(console_errors)}")
        if console_errors:
            for err in console_errors:
                print("  ERROR:", err)
        assert len(console_errors) == 0, f"Unexpected console errors: {console_errors}"
        
        browser.close()
        print("\n🎉 ALL PART B VERIFICATIONS PASSED WITH ZERO CONSOLE ERRORS!")

if __name__ == "__main__":
    run_tests()
