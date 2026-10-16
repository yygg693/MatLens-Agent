import os, sys
sys.path.insert(0, r"D:/MatLens"); os.chdir(r"D:/MatLens")
from playwright.sync_api import sync_playwright
with sync_playwright() as pw:
    b = pw.chromium.launch(headless=True)
    pg = b.new_page(viewport={"width": 1700, "height": 1000})
    pg.goto("http://127.0.0.1:7896/", wait_until="domcontentloaded", timeout=60000)
    pg.wait_for_timeout(3500)
    pg.locator("#input").click()
    pg.keyboard.type("@XRD", delay=120)
    pg.wait_for_timeout(1200)
    vis = pg.evaluate("()=>{const e=document.querySelector('#tool-picker');const s=getComputedStyle(e);return {d:s.display,h:Math.round(e.getBoundingClientRect().height)};}")
    print("@XRD 面板:", vis, "条目:", pg.locator("#tp-list .tp-item").count())
    pg.screenshot(path=r"D:/MatLens/_ui_picker2.png")
    pg.keyboard.type("图", delay=120); pg.wait_for_timeout(800)
    print("@XRD图 条目:", pg.locator("#tp-list .tp-item").count())
    b.close()
