import os, sys
sys.path.insert(0, r"D:/MatLens"); os.chdir(r"D:/MatLens")
from playwright.sync_api import sync_playwright
with sync_playwright() as pw:
    b = pw.chromium.launch(headless=True)
    pg = b.new_page(viewport={"width": 1700, "height": 1000})
    pg.goto("http://127.0.0.1:7896/", wait_until="domcontentloaded", timeout=60000)
    pg.wait_for_timeout(3000)
    m = pg.evaluate("""() => {
      const box=document.querySelector('.input-box');
      const chips=document.querySelector('.input-chips');
      const r=(e)=>{const b=e.getBoundingClientRect();return {x:Math.round(b.x),y:Math.round(b.y),w:Math.round(b.width),h:Math.round(b.height)};};
      return {box:r(box), chips:chips?r(chips):null, chipCount:document.querySelectorAll('.chip').length,
              align:getComputedStyle(box).alignItems, wrap:getComputedStyle(box).flexWrap};
    }""")
    print(m)
    b.close()
