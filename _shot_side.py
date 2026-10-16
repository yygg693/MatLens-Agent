import os, sys
sys.path.insert(0, r"D:/MatLens"); os.chdir(r"D:/MatLens")
from playwright.sync_api import sync_playwright
with sync_playwright() as pw:
    b = pw.chromium.launch(headless=True)
    pg = b.new_context(viewport={"width":1700,"height":1000}).new_page()
    pg.goto("http://127.0.0.1:7896/?t=E201", wait_until="domcontentloaded", timeout=60000)
    pg.wait_for_timeout(4500)
    pg.locator(".session-item").nth(1).hover(); pg.wait_for_timeout(500)
    pg.locator("#sidebar").screenshot(path=r"D:/MatLens/_ui_sidebar_final.png")
    print("ok")
    b.close()
