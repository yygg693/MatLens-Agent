import os, sys
sys.path.insert(0, r"D:/MatLens"); os.chdir(r"D:/MatLens")
from playwright.sync_api import sync_playwright
with sync_playwright() as pw:
    b = pw.chromium.launch(headless=True)
    pg = b.new_context(viewport={"width":1700,"height":1000}).new_page()
    pg.goto("http://127.0.0.1:7896/?t=7801", wait_until="domcontentloaded", timeout=60000)
    pg.wait_for_timeout(4300)
    for w in (1700, 1200, 900):
        pg.set_viewport_size({"width": w, "height": 900}); pg.wait_for_timeout(700)
        m = pg.evaluate("""() => {
          const ta=document.querySelector('#input'), bar=document.querySelector('.input-bar');
          const box=document.querySelector('.input-box');
          const g=e=>{const b=e.getBoundingClientRect();return {w:Math.round(b.width),h:Math.round(b.height),y:Math.round(b.y)};};
          return {ta:g(ta), bar:g(bar), box:g(box),
                  dir:getComputedStyle(box).flexDirection,
                  barScroll: bar.scrollWidth>bar.clientWidth+2,
                  taBelowBar: g(ta).y < g(bar).y};
        }""")
        print(f"[{w}px] textarea宽={m['ta']['w']} 工具条高={m['bar']['h']} 方向={m['dir']} 工具条需滚动={m['barScroll']} textarea在上方={m['taBelowBar']}")
    pg.set_viewport_size({"width":1700,"height":1000}); pg.wait_for_timeout(600)
    # 自动增高是否仍工作
    for n in (1,4,9):
        pg.evaluate("""(n)=>{const e=document.querySelector('#input');
          e.value=Array.from({length:n},(_,i)=>'这是第'+(i+1)+'行测试内容稍微长一点让它换行').join('\\n');
          e.dispatchEvent(new Event('input'));}""", n)
        pg.wait_for_timeout(300)
        print(f"  {n}行 → textarea高 {pg.evaluate('()=>Math.round(document.querySelector(\"#input\").getBoundingClientRect().height)')}px")
    pg.locator(".input-box").screenshot(path=r"D:/MatLens/_ui_2row.png")
    b.close()
