import os, sys
sys.path.insert(0, r"D:/MatLens"); os.chdir(r"D:/MatLens")
from playwright.sync_api import sync_playwright
with sync_playwright() as pw:
    b = pw.chromium.launch(headless=True)
    pg = b.new_page(viewport={"width": 1700, "height": 1000})
    pg.goto("http://127.0.0.1:7896/", wait_until="domcontentloaded", timeout=60000)
    pg.wait_for_timeout(3500)
    # 加号菜单
    pg.locator("#btn-add").click(); pg.wait_for_timeout(800)
    pg.locator(".input-box-wrap").screenshot(path=r"D:/MatLens/_ui_addmenu.png")
    pg.keyboard.press("Escape"); pg.wait_for_timeout(400)
    # 模型面板
    pg.locator("#chip-model").click(); pg.wait_for_timeout(1500)
    pg.screenshot(path=r"D:/MatLens/_ui_model_panel.png")
    # @ 选择器
    pg.locator("#chat-title").click(); pg.wait_for_timeout(400)
    pg.fill("#input", "@"); pg.wait_for_timeout(1000)
    pg.locator(".input-box-wrap").screenshot(path=r"D:/MatLens/_ui_picker_zoom.png")
    b.close()
print("ok")
