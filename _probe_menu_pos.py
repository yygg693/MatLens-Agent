import os, sys
sys.path.insert(0, r"D:/MatLens"); os.chdir(r"D:/MatLens")
from playwright.sync_api import sync_playwright
with sync_playwright() as pw:
    b = pw.chromium.launch(headless=True)
    pg = b.new_context(viewport={"width":1700,"height":1000}).new_page()
    pg.goto("http://127.0.0.1:7896/?t=7802", wait_until="domcontentloaded", timeout=60000)
    pg.wait_for_timeout(4300)
    pg.locator("#btn-add").click(); pg.wait_for_timeout(800)
    m = pg.evaluate("""()=>{
      const menu=document.querySelector('#add-menu'), btn=document.querySelector('#btn-add');
      const wrap=document.querySelector('.input-box-wrap'), bar=document.querySelector('.input-bar');
      const g=e=>{const b=e.getBoundingClientRect();return {x:Math.round(b.x),y:Math.round(b.y),w:Math.round(b.width),h:Math.round(b.height),bottom:Math.round(b.bottom)};};
      return {menu:g(menu), btn:g(btn), bar:g(bar), wrap:g(wrap),
              parent:menu.parentElement.className};}""")
    print("菜单:", m["menu"])
    print("加号:", m["btn"])
    print("工具条:", m["bar"])
    print("父容器:", m["parent"])
    print("菜单底部 vs 加号顶部: 间距", m["btn"]["y"]-m["menu"]["bottom"])
    b.close()
