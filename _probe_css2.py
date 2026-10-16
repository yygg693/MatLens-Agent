import os, sys, time
sys.path.insert(0, r"D:/MatLens"); os.chdir(r"D:/MatLens")
from playwright.sync_api import sync_playwright
with sync_playwright() as pw:
    b = pw.chromium.launch(headless=True)
    pg = b.new_context(viewport={"width":1700,"height":1000}).new_page()
    pg.goto("http://127.0.0.1:7896/", wait_until="domcontentloaded", timeout=60000)
    pg.wait_for_timeout(4000)
    pg.locator("#input").click()
    pg.keyboard.type("@论文", delay=60)
    for w in (500, 1200, 2500):
        pg.wait_for_timeout(w if w==500 else w-500)
        m = pg.evaluate("""() => [...document.querySelectorAll('#tp-list .tp-item')]
            .map(e=>({n:e.dataset.name,
                      h:Math.round(e.getBoundingClientRect().height),
                      w:Math.round(e.getBoundingClientRect().width),
                      d:getComputedStyle(e).display}))""")
        print(f"  t={w}ms:", [(x['n'][:16], x['h'], x['w'], x['d']) for x in m])
    b.close()
