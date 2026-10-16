import os, sys
sys.path.insert(0, r"D:/MatLens"); os.chdir(r"D:/MatLens")
from playwright.sync_api import sync_playwright
errs=[]
with sync_playwright() as pw:
    b = pw.chromium.launch(headless=True)
    ctx = b.new_context(viewport={"width":1700,"height":1000}, bypass_csp=True)
    pg = ctx.new_page()
    pg.on("pageerror", lambda e: errs.append(f"[pageerror] {e}"))
    pg.goto("http://127.0.0.1:7896/", wait_until="domcontentloaded", timeout=60000)
    # 强制清缓存重载
    pg.goto("http://127.0.0.1:7896/?t=999", wait_until="domcontentloaded", timeout=60000)
    pg.wait_for_timeout(4200)
    has = pg.evaluate("()=>typeof window.ML.toolPickerKey")
    print("window.ML.toolPickerKey 存在:", has)
    ta = pg.locator("#input")
    for n in (1,4,8):
        ta.click(); pg.keyboard.press("Control+a"); pg.keyboard.press("Delete")
        ta.type("\n".join("第%d行测试内容稍微长一点让它换行"%k for k in range(1,n+1)), delay=1)
        pg.wait_for_timeout(350)
        h = ta.evaluate("e=>Math.round(e.getBoundingClientRect().height)")
        sh = ta.evaluate("e=>e.scrollHeight")
        print(f"  {n}行 → 高{h}px scrollH={sh}")
    pg.screenshot(path=r"D:/MatLens/_ui_input_fixed.png")
    b.close()
print("错误:", [e for e in errs if "ERR_" not in e][:4] or "无")
