import math
import time
from playwright.sync_api import sync_playwright

def test_rotation():
    print("=" * 65)
    print("=== PLOT TWIST: TWO-FINGER TWIST ROTATION TEST ===")
    print("=" * 65)
    
    with sync_playwright() as p:
        browser = p.chromium.launch(
            executable_path='/Applications/Brave Browser.app/Contents/MacOS/Brave Browser',
            headless=True
        )
        context = browser.new_context(viewport={'width': 1280, 'height': 800}, has_touch=True)
        page = context.new_page()
        page.goto('http://localhost:8000/index.html')
        page.wait_for_timeout(2000)
        
        # Dismiss intro overlay and stop intro spin
        page.evaluate('''() => {
            const intro = document.getElementById('intro-overlay');
            if (intro) intro.classList.add('hidden');
            if (window.appState) {
                window.appState.isSpinningIntro = false;
                window.appState.map.setBearing(0);
                window.appState.map.setPitch(0);
            }
        }''')
        page.wait_for_timeout(500)
        
        cdp = context.new_cdp_session(page)
        cx, cy = 640, 400
        r = 100
        
        results = {}
        
        # Helper: reset view
        def reset_view(projection_mode='globe'):
            page.evaluate(f'''() => {{
                window.plotTwist.setProjection('{projection_mode}', false);
                window.appState.map.setBearing(0);
                window.appState.map.setPitch(0);
                window.appState.map.setZoom(2.0);
            }}''')
            page.wait_for_timeout(300)
            
        for proj in ['globe', 'flat']:
            print(f"\n--- TESTING PROJECTION: {proj.upper()} ---")
            reset_view(proj)
            
            # TEST 1: Clockwise 30 degrees
            # Fingers start horizontal: Touch 0 at left (cx - r, cy), Touch 1 at right (cx + r, cy)
            geo_mid = page.evaluate(f"window.appState.map.unproject([{cx}, {cy}])")
            bearing_start = page.evaluate("window.appState.map.getBearing()")
            
            cdp.send('Input.dispatchTouchEvent', {
                'type': 'touchStart',
                'touchPoints': [
                    {'x': cx - r, 'y': cy, 'id': 0},
                    {'x': cx + r, 'y': cy, 'id': 1}
                ]
            })
            time.sleep(0.05)
            
            steps = 15
            for s in range(1, steps + 1):
                cur_rad = math.radians(30 * s / steps)
                cur_dx = r * math.cos(cur_rad)
                cur_dy = r * math.sin(cur_rad)
                cdp.send('Input.dispatchTouchEvent', {
                    'type': 'touchMove',
                    'touchPoints': [
                        {'x': cx - cur_dx, 'y': cy - cur_dy, 'id': 0},
                        {'x': cx + cur_dx, 'y': cy + cur_dy, 'id': 1}
                    ]
                })
                time.sleep(0.015)
                
            time.sleep(0.08)
            cdp.send('Input.dispatchTouchEvent', {'type': 'touchEnd', 'touchPoints': []})
            page.wait_for_timeout(200)
            
            bearing_end_cw = page.evaluate("window.appState.map.getBearing()")
            delta_bearing_cw = bearing_end_cw - bearing_start
            
            # Midpoint drift
            cur_mid_pos = page.evaluate(f"window.appState.map.project([{geo_mid['lng']}, {geo_mid['lat']}])")
            drift_mid_cw = math.hypot(cur_mid_pos['x'] - cx, cur_mid_pos['y'] - cy)
            
            print(f"1. Clockwise 30° Rotation ({proj}):")
            print(f"   Start Bearing: {bearing_start:.4f}°")
            print(f"   End Bearing:   {bearing_end_cw:.4f}°")
            print(f"   Delta Bearing: {delta_bearing_cw:.4f}° (expected ~ -30.0000°)")
            print(f"   Midpoint Pixel Drift: {drift_mid_cw:.6f} px")
            assert -30.5 <= delta_bearing_cw <= -29.5, f"Expected bearing to decrease by 30°, got {delta_bearing_cw}"
            assert drift_mid_cw < 1.0, f"Midpoint drift too high: {drift_mid_cw} px"
            
            # TEST 2: Counterclockwise 30 degrees
            reset_view(proj)
            geo_mid = page.evaluate(f"window.appState.map.unproject([{cx}, {cy}])")
            bearing_start = page.evaluate("window.appState.map.getBearing()")
            
            cdp.send('Input.dispatchTouchEvent', {
                'type': 'touchStart',
                'touchPoints': [
                    {'x': cx - r, 'y': cy, 'id': 0},
                    {'x': cx + r, 'y': cy, 'id': 1}
                ]
            })
            time.sleep(0.05)
            
            for s in range(1, steps + 1):
                cur_rad = math.radians(-30 * s / steps)
                cur_dx = r * math.cos(cur_rad)
                cur_dy = r * math.sin(cur_rad)
                cdp.send('Input.dispatchTouchEvent', {
                    'type': 'touchMove',
                    'touchPoints': [
                        {'x': cx - cur_dx, 'y': cy - cur_dy, 'id': 0},
                        {'x': cx + cur_dx, 'y': cy + cur_dy, 'id': 1}
                    ]
                })
                time.sleep(0.015)
                
            time.sleep(0.08)
            cdp.send('Input.dispatchTouchEvent', {'type': 'touchEnd', 'touchPoints': []})
            page.wait_for_timeout(200)
            
            bearing_end_ccw = page.evaluate("window.appState.map.getBearing()")
            delta_bearing_ccw = bearing_end_ccw - bearing_start
            
            cur_mid_pos = page.evaluate(f"window.appState.map.project([{geo_mid['lng']}, {geo_mid['lat']}])")
            drift_mid_ccw = math.hypot(cur_mid_pos['x'] - cx, cur_mid_pos['y'] - cy)
            
            print(f"2. Counterclockwise 30° Rotation ({proj}):")
            print(f"   Start Bearing: {bearing_start:.4f}°")
            print(f"   End Bearing:   {bearing_end_ccw:.4f}°")
            print(f"   Delta Bearing: {delta_bearing_ccw:.4f}° (expected ~ +30.0000°)")
            print(f"   Midpoint Pixel Drift: {drift_mid_ccw:.6f} px")
            assert 29.5 <= delta_bearing_ccw <= 30.5, f"Expected bearing to increase by 30°, got {delta_bearing_ccw}"
            assert drift_mid_ccw < 1.0, f"Midpoint drift too high: {drift_mid_ccw} px"
            
            # TEST 3: Simultaneous Zoom + Clockwise Rotation (Apart + Twist)
            reset_view(proj)
            geo_mid = page.evaluate(f"window.appState.map.unproject([{cx}, {cy}])")
            bearing_start = page.evaluate("window.appState.map.getBearing()")
            zoom_start = page.evaluate("window.appState.map.getZoom()")
            
            cdp.send('Input.dispatchTouchEvent', {
                'type': 'touchStart',
                'touchPoints': [
                    {'x': cx - r, 'y': cy, 'id': 0},
                    {'x': cx + r, 'y': cy, 'id': 1}
                ]
            })
            time.sleep(0.05)
            
            # Simultaneously rotate 30° CW and expand radius from 100 to 160 (scale = 1.6)
            for s in range(1, steps + 1):
                cur_rad = math.radians(30 * s / steps)
                cur_r = r + (60 * s / steps)
                cur_dx = cur_r * math.cos(cur_rad)
                cur_dy = cur_r * math.sin(cur_rad)
                cdp.send('Input.dispatchTouchEvent', {
                    'type': 'touchMove',
                    'touchPoints': [
                        {'x': cx - cur_dx, 'y': cy - cur_dy, 'id': 0},
                        {'x': cx + cur_dx, 'y': cy + cur_dy, 'id': 1}
                    ]
                })
                time.sleep(0.015)
                
            time.sleep(0.08)
            cdp.send('Input.dispatchTouchEvent', {'type': 'touchEnd', 'touchPoints': []})
            page.wait_for_timeout(200)
            
            bearing_end_combo = page.evaluate("window.appState.map.getBearing()")
            zoom_end_combo = page.evaluate("window.appState.map.getZoom()")
            delta_bearing_combo = bearing_end_combo - bearing_start
            delta_zoom_combo = zoom_end_combo - zoom_start
            
            cur_mid_pos = page.evaluate(f"window.appState.map.project([{geo_mid['lng']}, {geo_mid['lat']}])")
            drift_mid_combo = math.hypot(cur_mid_pos['x'] - cx, cur_mid_pos['y'] - cy)
            
            print(f"3. Combined Zoom + 30° CW Rotation ({proj}):")
            print(f"   Delta Bearing: {delta_bearing_combo:.4f}° (expected ~ -30.0000°)")
            print(f"   Delta Zoom:    +{delta_zoom_combo:.4f} (expected zoom in > 0.5)")
            print(f"   Midpoint Pixel Drift: {drift_mid_combo:.6f} px")
            assert -30.5 <= delta_bearing_combo <= -29.5
            assert delta_zoom_combo > 0.5
            assert drift_mid_combo < 1.0
            
            results[proj] = {
                'cw_delta': delta_bearing_cw,
                'cw_drift': drift_mid_cw,
                'ccw_delta': delta_bearing_ccw,
                'ccw_drift': drift_mid_ccw,
                'combo_bearing_delta': delta_bearing_combo,
                'combo_zoom_delta': delta_zoom_combo,
                'combo_drift': drift_mid_combo,
            }
            
        # TEST 4: Safari gesturechange event testing
        print("\n--- TESTING SAFARI GESTURECHANGE EVENT ---")
        page.evaluate('''() => {
            window.appState.map.setBearing(0);
        }''')
        # Simulate gesturestart and gesturechange with rotation = +30 (clockwise)
        page.evaluate('''() => {
            const container = document.getElementById('map-container');
            const gStart = new Event('gesturestart', { bubbles: true, cancelable: true });
            container.dispatchEvent(gStart);
            
            const gChange = new Event('gesturechange', { bubbles: true, cancelable: true });
            gChange.rotation = 30; // +30 deg clockwise in Safari
            gChange.scale = 1.0;
            container.dispatchEvent(gChange);
        }''')
        page.wait_for_timeout(200)
        safari_bearing = page.evaluate("window.appState.map.getBearing()")
        print(f"Safari gesturechange (+30° CW): Resulting bearing = {safari_bearing:.4f}° (expected -30.0000°)")
        assert -30.5 <= safari_bearing <= -29.5, f"Safari gesture rotation reversed! Got {safari_bearing}"
        
        # Test angle wraparound
        page.evaluate('''() => {
            const container = document.getElementById('map-container');
            window.appState.map.setBearing(10);
            
            const gStart = new Event('gesturestart', { bubbles: true, cancelable: true });
            container.dispatchEvent(gStart);
            
            const gChange = new Event('gesturechange', { bubbles: true, cancelable: true });
            gChange.rotation = 30; // 10° - 30° = -20°
            container.dispatchEvent(gChange);
        }''')
        page.wait_for_timeout(200)
        wraparound_bearing = page.evaluate("window.appState.map.getBearing()")
        print(f"Safari gesturechange wraparound test (10° - 30°): Resulting bearing = {wraparound_bearing:.4f}° (expected -20.0000°)")
        assert -20.5 <= wraparound_bearing <= -19.5
        
        print("\n=== ALL ROTATION AND GESTURE TESTS PASSED! ===")
        browser.close()

if __name__ == '__main__':
    test_rotation()
