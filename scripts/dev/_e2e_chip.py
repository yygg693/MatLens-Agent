import os, sys
sys.path.insert(0, r"D:/MatLens"); os.chdir(r"D:/MatLens")
from playwright.sync_api import sync_playwright
errs=[]
with sync_playwright() as pw:
    b = pw.chromium.launch(headless=True)
    pg = b.new_page(viewport={"width": 1700, "height": 1000})
    pg.on("console", lambda m: errs.append(f"[{m.type}] {m.text}") if m.type=="error" and "favicon" not in m.text else None)
    pg.on("pageerror", lambda e: errs.append(f"[pageerror] {e}"))
    pg.goto("http://127.0.0.1:7896/", wait_until="domcontentloaded", timeout=60000)
    pg.wait_for_timeout(4000)
    m = pg.evaluate("""() => {
      const chips=[...document.querySelectorAll('.input-chips .chip')].map(c=>({
        id:c.id, cls:c.className, tx:(c.textContent||'').trim().slice(0,20),
        led: c.querySelector('.chip-led') ? c.querySelector('.chip-led').className : null}));
      return {chips, sep: !!document.querySelector('.chip-sep'),
              order: [...document.querySelectorAll('.input-chips > *')].map(e=>e.id||e.className)};
    }""")
    print("分组顺序:", m["order"])
    print("分隔线:", m["sep"])
    for c in m["chips"]:
        print(f"  {c['id']:14} cls={c['cls']:24} tx={c['tx']:14} led={c['led']}")
    pg.screenshot(path=r"D:/MatLens/_ui_chips.png")
    b.close()
print("console:", [e for e in errs if "ERR_CONNECTION" not in e][:4] or "无")
