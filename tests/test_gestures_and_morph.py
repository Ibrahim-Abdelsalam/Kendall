import time
import math
from playwright.sync_api import sync_playwright

def run_tests():
    print("=== PLOT TWIST: TOUCH GESTURES & MORPH VERIFICATION ===")
    
    with sync_playwright() as p:
        browser = p.chromium.launch(
            executable_path='/Applications/Brave Browser.app/Contents/MacOS/Brave Browser',
            headless=True
        )
        
        # Enable touch support on browser context
        context = browser.new_context(
            viewport={'width': 1280, 'height': 800},
            has_touch=True,
            is_mobile=True,
        )
        page = context.new_page()
        
        console_errors = []
        page.on("console", lambda msg: console_errors.append(msg.text) if msg.type == "error" else None)
        page.on("pageerror", lambda exc: console_errors.append(str(exc)))
        page.on("response", lambda resp: print("Failed HTTP response:", resp.status, resp.url) if resp.status >= 400 else None)
        
        print("\n1. Loading Web Application...")
        page.goto("http://localhost:8000/index.html")
        page.wait_for_selector("#map")
        page.wait_for_function("() => window.appState && window.appState.map", timeout=15000)
        page.wait_for_timeout(500)
        
        # Dismiss intro overlay so map controls are accessible
        page.click("#btn-intro-start")
        page.evaluate("""() => {
            const intro = document.getElementById('intro-overlay');
            if (intro) {
                intro.classList.add('hidden');
                intro.style.display = 'none';
                intro.style.pointerEvents = 'none';
            }
            if (window.appState) window.appState.isSpinningIntro = false;
        }""")
        page.wait_for_timeout(500)
        
        # Check initial state
        state_info = page.evaluate("""() => {
            const m = window.appState ? window.appState.map : null;
            return {
                ready: !!m,
                proj: window.appState ? window.appState.projection : null,
                zoom: m ? m.getZoom() : null,
                pitch: m ? m.getPitch() : null,
                bearing: m ? m.getBearing() : null,
                touchPitchEnabled: m ? m.touchPitch.isEnabled() : null,
                touchZoomRotateEnabled: m ? m.touchZoomRotate.isEnabled() : null,
            };
        }""")
        print("Initial Map State:", state_info)
        assert state_info["ready"], "Map failed to initialize!"
        assert state_info["touchPitchEnabled"] is False, "touchPitch should be disabled!"
        assert state_info["touchZoomRotateEnabled"] is True, "touchZoomRotate should be enabled!"
        
        # Test 1: 3D Tilt button
        print("\n2. Testing 3D Tilt Button (0° <-> 45°)...")
        tilt_btn = page.locator("#btn-toggle-tilt")
        assert tilt_btn.is_visible()
        
        initial_pitch = page.evaluate("window.appState.map.getPitch()")
        print(f"Initial pitch: {initial_pitch:.1f}°")
        
        # Click tilt button
        tilt_btn.click()
        page.wait_for_timeout(700)
        pitch_after = page.evaluate("window.appState.map.getPitch()")
        label_after = page.locator("#tilt-label").text_content()
        print(f"Pitch after clicking 3D button: {pitch_after:.1f}°, Badge: '{label_after}'")
        assert pitch_after > 40, f"Expected pitch ~45°, got {pitch_after}"
        assert label_after == "3D", f"Expected badge '3D', got {label_after}"
        
        # Click again to reset to 0
        tilt_btn.click()
        page.wait_for_timeout(700)
        pitch_reset = page.evaluate("window.appState.map.getPitch()")
        label_reset = page.locator("#tilt-label").text_content()
        print(f"Pitch after reset: {pitch_reset:.1f}°, Badge: '{label_reset}'")
        assert pitch_reset < 2, f"Expected pitch ~0°, got {pitch_reset}"
        assert label_reset == "2D", f"Expected badge '2D', got {label_reset}"
        
        # Test 2: Pinch to zoom in (moving apart) & Midpoint anchor
        print("\n3. Testing Pinch-to-Zoom Gestures via CDP Touch Synthesis...")
        cdp = context.new_cdp_session(page)
        
        # Center of viewport
        cx, cy = 640, 400
        
        # Get LngLat at center midpoint before pinch
        pt_before = page.evaluate(f"window.appState.map.unproject([{cx}, {cy}])")
        zoom_before = page.evaluate("window.appState.map.getZoom()")
        print(f"Before pinch-out (apart): Zoom = {zoom_before:.3f}, Midpoint = [{pt_before['lng']:.4f}, {pt_before['lat']:.4f}]")
        
        # Synthesize pinch: two fingers moving APART (zooming in)
        # Touch 0: (cx - 40, cy) -> (cx - 120, cy)
        # Touch 1: (cx + 40, cy) -> (cx + 120, cy)
        # Midpoint stays at (cx, cy)
        cdp.send("Input.dispatchTouchEvent", {
            "type": "touchStart",
            "touchPoints": [
                {"x": cx - 40, "y": cy, "id": 0},
                {"x": cx + 40, "y": cy, "id": 1}
            ]
        })
        time.sleep(0.05)
        
        steps = 10
        for i in range(1, steps + 1):
            offset = 40 + (80 * i / steps)
            cdp.send("Input.dispatchTouchEvent", {
                "type": "touchMove",
                "touchPoints": [
                    {"x": cx - offset, "y": cy, "id": 0},
                    {"x": cx + offset, "y": cy, "id": 1}
                ]
            })
            time.sleep(0.02)
            
        cdp.send("Input.dispatchTouchEvent", {
            "type": "touchEnd",
            "touchPoints": []
        })
        page.wait_for_timeout(300)
        
        zoom_after_pinch_in = page.evaluate("window.appState.map.getZoom()")
        pt_after_pinch_in = page.evaluate(f"window.appState.map.unproject([{cx}, {cy}])")
        zoom_delta = zoom_after_pinch_in - zoom_before
        print(f"After pinch-out (apart): Zoom = {zoom_after_pinch_in:.3f} (delta = +{zoom_delta:.3f})")
        print(f"Midpoint after: [{pt_after_pinch_in['lng']:.4f}, {pt_after_pinch_in['lat']:.4f}]")
        
        assert zoom_delta > 0.4, f"Pinch apart should have zoomed in! Got delta {zoom_delta}"
        
        # Check midpoint anchor drift: project pt_before to current screen coordinates
        screen_pt = page.evaluate(f"""() => {{
            const p = window.appState.map.project([{pt_before['lng']}, {pt_before['lat']}]);
            return {{ x: p.x, y: p.y }};
        }}""")
        drift_px = math.hypot(screen_pt['x'] - cx, screen_pt['y'] - cy)
        print(f"Midpoint anchor pixel drift: {drift_px:.2f} px")
        assert drift_px < 4.0, f"Drift too large: {drift_px}px! Zoom was not anchored at pinch midpoint."
        
        # Test 3: Pinch together (zooming out)
        print("\n4. Testing Pinch-together (Zoom Out)...")
        zoom_before_out = page.evaluate("window.appState.map.getZoom()")
        cdp.send("Input.dispatchTouchEvent", {
            "type": "touchStart",
            "touchPoints": [
                {"x": cx - 120, "y": cy, "id": 0},
                {"x": cx + 120, "y": cy, "id": 1}
            ]
        })
        time.sleep(0.05)
        for i in range(1, steps + 1):
            offset = 120 - (70 * i / steps)
            cdp.send("Input.dispatchTouchEvent", {
                "type": "touchMove",
                "touchPoints": [
                    {"x": cx - offset, "y": cy, "id": 0},
                    {"x": cx + offset, "y": cy, "id": 1}
                ]
            })
            time.sleep(0.02)
        cdp.send("Input.dispatchTouchEvent", {
            "type": "touchEnd",
            "touchPoints": []
        })
        page.wait_for_timeout(300)
        
        zoom_after_out = page.evaluate("window.appState.map.getZoom()")
        print(f"Zoom after pinch together: {zoom_after_out:.3f} (delta = {zoom_after_out - zoom_before_out:.3f})")
        assert zoom_after_out < zoom_before_out, "Pinch together should zoom out!"
        
        # Test 4: Pin safety during touch gestures
        print("\n5. Testing Pin Safety (Pinch/Pan must NEVER drop a pin)...")
        pin_before = page.evaluate("window.appState.currentPin")
        print("Pin coords before gesture:", pin_before)
        
        # Pan gesture with 1 finger moving 100px
        cdp.send("Input.dispatchTouchEvent", {
            "type": "touchStart",
            "touchPoints": [{"x": cx, "y": cy, "id": 0}]
        })
        time.sleep(0.05)
        for i in range(1, 10):
            cdp.send("Input.dispatchTouchEvent", {
                "type": "touchMove",
                "touchPoints": [{"x": cx + i * 15, "y": cy + i * 10, "id": 0}]
            })
            time.sleep(0.02)
        cdp.send("Input.dispatchTouchEvent", {
            "type": "touchEnd",
            "touchPoints": []
        })
        page.wait_for_timeout(400)
        
        pin_after_pan = page.evaluate("window.appState.currentPin")
        print("Pin coords after pan:", pin_after_pan)
        assert pin_after_pan == pin_before, "Pan gesture accidentally dropped a pin!"
        
        # Stationary single tap (< 6px, < 400ms) SHOULD drop a pin
        print("\n6. Testing Clean Stationary Single Tap (SHOULD drop pin)...")
        tap_x, tap_y = 500, 350
        tap_target_ll = page.evaluate(f"window.appState.map.unproject([{tap_x}, {tap_y}])")
        
        cdp.send("Input.dispatchTouchEvent", {
            "type": "touchStart",
            "touchPoints": [{"x": tap_x, "y": tap_y, "id": 0}]
        })
        time.sleep(0.08) # 80ms tap duration
        cdp.send("Input.dispatchTouchEvent", {
            "type": "touchEnd",
            "touchPoints": []
        })
        page.mouse.click(tap_x, tap_y)
        page.wait_for_timeout(700)
        
        pin_after_tap = page.evaluate("window.appState.currentPin")
        print("Pin coords after clean tap:", pin_after_tap)
        assert pin_after_tap != pin_before, "Stationary tap failed to drop pin!"
        
        # Test 5: 900ms Projection Morph Animation
        print("\n7. Testing 900ms Projection Morph Animation...")
        
        # Set to flat first
        page.evaluate("window.plotTwist.setProjection('flat', false)")
        page.wait_for_timeout(500)
        assert page.evaluate("window.appState.projection") == "mercator"
        
        # Verify 0% Flat state screenshot
        page.screenshot(path="docs/screens/morph_to_globe_0pct.png")
        print("Captured docs/screens/morph_to_globe_0pct.png")
        
        # Start animated morph to Globe
        page.evaluate("window.plotTwist.setProjection('globe', true)")
        
        # Immediately check isMorphing and pointer-events
        is_morphing_start = page.evaluate("window.appState.isMorphing")
        has_morphing_class = page.evaluate("document.getElementById('map-container').classList.contains('is-morphing')")
        print(f"At t=0ms: isMorphing={is_morphing_start}, class='is-morphing'={has_morphing_class}")
        assert is_morphing_start is True, "isMorphing flag should be true during morph!"
        assert has_morphing_class is True, "map-container should have 'is-morphing' class to block pointer events!"
        
        # Capture ~50% (~450ms)
        page.wait_for_timeout(450)
        is_morphing_mid = page.evaluate("window.appState.isMorphing")
        proj_mid = page.evaluate("window.appState.projection")
        has_halo = page.evaluate("!!document.getElementById('globe-halo-glow')")
        print(f"At t=450ms (~50%): isMorphing={is_morphing_mid}, proj={proj_mid}, hasStaticHalo={has_halo}")
        assert is_morphing_mid is True
        assert has_halo is False, "Static halo overlay must NOT exist (no blue circle in center)!"
        page.screenshot(path="docs/screens/morph_to_globe_50pct.png")
        print("Captured docs/screens/morph_to_globe_50pct.png")
        
        # Wait for 100% completion (~950ms)
        page.wait_for_timeout(550)
        is_morphing_end = page.evaluate("window.appState.isMorphing")
        has_morphing_class_end = page.evaluate("document.getElementById('map-container').classList.contains('is-morphing')")
        print(f"At t=1000ms (~100%): isMorphing={is_morphing_end}, class='is-morphing'={has_morphing_class_end}")
        assert is_morphing_end is False, "isMorphing should reset to false after 900ms!"
        assert has_morphing_class_end is False, "is-morphing class should be removed!"
        page.screenshot(path="docs/screens/morph_to_globe_100pct.png")
        print("Captured docs/screens/morph_to_globe_100pct.png")
        
        # Test reverse morph: Globe -> Flat
        print("\n8. Testing Reverse Morph (Globe -> Flat)...")
        page.evaluate("window.plotTwist.setProjection('flat', true)")
        page.wait_for_timeout(450)
        page.screenshot(path="docs/screens/morph_to_flat_50pct.png")
        print("Captured docs/screens/morph_to_flat_50pct.png")
        page.wait_for_timeout(550)
        assert page.evaluate("window.appState.projection") == "mercator"
        assert page.evaluate("window.appState.isMorphing") is False
        
        # Test 6: Verify all 3 Case Files
        print("\n9. Testing All 3 Guided Tour Case Files...")
        for case_idx, case_name in enumerate(["Amazon", "Sahel", "Tibet"]):
            page.evaluate(f"window.plotTwist.launchTourStep({case_idx})")
            page.wait_for_timeout(1000)
            step_text = page.locator("#tour-step-pill").text_content()
            title_text = page.locator("#tour-title").text_content()
            verdict_text = page.locator("#verdict-status-text").text_content()
            print(f"Case {case_idx + 1} ({case_name}): Pill='{step_text}', Title='{title_text}', Status='{verdict_text}'")
            assert f"CASE {case_idx + 1}" in step_text
        
        # Test 7: Check console errors
        print("\n10. Checking Console & Network Cleanliness...")
        filtered_errors = [e for e in console_errors if "favicon" not in e.lower()]
        print("Console errors count:", len(filtered_errors))
        if filtered_errors:
            print("Errors detected:", filtered_errors)
        assert len(filtered_errors) == 0, f"Found console errors: {filtered_errors}"
        
        print("\n ALL TESTS PASSED SUCCESSFULLY!")
        browser.close()

if __name__ == '__main__':
    run_tests()
