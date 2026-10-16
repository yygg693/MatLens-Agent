import os, sys
sys.path.insert(0, r"D:/MatLens"); os.chdir(r"D:/MatLens")
from playwright.sync_api import sync_playwright
errs=[]
with sync_playwright() as pw:
    b = pw.chromium.launch(headless=True)
    pg = b.new_context(viewport={"width":1700,"height":1000}).new_page()
    pg.on("console", lambda m: errs.append(f"[{m.type}] {m.text}") if m.type=="error" and "favicon" not in m.text else None)
    pg.on("pageerror", lambda e: errs.append(f"[pageerror] {e}"))
    pg.goto("http://127.0.0.1:7896/?t=C302", wait_until="domcontentloaded", timeout=60000)
    pg.wait_for_timeout(4500)
    it = pg.locator(".session-item").first
    it.hover(); pg.wait_for_timeout(600)
    m = pg.evaluate("""()=>{
      const it=document.querySelector('.session-item');
      const ops=it.querySelector('.s-ops');
      const o=ops.getBoundingClientRect(), ib=it.getBoundingClientRect();
      return {op:getComputedStyle(ops).opacity, pointer:getComputedStyle(ops).pointerEvents,
              rightGap:Math.round(ib.right-o.right),
              opsW:Math.round(o.width), opsH:Math.round(o.height),
              sideW:Math.round(document.querySelector('.side-sessions').getBoundingClientRect().width),
              btns:[...ops.querySelectorAll('.s-op')].map(x=>{
                const r=x.getBoundingClientRect();
                return {act:x.dataset.act,w:Math.round(r.width),h:Math.round(r.height),
                        hasSvg:!!x.querySelector('svg'), emoji:/\\p{Extended_Pictographic}/u.test(x.textContent)};}),
              emojiLeft:it.innerText.replace(/\\n/g,' ').match(/[\\u{1F300}-\\u{1FAFF}\\u{2600}-\\u{27BF}]/gu)};}""")
    print("  操作区: opacity=",m["op"]," pointer=",m["pointer"]," 宽=",m["opsW"]," 右边距=",m["rightGap"])
    print("  侧栏宽=",m["sideW"])
    for x in m["btns"]: print("   ",x)
    print("  行内残留emoji:", m["emojiLeft"])
    pg.locator(".side-sessions").screenshot(path=r"D:/MatLens/_ui_ops_hover.png")
    b.close()
print("console:", [e for e in errs if "ERR_" not in e][:4] or "无")
