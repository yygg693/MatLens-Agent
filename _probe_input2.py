import os, sys
sys.path.insert(0, r"D:/MatLens"); os.chdir(r"D:/MatLens")
from playwright.sync_api import sync_playwright
with sync_playwright() as pw:
    b = pw.chromium.launch(headless=True)
    pg = b.new_page(viewport={"width": 1700, "height": 1000})
    pg.goto("http://127.0.0.1:7896/", wait_until="domcontentloaded", timeout=60000)
    pg.wait_for_timeout(3000)
    # 1) 窄屏：输入框内元素会不会挤爆
    for w in (1700, 1200, 900):
        pg.set_viewport_size({"width": w, "height": 900})
        pg.wait_for_timeout(700)
        m = pg.evaluate("""() => {
          const box=document.querySelector('.input-box');
          const chips=document.querySelector('.input-chips');
          const ta=document.querySelector('#input');
          const r=e=>{const b=e.getBoundingClientRect();return {w:Math.round(b.width),h:Math.round(b.height),y:Math.round(b.y)};};
          const bx=r(box);
          const c=r(chips), t=r(ta);
          return {box:bx, chips:c, ta:t,
                  chipsOverflow: c.x+c.w > bx.x+bx.w+1,
                  chipsBelow: c.y+c.h > bx.y+bx.h-8,
                  wrap: getComputedStyle(box).flexWrap};
        }""")
        print(f"[{w}px] box={m['box']['w']}x{m['box']['h']} chips={m['chips']['w']} 溢出={m['chipsOverflow']} 换行={m['wrap']}")
    pg.set_viewport_size({"width": 1700, "height": 1000})
    pg.wait_for_timeout(600)
    # 2) 附件预览位置
    a = pg.evaluate("""() => {
      const ap=document.querySelector('#attach-preview');
      const box=document.querySelector('.input-box');
      const wrap=document.querySelector('.input-box-wrap');
      const g=e=>{const b=e.getBoundingClientRect();return {y:Math.round(b.y),h:Math.round(b.height),disp:getComputedStyle(e).display};};
      return {attach:g(ap), box:g(box), wrap:g(wrap), hintY: (()=>{const h=document.querySelector('.input-hint'); return h?Math.round(h.getBoundingClientRect().y):null;})()};
    }""")
    print("[垂直顺序] box.y=%d attach.y=%d(h=%s,%s) hint.y=%d" % (a['box']['y'], a['attach']['y'], a['attach']['h'], a['attach']['disp'], a['hintY']))
    b.close()
