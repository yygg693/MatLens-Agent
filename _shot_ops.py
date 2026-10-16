import os, sys
sys.path.insert(0, r"D:/MatLens"); os.chdir(r"D:/MatLens")
from playwright.sync_api import sync_playwright
with sync_playwright() as pw:
    b = pw.chromium.launch(headless=True)
    pg = b.new_context(viewport={"width":1700,"height":1000}).new_page()
    pg.goto("http://127.0.0.1:7896/?t=F301", wait_until="domcontentloaded", timeout=60000)
    pg.wait_for_timeout(4500)
    pg.locator(".session-item").nth(1).hover(); pg.wait_for_timeout(600)
    m = pg.evaluate("""()=>{const it=document.querySelectorAll('.session-item')[1];
      const o=it.querySelector('.s-ops').getBoundingClientRect(), ib=it.getBoundingClientRect();
      return {opsW:Math.round(o.width), opsH:Math.round(o.height),
              rightGap:Math.round(ib.right-o.right),
              overflow:o.right>ib.right+0.5,
              op: getComputedStyle(it.querySelector('.s-ops')).opacity,
              btns:[...it.querySelectorAll('.s-op')].map(b=>Math.round(b.getBoundingClientRect().width))};}""")
    print("  操作组:", m["opsW"], "x", m["opsH"], " 右边距", m["rightGap"], " 溢出", m["overflow"], " 常态透明度", m["op"])
    print("  按钮宽:", m["btns"])
    pg.locator("#side-sessions").screenshot(path=r"D:/MatLens/_ui_ops_v3.png")
    b.close()
