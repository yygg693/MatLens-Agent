import os, sys
sys.path.insert(0, r"D:/MatLens"); os.chdir(r"D:/MatLens")
from playwright.sync_api import sync_playwright
with sync_playwright() as pw:
    b = pw.chromium.launch(headless=True)
    pg = b.new_context(viewport={"width":1700,"height":1000}).new_page()
    pg.goto("http://127.0.0.1:7896/", wait_until="domcontentloaded", timeout=60000)
    pg.wait_for_timeout(4000)
    pg.locator("#input").click()
    pg.keyboard.type("@论文", delay=60); pg.wait_for_timeout(1200)
    m = pg.evaluate("""() => {
      const it = document.querySelector('#tp-list .tp-item');
      const g = e => { const b=e.getBoundingClientRect(); const c=getComputedStyle(e);
        return {w:Math.round(b.width),h:Math.round(b.height),disp:c.display,
                flex:c.flex, minW:c.minWidth, maxW:c.maxWidth, over:c.overflow}; };
      return {item:g(it), icon:g(it.querySelector('.tp-icon')),
              info:g(it.querySelector('.tp-info')), name:g(it.querySelector('.tp-name')),
              desc:g(it.querySelector('.tp-desc')), key:g(it.querySelector('.tp-key'))};
    }""")
    for k,v in m.items(): print(f"  {k:5} = {v}")
    b.close()
