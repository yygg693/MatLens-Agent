import os, sys
sys.path.insert(0, r"D:/MatLens"); os.chdir(r"D:/MatLens")
from playwright.sync_api import sync_playwright
errs=[]
with sync_playwright() as pw:
    b = pw.chromium.launch(headless=True)
    pg = b.new_context(viewport={"width":1700,"height":1000}).new_page()
    pg.on("console", lambda m: errs.append(f"[{m.type}] {m.text}"))
    pg.on("pageerror", lambda e: errs.append(f"[pageerror] {e}"))
    pg.goto("http://127.0.0.1:7896/?t=K203", wait_until="domcontentloaded", timeout=60000)
    pg.wait_for_timeout(4500)
    pg.locator('.nav-item[data-page="kb"]').click(); pg.wait_for_timeout(2500)
    print("doc-list innerHTML:", pg.evaluate("()=>document.getElementById('doc-list')?.innerHTML.slice(0,220)"))
    print("doc-list innerText:", repr(pg.evaluate("()=>document.getElementById('doc-list')?.innerText.slice(0,120)")))
    print("S.kb.name:", pg.evaluate("()=>{try{return window.ML?JSON.stringify(Object.keys(window.ML)):'no ML'}catch(e){return 'err'}}"))
    print("kb-item 数:", pg.locator(".kb-item").count())
    print("\n错误:")
    for e in errs[:5]: print("  ", e[:200])
    b.close()
