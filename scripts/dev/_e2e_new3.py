# -*- coding: utf-8 -*-
"""工作区 + 会话归档 + 审批面板 + 死 UI 清理 验证。"""
import os, sys
sys.path.insert(0, r"D:/MatLens"); os.chdir(r"D:/MatLens")
from playwright.sync_api import sync_playwright
errs=[]
with sync_playwright() as pw:
    b = pw.chromium.launch(headless=True)
    pg = b.new_context(viewport={"width":1700,"height":1000}).new_page()
    pg.on("console", lambda m: errs.append(f"[{m.type}] {m.text}") if m.type=="error" and "favicon" not in m.text else None)
    pg.on("pageerror", lambda e: errs.append(f"[pageerror] {e}"))
    pg.goto("http://127.0.0.1:7896/?t=A101", wait_until="domcontentloaded", timeout=60000)
    pg.wait_for_timeout(4500)

    print("=== 死 UI 清理 ===")
    print("  mode-badge 是否残留:", pg.locator("#mode-badge").count()>0)
    print("  L2 文案是否残留:", "L2" in pg.evaluate("()=>document.querySelector('.input-bar')?.innerText||''"))

    print("\n=== 工作区 chip ===")
    ws_tx = pg.locator("#chip-ws-name").inner_text()
    print("  chip 文案:", repr(ws_tx))
    pg.locator("#chip-ws").click(); pg.wait_for_timeout(1500)
    m = pg.evaluate("""()=>{const e=document.getElementById('ws-panel');
      return {disp:getComputedStyle(e).display, secs:[...e.querySelectorAll('.cp-sec')].map(s=>s.childNodes[0].textContent.trim()),
              addBtn: !!e.querySelector('#ws-add-btn'), items:e.querySelectorAll('.ws-item').length,
              rows:e.querySelectorAll('.ws-row').length, hint: !!e.querySelector('.ws-hint')};}""")
    print("  面板:", m["disp"], " 分段:", m["secs"])
    print("  添加按钮:", m["addBtn"], " 会话数:", m["items"], " 工作区行:", m["rows"], " 空态提示:", m["hint"])
    print("  归档按钮数:", pg.locator(".ws-arch").count(), " 归档箱段:", any("归档箱" in x for x in m["secs"]))
    pg.locator("#ws-panel").screenshot(path=r"D:/MatLens/_ui_ws_panel.png")

    print("\n=== 审批面板 ===")
    pg.keyboard.press("Escape"); pg.wait_for_timeout(400)
    pg.locator("#chip-approval").click(); pg.wait_for_timeout(1500)
    a = pg.evaluate("""()=>{const e=document.getElementById('approval-panel');
      return {disp:getComputedStyle(e).display,
              warn:(document.getElementById('approval-warn')||{}).textContent||'',
              warnVis: getComputedStyle(document.getElementById('approval-warn')).display,
              note:(document.getElementById('approval-note')||{}).textContent||'',
              tags:e.querySelectorAll('.ap-tag').length,
              denyTags:e.querySelectorAll('.ap-tag.deny').length,
              allowN:(document.getElementById('ap-allow-n')||{}).textContent,
              inputs:e.querySelectorAll('.ap-input').length};}""")
    print("  面板:", a["disp"])
    print("  警告条:", a["warn"][:70])
    print("  说明:", a["note"][:56])
    print(f"  免审标签 {a['tags']-a['denyTags']} 个 / 高危 {a['denyTags']} 个 / 计数徽标 {a['allowN']} / 输入框 {a['inputs']}")
    ap_tx = pg.locator("#chip-approval-tx").inner_text()
    print("  chip 文案:", repr(ap_tx))
    pg.locator("#approval-panel").screenshot(path=r"D:/MatLens/_ui_approval_panel.png")

    print("\n=== 审批开关真实生效 ===")
    # 打开审批 + 选confirm_list，验证 API 真的落库
    pg.locator("#approval-toggle").click(); pg.wait_for_timeout(1200)
    pg.locator('.stc[data-str="confirm_list"]').click(); pg.wait_for_timeout(1500)
    import json, urllib.request
    d = json.loads(urllib.request.urlopen("http://127.0.0.1:7896/api/settings", timeout=20).read())
    ap = d.get("approval", {})
    print("  后端 enabled=", ap.get("enabled"), " strategy=", ap.get("strategy"))
    print("  警告条已消失:", pg.evaluate("()=>getComputedStyle(document.getElementById('approval-warn')).display")=="none")
    print("  chip 文案:", repr(pg.locator("#chip-approval-tx").inner_text()))
    # 复原
    pg.locator("#approval-toggle").click(); pg.wait_for_timeout(1200)
    b.close()
print("\nconsole:", [e for e in errs if "ERR_" not in e][:5] or "无")
