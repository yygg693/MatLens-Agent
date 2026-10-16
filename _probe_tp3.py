import os, sys
sys.path.insert(0, r"D:/MatLens"); os.chdir(r"D:/MatLens")
from playwright.sync_api import sync_playwright
with sync_playwright() as pw:
    b = pw.chromium.launch(headless=True)
    pg = b.new_context(viewport={"width":1700,"height":1000}).new_page()
    pg.goto("http://127.0.0.1:7896/", wait_until="domcontentloaded", timeout=60000)
    pg.wait_for_timeout(4000)
    pg.locator("#input").click()
    pg.keyboard.type("@论文", delay=60); pg.wait_for_timeout(1500)
    # 连续采样3次，确认是否稳定
    for k in range(3):
        m = pg.evaluate("""() => [...document.querySelectorAll('#tp-list .tp-item')]
            .map(e=>({n:e.dataset.name, h:Math.round(e.getBoundingClientRect().height),
                      w:Math.round(e.getBoundingClientRect().width)}))""")
        print(f"  采样{k}: ", [(x['n'], x['h'], x['w']) for x in m])
        pg.wait_for_timeout(500)
    pg.locator(".input-box-wrap").screenshot(path=r"D:/MatLens/_ui_picker_fixed.png")
    b.close()
