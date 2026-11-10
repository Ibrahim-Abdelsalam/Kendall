import os
import asyncio
from playwright.async_api import async_playwright
from PIL import Image

BRAVE_PATH = "/Applications/Brave Browser.app/Contents/MacOS/Brave Browser"
ICONS_DIR = os.path.abspath("web/icons")
os.makedirs(ICONS_DIR, exist_ok=True)

async def generate():
    svg_path = os.path.abspath("web/icons/kendall.svg")
    
    # 1. HTML harness to render master SVG cleanly
    harness_html = f"""<!DOCTYPE html>
<html>
<head>
  <style>
    * {{ margin: 0; padding: 0; box-sizing: border-box; }}
    html, body {{ width: 512px; height: 512px; background: transparent; overflow: hidden; }}
  </style>
</head>
<body>
  <img src="file://{svg_path}" width="512" height="512" style="display:block;" />
</body>
</html>"""
    harness_file = os.path.abspath("scratch/icon_harness.html")
    with open(harness_file, "w") as f:
        f.write(harness_html)

    # 2. HTML harness for OG Image (1200x630)
    og_html = f"""<!DOCTYPE html>
<html>
<head>
  <link rel="preconnect" href="https://fonts.googleapis.com">
  <link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
  <link href="https://fonts.googleapis.com/css2?family=Barlow+Condensed:wght@600;700;800&family=IBM+Plex+Mono:wght@500;600&family=Inter:wght@400;500;600&display=swap" rel="stylesheet">
  <style>
    * {{ margin: 0; padding: 0; box-sizing: border-box; }}
    body {{
      width: 1200px;
      height: 630px;
      background: #0B1630;
      color: #E2E8F0;
      font-family: 'Inter', sans-serif;
      position: relative;
      overflow: hidden;
      display: flex;
      align-items: center;
      justify-content: center;
    }}
    /* Technical grid background */
    .grid-bg {{
      position: absolute;
      inset: 0;
      background-image: 
        linear-gradient(rgba(34, 211, 238, 0.05) 1px, transparent 1px),
        linear-gradient(90deg, rgba(34, 211, 238, 0.05) 1px, transparent 1px);
      background-size: 40px 40px;
      background-position: center center;
    }}
    /* Subtle radial glow */
    .glow-cyan {{
      position: absolute;
      top: -100px;
      left: 100px;
      width: 600px;
      height: 600px;
      background: radial-gradient(circle, rgba(34, 211, 238, 0.12) 0%, transparent 70%);
      pointer-events: none;
    }}
    .glow-orange {{
      position: absolute;
      bottom: -150px;
      right: 150px;
      width: 650px;
      height: 650px;
      background: radial-gradient(circle, rgba(255, 107, 53, 0.10) 0%, transparent 70%);
      pointer-events: none;
    }}
    .container {{
      position: relative;
      z-index: 10;
      width: 1040px;
      display: flex;
      align-items: center;
      gap: 60px;
      background: rgba(11, 22, 48, 0.75);
      border: 1px solid rgba(34, 211, 238, 0.25);
      padding: 48px 56px;
      box-shadow: 0 24px 64px rgba(0, 0, 0, 0.6);
    }}
    .icon-wrap {{
      flex-shrink: 0;
      width: 260px;
      height: 260px;
      display: flex;
      align-items: center;
      justify-content: center;
      filter: drop-shadow(0 12px 32px rgba(34, 211, 238, 0.3));
    }}
    .icon-wrap img {{
      width: 260px;
      height: 260px;
      border-radius: 48px;
    }}
    .content {{
      display: flex;
      flex-direction: column;
      gap: 12px;
    }}
    .eyebrow {{
      display: flex;
      align-items: center;
      gap: 12px;
      font-family: 'IBM Plex Mono', monospace;
      font-size: 13px;
      color: #22D3EE;
      letter-spacing: 0.15em;
      text-transform: uppercase;
    }}
    .badge {{
      background: rgba(34, 211, 238, 0.15);
      border: 1px solid #22D3EE;
      padding: 2px 8px;
      font-weight: 600;
    }}
    h1 {{
      font-family: 'Barlow Condensed', sans-serif;
      font-size: 76px;
      font-weight: 800;
      letter-spacing: 0.05em;
      line-height: 0.95;
      color: #FFFFFF;
      text-shadow: 0 2px 16px rgba(0,0,0,0.5);
    }}
    .tagline {{
      font-family: 'Barlow Condensed', sans-serif;
      font-size: 26px;
      font-weight: 600;
      color: #22D3EE;
      letter-spacing: 0.04em;
      text-transform: uppercase;
    }}
    .lead {{
      font-size: 15px;
      color: #94A3B8;
      line-height: 1.45;
      max-width: 580px;
      margin-top: 4px;
    }}
    .meta-row {{
      display: flex;
      align-items: center;
      gap: 20px;
      margin-top: 10px;
      font-family: 'IBM Plex Mono', monospace;
      font-size: 11px;
      color: #64748B;
      letter-spacing: 0.08em;
    }}
    .meta-item {{
      display: flex;
      align-items: center;
      gap: 6px;
    }}
    .dot-cyan {{
      width: 6px;
      height: 6px;
      border-radius: 50%;
      background: #22D3EE;
    }}
    .dot-orange {{
      width: 6px;
      height: 6px;
      border-radius: 50%;
      background: #FF6B35;
    }}
  </style>
</head>
<body>
  <div class="grid-bg"></div>
  <div class="glow-cyan"></div>
  <div class="glow-orange"></div>
  
  <div class="container">
    <div class="icon-wrap">
      <img src="file://{svg_path}" />
    </div>
    <div class="content">
      <div class="eyebrow">
        <span class="badge">p &lt; 0.05</span>
        <span>PRESENTS</span>
      </div>
      <h1>KENDALL</h1>
      <div class="tagline">Find the trends that are real.</div>
      <p class="lead">Planetary Multi-Decadal Trend &amp; Era Shift Detector (2000–2025). Autocorrelation-corrected Mann-Kendall statistics, Hamed-Rao variance inflation, and false-discovery rate control across 10,368 grid cells.</p>
      <div class="meta-row">
        <span class="meta-item"><span class="dot-cyan"></span> 6 Planetary Variables</span>
        <span class="meta-item"><span class="dot-orange"></span> 2014 Era Break</span>
        <span class="meta-item"><span class="dot-cyan"></span> Globe &amp; Flat Projections</span>
      </div>
    </div>
  </div>
</body>
</html>"""
    og_file = os.path.abspath("scratch/og_harness.html")
    with open(og_file, "w") as f:
        f.write(og_html)

    async with async_playwright() as p:
        browser = await p.chromium.launch(
            executable_path=BRAVE_PATH if os.path.exists(BRAVE_PATH) else None,
            headless=True
        )
        
        # 1. Render master 512x512
        page = await browser.new_page(viewport={"width": 512, "height": 512}, device_scale_factor=1)
        await page.goto(f"file://{harness_file}")
        await page.wait_for_timeout(300)
        p512_path = os.path.join(ICONS_DIR, "icon-512.png")
        await page.screenshot(path=p512_path, omit_background=True)
        print("Generated icon-512.png")

        # 2. Render OG Image 1200x630
        page_og = await browser.new_page(viewport={"width": 1200, "height": 630}, device_scale_factor=1)
        await page_og.goto(f"file://{og_file}")
        await page_og.wait_for_timeout(600)
        og_path = os.path.join(ICONS_DIR, "og-image.png")
        await page_og.screenshot(path=og_path)
        print("Generated og-image.png (1200x630)")

        await browser.close()

    # 3. Downscale icons from 512x512 with Pillow LANCZOS
    base_img = Image.open(p512_path)
    
    # 192x192
    img_192 = base_img.resize((192, 192), Image.Resampling.LANCZOS)
    img_192.save(os.path.join(ICONS_DIR, "icon-192.png"))
    print("Generated icon-192.png")

    # 180x180 (apple-touch-icon)
    img_180 = base_img.resize((180, 180), Image.Resampling.LANCZOS)
    img_180.save(os.path.join(ICONS_DIR, "apple-touch-icon.png"))
    print("Generated apple-touch-icon.png")

    # 32x32
    img_32 = base_img.resize((32, 32), Image.Resampling.LANCZOS)
    img_32.save(os.path.join(ICONS_DIR, "favicon-32x32.png"))
    print("Generated favicon-32x32.png")

    # 16x16
    img_16 = base_img.resize((16, 16), Image.Resampling.LANCZOS)
    img_16.save(os.path.join(ICONS_DIR, "favicon-16x16.png"))
    print("Generated favicon-16x16.png")

    # 48x48
    img_48 = base_img.resize((48, 48), Image.Resampling.LANCZOS)

    # Multi-resolution ICO at web/favicon.ico
    ico_path = os.path.abspath("web/favicon.ico")
    base_img.save(ico_path, format="ICO", sizes=[(16, 16), (32, 32), (48, 48)])
    print(f"Generated {ico_path}")

asyncio.run(generate())
