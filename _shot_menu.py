import os, sys
sys.path.insert(0, r"D:/MatLens"); os.chdir(r"D:/MatLens")
from playwright.sync_api import sync_playwright
with sync_playwright() as pw:
    b = pw.chromium.launch(headless=True)
    pg = b.new_context(viewport={"width":1700,"height":1000}).new_page()
    pg.goto("http://127.0.0.1:7896/?t=8811", wait_until="domcontentloaded", timeout=60000)
    pg.wait_for_timeout(4300)
    pg.locator("#btn-add").click(); pg.wait_for_timeout(900)
    # 直接截 add-menu 元素（避免 document click 收起）
    pg.locator("#add-menu").screenshot(path=r"D:/MatLens/_ui_menu_only.png")
    print("ok")
    b.close()
