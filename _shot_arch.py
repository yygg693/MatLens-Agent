import os, sys
sys.path.insert(0, r"D:/MatLens"); os.chdir(r"D:/MatLens")
from playwright.sync_api import sync_playwright
errs=[]
with sync_playwright() as pw:
    b = pw.chromium.launch(headless=True)
    pg = b.new_context(viewport={"width":1700,"height":1000}).new_page()
    pg.on("console", lambda m: errs.append(f"[{m.type}] {m.text}") if m.type=="error" and "favicon" not in m.text else None)
    pg.on("pageerror", lambda e: errs.append(f"[pageerror] {e}"))
    pg.goto("http://127.0.0.1:7896/?t=F201", wait_until="domcontentloaded", timeout=60000)
    pg.wait_for_timeout(4500)
    # 侧栏 hover 态
    pg.locator(".session-item").nth(1).hover(); pg.wait_for_timeout(600)
    pg.locator("#side-sessions").screenshot(path=r"D:/MatLens/_ui_ops_v2.png")
    # 设置会话面板
    pg.locator("#btn-manage-archive").click(); pg.wait_for_timeout(2200)
    m = pg.evaluate("""()=>{
      const p=document.querySelector('[data-pane="sessions"]');
      const btn=document.getElementById('btn-distill-sessions');
      const sel=document.getElementById('distill-scope-ui');
      const btnCs=btn?getComputedStyle(btn):null;
      return {btnText:(document.getElementById('distill-btn-tx')||{}).textContent,
              btnW:btn?Math.round(btn.getBoundingClientRect().width):0,
              btnH:btn?Math.round(btn.getBoundingClientRect().height):0,
              btnBg:btnCs?btnCs.background:'n/a',
              selW:sel?Math.round(sel.getBoundingClientRect().width):0,
              selText:sel?sel.innerText.trim():'-',
              hasSvgInBtn: btn?!!btn.querySelector('svg'):false,
              selectHidden: document.getElementById('distill-scope')?.offsetParent===null,
              paneH: Math.round(p.getBoundingClientRect().height)};}""")
    print("提炼钮:", m["btnText"], " 尺寸:", m["btnW"], "x", m["btnH"])
    print("  背景:", m["btnBg"], " 含SVG:", m["hasSvgInBtn"])
    print("范围选择器: 宽", m["selW"], " 文案", repr(m["selText"]), " 原生select隐藏:", m["selectHidden"])
    pg.locator('[data-pane="sessions"]').screenshot(path=r"D:/MatLens/_ui_archbox_v2.png")
    b.close()
print("console:", [e for e in errs if "ERR_" not in e][:3] or "无")
