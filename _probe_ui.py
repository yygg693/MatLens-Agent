import os, sys
sys.path.insert(0, r"D:/MatLens"); os.chdir(r"D:/MatLens")
from playwright.sync_api import sync_playwright
with sync_playwright() as pw:
    b = pw.chromium.launch(headless=True)
    pg = b.new_page(viewport={"width": 1700, "height": 1000})
    pg.goto("http://127.0.0.1:7896/", wait_until="domcontentloaded", timeout=60000)
    pg.wait_for_timeout(3000)
    m = pg.evaluate("""() => {
      const g=(s)=>{const e=document.querySelector(s); if(!e) return null;
        const b=e.getBoundingClientRect(); const c=getComputedStyle(e);
        return {w:Math.round(b.width),h:Math.round(b.height),x:Math.round(b.x),
                pad:c.padding, fs:c.fontSize, lh:c.lineHeight, bg:c.backgroundColor};};
      const chips=[...document.querySelectorAll('.input-chips > *')].map(e=>{
        const b=e.getBoundingClientRect();
        return {tag:e.id||e.className, w:Math.round(b.width), h:Math.round(b.height), y:Math.round(b.y)};});
      return {
        chatInput:g('.chat-input'), inputBox:g('.input-box'), textarea:g('#input'),
        sendBtn:g('.send-btn'), addBtn:g('.add-btn'), hint:g('.input-hint'),
        chips, chipWrapY:[...new Set(chips.map(c=>c.y))],
        iconSvg: (()=>{const s=document.querySelector('.input-box svg'); return s?Math.round(s.getBoundingClientRect().width):0;})(),
        iconCount: document.querySelectorAll('.input-box svg').length,
        iconColor: (()=>{const s=document.querySelector('.add-btn'); return s?getComputedStyle(s).color:'-';})(),
      };
    }""")
    print("chatInput:", m['chatInput'])
    print("inputBox:", m['inputBox'])
    print("textarea:", m['textarea'])
    print("hint:", m['hint'])
    print("图标数:", m['iconCount'], " svg宽:", m['iconSvg'], " 颜色:", m['iconColor'])
    print("chip 各行 y:", m['chipWrapY'], "  chip 条数:", len(m['chips']))
    for c in m['chips']: print("   ", c)
    b.close()
