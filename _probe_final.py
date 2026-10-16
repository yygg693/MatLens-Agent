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
    m = pg.evaluate("""() => [...document.querySelectorAll('#tp-list .tp-item')]
        .map(e=>({cls:e.className, outer:e.outerHTML.slice(0,60),
                  parentCls:e.parentElement.className,
                  sibs:e.parentElement.children.length,
                  idx:[...e.parentElement.children].indexOf(e)}))""")
    for x in m: print(" ", x)
    b.close()
