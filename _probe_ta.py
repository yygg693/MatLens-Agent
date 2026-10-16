import os, sys
sys.path.insert(0, r"D:/MatLens"); os.chdir(r"D:/MatLens")
from playwright.sync_api import sync_playwright
with sync_playwright() as pw:
    b = pw.chromium.launch(headless=True)
    pg = b.new_context(viewport={"width":1700,"height":1000}).new_page()
    pg.goto("http://127.0.0.1:7896/", wait_until="domcontentloaded", timeout=60000)
    pg.wait_for_timeout(4000)
    ta = pg.locator("#input")
    ta.click()
    ta.type("第一行\n第二行\n第三行", delay=30)
    pg.wait_for_timeout(500)
    m = pg.evaluate("""() => {
      const e=document.querySelector('#input');
      return {value:e.value, len:e.value.length, rows:e.rows,
              styleH:e.style.height, cssH:getComputedStyle(e).height,
              scrollH:e.scrollHeight, clientH:e.clientHeight,
              wrapAttr:e.getAttribute('wrap'),
              parent: e.parentElement.className,
              parentDisp: getComputedStyle(e.parentElement).display,
              parentAlign: getComputedStyle(e.parentElement).alignItems};
    }""")
    for k,v in m.items(): print(f"  {k} = {v!r}")
    b.close()
