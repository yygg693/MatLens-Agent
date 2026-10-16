import os, sys
sys.path.insert(0, r"D:/MatLens"); os.chdir(r"D:/MatLens")
from playwright.sync_api import sync_playwright
with sync_playwright() as pw:
    b = pw.chromium.launch(headless=True)
    pg = b.new_page(viewport={"width": 1700, "height": 1000})
    pg.goto("http://127.0.0.1:7896/", wait_until="domcontentloaded", timeout=60000)
    pg.wait_for_timeout(3000)
    # 填入多行 + 一个附件态，看真实视觉
    pg.fill("#input", "帮我分析这份 XRD 数据中 Ca 共掺杂对晶格常数的影响，\n并对比不同烧结温度下的致密化表现")
    pg.wait_for_timeout(400)
    pg.locator(".chat-input").screenshot(path=r"D:/MatLens/_ui_input_zoom.png")
    # 打开 @ 选择器
    pg.fill("#input", "@")
    pg.wait_for_timeout(800)
    pg.screenshot(path=r"D:/MatLens/_ui_picker.png")
    b.close()
print("ok")
