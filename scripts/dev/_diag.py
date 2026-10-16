import os, sys
sys.path.insert(0, r"D:/MatLens"); os.chdir(r"D:/MatLens")
from playwright.sync_api import sync_playwright
errs=[]
with sync_playwright() as pw:
    b = pw.chromium.launch(headless=True)
    pg = b.new_context(viewport={"width":1700,"height":1000}).new_page()
    pg.on("console", lambda m: errs.append(f"[{m.type}] {m.text}"))
    pg.on("pageerror", lambda e: errs.append(f"[pageerror] {e}"))
    pg.goto("http://127.0.0.1:7896/?t=D202&cb=1", wait_until="domcontentloaded", timeout=60000)
    pg.wait_for_timeout(4500)
    print("session-list 内容前 200:")
    print(repr(pg.evaluate("()=>document.getElementById('session-list')?.innerText.slice(0,200)")))
    print("条目数:", pg.locator(".session-item").count())
    print("s-toggle 数:", pg.locator(".s-toggle").count())
    print("\n错误:")
    for e in errs[:6]: print("  ", e[:220])
    b.close()
