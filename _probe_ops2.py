import os, sys
sys.path.insert(0, r"D:/MatLens"); os.chdir(r"D:/MatLens")
from playwright.sync_api import sync_playwright
with sync_playwright() as pw:
    b = pw.chromium.launch(headless=True)
    pg = b.new_context(viewport={"width":1700,"height":1000}).new_page()
    pg.goto("http://127.0.0.1:7896/?t=F101", wait_until="domcontentloaded", timeout=60000)
    pg.wait_for_timeout(4500)
    it = pg.locator(".session-item").nth(1)
    it.hover(); pg.wait_for_timeout(600)
    m = pg.evaluate("""()=>{
      const it=document.querySelectorAll('.session-item')[1];
      const ops=it.querySelector('.s-ops');
      const o=ops.getBoundingClientRect(), ib=it.getBoundingClientRect();
      const sb=document.getElementById('side-sessions');
      const cs=getComputedStyle(sb);
      const sOpsCs=getComputedStyle(ops);
      return {
        itemW:Math.round(ib.width), itemH:Math.round(ib.height),
        itemOverflow:getComputedStyle(it).overflow,
        opsW:Math.round(o.width), opsH:Math.round(o.height),
        opsRightGap:Math.round(ib.right-o.right),
        opsOverflowsItem: o.right > ib.right+0.5 || o.left < ib.left-0.5,
        sideW:Math.round(sb.getBoundingClientRect().width),
        sidePad:cs.paddingLeft+'/'+cs.paddingRight,
        sideOverflow:cs.overflow,
        listOverflow:getComputedStyle(document.getElementById('session-list')).overflow,
        opsPos:sOpsCs.position, opsOpacity:sOpsCs.opacity,
        btns:[...ops.querySelectorAll('.s-op')].map(b=>{const r=b.getBoundingClientRect();
          return {w:Math.round(r.width),h:Math.round(r.height)};})};}""")
    for k,v in m.items(): print(f"  {k} = {v}")
    pg.locator("#side-sessions").screenshot(path=r"D:/MatLens/_ui_ops_overflow.png")
    b.close()
