# -*- coding: utf-8 -*-
"""验证：工作区面板只有工作区；归档在侧栏可用。"""
import os, sys, json, urllib.request
sys.path.insert(0, r"D:/MatLens"); os.chdir(r"D:/MatLens")
from playwright.sync_api import sync_playwright
def api(p): return json.loads(urllib.request.urlopen("http://127.0.0.1:7896"+p, timeout=20).read())
errs=[]
with sync_playwright() as pw:
    b = pw.chromium.launch(headless=True)
    pg = b.new_context(viewport={"width":1700,"height":1000}).new_page()
    pg.on("console", lambda m: errs.append(f"[{m.type}] {m.text}") if m.type=="error" and "favicon" not in m.text else None)
    pg.on("pageerror", lambda e: errs.append(f"[pageerror] {e}"))
    pg.goto("http://127.0.0.1:7896/?t=B201", wait_until="domcontentloaded", timeout=60000)
    pg.wait_for_timeout(4500)

    print("=== 工作区面板（应只有工作区）===")
    pg.locator("#chip-ws").click(); pg.wait_for_timeout(1400)
    m = pg.evaluate("""()=>{const e=document.getElementById('ws-panel');
      return {disp:getComputedStyle(e).display,
              secs:[...e.querySelectorAll('.cp-sec')].map(s=>s.querySelector('span').textContent),
              rows:e.querySelectorAll('.ws-row').length,
              sessionItems:e.querySelectorAll('.ws-item').length,
              empty:!!e.querySelector('.ws-empty'),
              addBtn:!!e.querySelector('#ws-add-btn')};}""")
    print("  面板:", m["disp"], " 分段:", m["secs"])
    print(f"  工作区行={m['rows']} 会话条目={m['sessionItems']} 空态={m['empty']} 添加钮={m['addBtn']}")
    assert m["sessionItems"]==0, "工作区面板不该有会话条目"
    pg.locator("#ws-panel").screenshot(path=r"D:/MatLens/_ui_ws_only.png")

    print("\n=== 侧栏归档 ===")
    print("  活跃 count:", api("/api/sessions")["count"], " 归档箱:", api("/api/sessions/archived")["count"])
    print("  列表头:", pg.evaluate("()=>document.querySelector('.s-group').innerText.replace(/\\n/g,' ')"))
    print("  切换钮:", pg.locator(".s-toggle").count()>0,
          " 归档钮/条:", pg.locator('[data-act="archive"]').count())
    # 归档一条
    # 真实用户路径：hover 到条目 → 归档钮显现 → 点击
    item0 = pg.locator(".session-item").first
    item0.hover(); pg.wait_for_timeout(600)
    pg.locator('[data-act="archive"]').first.click(); pg.wait_for_timeout(1800)
    print("  归档后→ 活跃:", api("/api/sessions")["count"], " 归档箱:", api("/api/sessions/archived")["count"])
    # 切到归档箱
    pg.locator(".s-toggle").click(); pg.wait_for_timeout(1600)
    print("  切到归档箱: 列表头=", pg.evaluate("()=>document.querySelector('.s-group').innerText.replace(/\\n/g,' ')") or "")
    print("  归档条目:", pg.locator(".session-item").count(),
          " 恢复钮:", pg.locator('[data-act="unarchive"]').count(),
          " 归档钮(应为0):", pg.locator('[data-act="archive"]').count())
    pg.locator(".side-sessions").screenshot(path=r"D:/MatLens/_ui_archive_box.png")
    # 恢复
    pg.locator(".session-item").first.hover(); pg.wait_for_timeout(600)
    pg.locator('[data-act="unarchive"]').first.click(); pg.wait_for_timeout(1800)
    print("  恢复后 归档箱:", api("/api/sessions/archived")["count"], " 活跃:", api("/api/sessions")["count"])
    # 切回
    pg.locator(".s-toggle").click(); pg.wait_for_timeout(1300)
    print("  切回: 列表头=", pg.evaluate("()=>document.querySelector('.s-group').innerText.replace(/\\n/g,' ')") or "")
    print("  活跃条目:", pg.locator(".session-item").count())
    b.close()
print("\nconsole:", [e for e in errs if "ERR_" not in e][:5] or "无")
