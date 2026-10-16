# -*- coding: utf-8 -*-
"""会话归档 + 添加工作区 真实交互验证。"""
import os, sys, json, urllib.request
sys.path.insert(0, r"D:/MatLens"); os.chdir(r"D:/MatLens")
from playwright.sync_api import sync_playwright
def api(p):
    return json.loads(urllib.request.urlopen("http://127.0.0.1:7896"+p, timeout=20).read())
errs=[]
with sync_playwright() as pw:
    b = pw.chromium.launch(headless=True)
    pg = b.new_context(viewport={"width":1700,"height":1000}).new_page()
    pg.on("console", lambda m: errs.append(f"[{m.type}] {m.text}") if m.type=="error" and "favicon" not in m.text else None)
    pg.on("pageerror", lambda e: errs.append(f"[pageerror] {e}"))
    pg.on("dialog", lambda d: d.accept("D:/MatLens/skills"))
    pg.goto("http://127.0.0.1:7896/?t=A102", wait_until="domcontentloaded", timeout=60000)
    pg.wait_for_timeout(4500)

    print("=== 添加工作区（prompt 自动接受 D:/MatLens/skills）===")
    pg.locator("#chip-ws").click(); pg.wait_for_timeout(1300)
    pg.locator("#ws-add-btn").click(); pg.wait_for_timeout(1800)
    ws = api("/api/workspaces")
    print("  后端 count=", ws["count"], " current=", ws["current"])
    print("  chip 文案:", repr(pg.locator("#chip-ws-name").inner_text()))
    print("  chip title:", pg.locator("#chip-ws").get_attribute("title"))
    m = pg.evaluate("""()=>{const e=document.getElementById('ws-panel');
      return {rows:e.querySelectorAll('.ws-row').length,
              active:e.querySelectorAll('.ws-row.active').length,
              path:(e.querySelector('.ws-path')||{}).textContent||'',
              del:!!e.querySelector('[data-delws]')};}""")
    print("  面板:行数=",m["rows"]," 高亮=",m["active"]," 路径=",m["path"][:38]," 删除钮=",m["del"])
    pg.locator("#ws-panel").screenshot(path=r"D:/MatLens/_ui_ws_panel.png")

    print("\n=== 归档一条会话 ===")
    before = api("/api/sessions")["count"]
    arch_before = api("/api/sessions/archived")["count"]
    print("  归档前: 历史=",before," 归档箱=",arch_before)
    pg.locator(".ws-arch").first.click(); pg.wait_for_timeout(1800)
    after = api("/api/sessions")["count"]
    arch_after = api("/api/sessions/archived")["count"]
    print("  归档后: 历史=",after," 归档箱=",arch_after, " 变化:", before-after, "/", arch_after-arch_before)
    # 恢复
    pg.locator(".ws-unarch").first.click(); pg.wait_for_timeout(1800)
    print("  恢复后: 历史=",api("/api/sessions")["count"]," 归档箱=",api("/api/sessions/archived")["count"])

    print("\n=== 删除工作区条目 ===")
    pg.locator(".ws-del").first.click(); pg.wait_for_timeout(1600)
    ws2 = api("/api/workspaces")
    print("  删除后 count=", ws2["count"], " 磁盘目录仍在=", os.path.isdir("D:/MatLens/skills"))
    b.close()
print("\nconsole:", [e for e in errs if "ERR_" not in e][:4] or "无")
