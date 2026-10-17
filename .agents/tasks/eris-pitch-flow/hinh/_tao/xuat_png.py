from pathlib import Path
from playwright.sync_api import sync_playwright

hinh = Path(__file__).resolve().parent.parent
png = hinh / "png"
png.mkdir(exist_ok=True)
with sync_playwright() as p:
    b = p.chromium.launch(channel="msedge")
    pg = b.new_page(viewport={"width": 1280, "height": 720}, device_scale_factor=2)
    for svg in sorted(hinh.glob("s[0-9][0-9]-*.svg")):
        pg.goto(svg.resolve().as_uri())
        pg.screenshot(path=str(png / (svg.stem + ".png")))
    b.close()
print("png ok")
