import os
import asyncio
from playwright.async_api import async_playwright

BRAVE_PATH = "/Applications/Brave Browser.app/Contents/MacOS/Brave Browser"
SCREENS_DIR = os.path.abspath("docs/screens")
os.makedirs(SCREENS_DIR, exist_ok=True)

async def run_verification():
    print("=== STARTING KENDALL VERIFICATION SUITE ===")
    
    # 1. Create Icon Scales & Legibility HTML page
    scales_html = f"""<!DOCTYPE html>
<html>
<head>
  <meta charset="UTF-8">
  <title>Kendall Icon Legibility Test</title>
  <link rel="preconnect" href="https://fonts.googleapis.com">
  <link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
  <link href="https://fonts.googleapis.com/css2?family=Barlow+Condensed:wght@600;700&family=IBM+Plex+Mono:wght@500;600&family=Inter:wght@400;500&display=swap" rel="stylesheet">
  <style>
    * {{ margin: 0; padding: 0; box-sizing: border-box; }}
    body {{
      background: #070B12;
      color: #E2E8F0;
      font-family: 'Inter', sans-serif;
      padding: 40px;
    }}
    h1 {{
      font-family: 'Barlow Condensed', sans-serif;
      font-size: 28px;
      letter-spacing: 0.05em;
      color: #22D3EE;
      margin-bottom: 24px;
      text-transform: uppercase;
    }}
    .grid {{
      display: flex;
      flex-direction: column;
      gap: 32px;
    }}
    .section-title {{
      font-family: 'IBM Plex Mono', monospace;
      font-size: 13px;
      color: #94A3B8;
      margin-bottom: 12px;
      text-transform: uppercase;
      letter-spacing: 0.1em;
    }}
    .row {{
      display: flex;
      align-items: center;
      gap: 28px;
      background: #0B1630;
      border: 1px solid rgba(34, 211, 238, 0.25);
      padding: 20px 24px;
      border-radius: 4px;
    }}
    .icon-box {{
      display: flex;
      flex-direction: column;
      align-items: center;
      gap: 8px;
    }}
    .icon-box span {{
      font-family: 'IBM Plex Mono', monospace;
      font-size: 11px;
      color: #64748B;
    }}
    .simulated-tab {{
      display: flex;
      align-items: center;
      gap: 10px;
      background: #182234;
      border: 1px solid rgba(255, 255, 255, 0.1);
      border-bottom: none;
      padding: 8px 16px;
      border-radius: 8px 8px 0 0;
      width: 280px;
      font-size: 12px;
      color: #E2E8F0;
    }}
  </style>
</head>
<body>
  <h1>Kendall &bull; Icon Legibility &amp; Multi-Scale Audit</h1>
  <div class="grid">
    <div>
      <div class="section-title">Multi-Resolution Rendering (SVG &amp; Downscaled PNG)</div>
      <div class="row">
        <div class="icon-box">
          <img src="http://localhost:8000/icons/favicon-16x16.png" width="16" height="16" />
          <span>16 &times; 16 (PNG)</span>
        </div>
        <div class="icon-box">
          <img src="http://localhost:8000/icons/favicon.svg" width="16" height="16" />
          <span>16 &times; 16 (SVG)</span>
        </div>
        <div class="icon-box">
          <img src="http://localhost:8000/icons/favicon-32x32.png" width="32" height="32" />
          <span>32 &times; 32 (PNG)</span>
        </div>
        <div class="icon-box">
          <img src="http://localhost:8000/icons/favicon.svg" width="32" height="32" />
          <span>32 &times; 32 (SVG)</span>
        </div>
        <div class="icon-box">
          <img src="http://localhost:8000/icons/apple-touch-icon.png" width="48" height="48" style="border-radius: 10px;" />
          <span>48 &times; 48</span>
        </div>
        <div class="icon-box">
          <img src="http://localhost:8000/icons/apple-touch-icon.png" width="64" height="64" style="border-radius: 14px;" />
          <span>64 &times; 64</span>
        </div>
        <div class="icon-box">
          <img src="http://localhost:8000/icons/icon-192.png" width="96" height="96" style="border-radius: 20px;" />
          <span>96 &times; 96 (PWA)</span>
        </div>
        <div class="icon-box">
          <img src="http://localhost:8000/icons/kendall.svg" width="128" height="128" />
          <span>128 &times; 128 (Master)</span>
        </div>
      </div>
    </div>

    <div>
      <div class="section-title">Browser Tab Simulation</div>
      <div class="row" style="background: #070D19;">
        <div class="simulated-tab">
          <img src="http://localhost:8000/icons/favicon-32x32.png" width="16" height="16" />
          <span style="overflow: hidden; text-overflow: ellipsis; white-space: nowrap;">p &lt; 0.05 / Kendall | Planetary Multi-Decadal...</span>
        </div>
      </div>
    </div>
  </div>
</body>
</html>"""
    scales_path = os.path.abspath("scratch/test_icon_legibility.html")
    with open(scales_path, "w") as f:
        f.write(scales_html)

    async with async_playwright() as p:
        browser = await p.chromium.launch(
            executable_path=BRAVE_PATH if os.path.exists(BRAVE_PATH) else None,
            headless=True
        )

        # 1. Screenshot Icon Scales
        page_scales = await browser.new_page(viewport={"width": 960, "height": 480}, device_scale_factor=2)
        await page_scales.goto(f"file://{scales_path}")
        await page_scales.wait_for_timeout(400)
        await page_scales.screenshot(path=os.path.join(SCREENS_DIR, "kendall_icon_scales.png"))
        print("Captured docs/screens/kendall_icon_scales.png")

        # 2. Main App Desktop View
        page = await browser.new_page(viewport={"width": 1440, "height": 900}, device_scale_factor=2)
        
        console_errors = []
        page.on("console", lambda msg: console_errors.append(msg.text) if msg.type == "error" else None)
        page.on("pageerror", lambda exc: console_errors.append(str(exc)))

        await page.goto("http://localhost:8000/")
        await page.wait_for_load_state("networkidle")
        await page.wait_for_timeout(600)

        # Verify Title
        title = await page.title()
        print(f"Page Title: {title}")
        assert "Kendall" in title, f"Title does not contain Kendall: {title}"
        assert "p < 0.05" in title, f"Title does not contain p < 0.05: {title}"

        # Capture Intro Screen
        await page.screenshot(path=os.path.join(SCREENS_DIR, "kendall_intro.png"))
        print("Captured docs/screens/kendall_intro.png")

        # Verify Intro Text
        intro_badge = await page.text_content(".intro-badge")
        intro_title = await page.text_content(".intro-title")
        intro_tagline = await page.text_content(".intro-tagline")
        print(f"Intro Badge: '{intro_badge.strip()}', Title: '{intro_title.strip()}', Tagline: '{intro_tagline.strip()}'")
        assert "p < 0.05" in intro_badge
        assert "KENDALL" in intro_title
        assert "Find the trends that are real." in intro_tagline

        # Dismiss Intro Overlay
        await page.click("#btn-intro-start")
        await page.wait_for_timeout(600)

        # Verify Header Brand Title and Icon
        header_title = await page.text_content(".brand-title")
        print(f"Header Title: '{header_title.strip()}'")
        assert "KENDALL" in header_title
        
        has_header_logo = await page.evaluate("() => !!document.querySelector('.brand-logo-svg')")
        print(f"Header Logo SVG present: {has_header_logo}")
        assert has_header_logo

        # Verify Footer Attribution
        footer_text = await page.text_content(".footer-attribution")
        print(f"Footer Attribution: '{footer_text.strip()}'")
        assert "Named after the Mann-Kendall trend test." in footer_text

        # Capture Tab & Header area
        await page.screenshot(path=os.path.join(SCREENS_DIR, "kendall_tab_and_header.png"))
        print("Captured docs/screens/kendall_tab_and_header.png")

        # Capture Footer HUD close-up
        footer_el = page.locator("#hud-bottom-bar")
        await footer_el.screenshot(path=os.path.join(SCREENS_DIR, "kendall_footer.png"))
        print("Captured docs/screens/kendall_footer.png")

        # 3. Mobile Viewport (iPhone 14 Pro style: 390x844)
        page_mobile = await browser.new_page(viewport={"width": 390, "height": 844}, device_scale_factor=2)
        await page_mobile.goto("http://localhost:8000/")
        await page_mobile.wait_for_load_state("networkidle")
        # Click start
        await page_mobile.click("#btn-intro-start")
        await page_mobile.wait_for_timeout(600)
        await page_mobile.screenshot(path=os.path.join(SCREENS_DIR, "kendall_mobile.png"))
        print("Captured docs/screens/kendall_mobile.png")

        await browser.close()

        print(f"Console errors detected during run: {len(console_errors)}")
        if console_errors:
            for err in console_errors:
                print(f"  ERROR: {err}")
        assert len(console_errors) == 0, "Console errors were logged!"
        print("=== VERIFICATION PASSED WITH ZERO CONSOLE ERRORS ===")

asyncio.run(run_verification())
