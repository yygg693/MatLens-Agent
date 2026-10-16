import os, sys
sys.path.insert(0, r"D:/MatLens"); os.chdir(r"D:/MatLens")
from playwright.sync_api import sync_playwright
with sync_playwright() as pw:
    b = pw.chromium.launch(headless=True)
    pg = b.new_page(viewport={"width": 1700, "height": 1050})
    pg.goto("http://127.0.0.1:7896/", wait_until="domcontentloaded", timeout=60000)
    pg.wait_for_timeout(3000)
    pg.locator("text=工具中心").first.click(); pg.wait_for_timeout(3500)
    pg.locator('.tool-tile:has(.tt-badge)').first.click(); pg.wait_for_timeout(1500)
    pg.screenshot(path=r"D:/MatLens/_ui_drawer.png")
    b.close()
print("ok")
