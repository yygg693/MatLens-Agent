# -*- coding: utf-8 -*-
"""加号菜单 + 右栏重做验证。"""
import os, sys
sys.path.insert(0, r"D:\MatLens"); os.chdir(r"D:\MatLens")
from playwright.sync_api import sync_playwright

errs = []
with sync_playwright() as pw:
    b = pw.chromium.launch(headless=True)
    pg = b.new_context(viewport={"width": 1700, "height": 1000}).new_page()
    pg.on("console", lambda m: errs.append(f"[{m.type}] {m.text}")
          if m.type == "error" and "favicon" not in m.text else None)
    pg.on("pageerror", lambda e: errs.append(f"[pageerror] {e}"))
    pg.goto("http://127.0.0.1:7896/?t=7702", wait_until="domcontentloaded", timeout=60000)
    pg.wait_for_timeout(4500)

    # ── 加号菜单 ──
    print("=== 加号菜单 ===")
    pg.locator("#btn-add").click()
    pg.wait_for_timeout(900)
    print("  显示:", pg.evaluate("()=>getComputedStyle(document.getElementById('add-menu')).display"))
    print("  分组数:", pg.locator("#add-menu .am-group").count())
    print("  菜单项:", pg.locator("#add-menu .am-item").count())
    acts = pg.evaluate(
        "()=>[...document.querySelectorAll('#add-menu .am-item')]"
        ".map(e=>e.dataset.action+(e.hasAttribute('disabled')?'(禁用)':''))")
    print("  action:", acts)
    print("  描述回填:", pg.evaluate(
        "()=>[...document.querySelectorAll('#add-menu .am-desc')].map(e=>e.textContent.trim())"))
    print("  emoji 残留:", pg.evaluate(
        "()=>[...document.querySelectorAll('#add-menu .am-ic')].filter(e=>!e.querySelector('svg')).length"))

    # 点「工具与技能」应打开目录弹窗
    pg.locator('.am-item[data-action="tools"]').click()
    pg.wait_for_timeout(1300)
    print("  点「工具与技能」→ 目录弹窗:", pg.locator("#tool-cat-mask.show").count() > 0)
    if pg.locator("#tool-cat-mask.show").count() > 0:
        pg.locator("#tc-close").click()
        pg.wait_for_timeout(500)

    # 点「翻阅记忆」应切到右栏记忆 tab
    pg.locator("#btn-add").click(); pg.wait_for_timeout(700)
    pg.locator('.am-item[data-action="memory"]').click(); pg.wait_for_timeout(1200)
    print("  点「翻阅记忆」→ 右栏记忆 active:",
          pg.evaluate("()=>document.querySelector('.right-tab[data-tab=\"mem\"]').classList.contains('active')"))

    # ── 右栏四 tab ──
    print("")
    print("=== 右栏四 tab ===")
    for tab, label in [("mem", "记忆"), ("cite", "引用"), ("files", "文件"), ("tl", "时间线")]:
        pg.locator('.right-tab[data-tab="%s"]' % tab).click()
        pg.wait_for_timeout(1200)
        info = pg.evaluate("""(t)=>{const e=document.getElementById('right-'+t);
            return {d:getComputedStyle(e).display, items:e.querySelectorAll('.rm-item').length,
                    empty:e.querySelectorAll('.rm-empty').length,
                    txt:e.innerText.replace(/\\n+/g,' | ').trim().slice(0,80)};}""", tab)
        act = pg.evaluate("""(t)=>document.querySelector('.right-tab[data-tab="'+t+'"]')
                                .classList.contains('active')""", tab)
        print("  [%s] active=%s display=%s 条目=%d 空态=%d" % (label, act, info["d"], info["items"], info["empty"]))
        print("      %s" % info["txt"])

    m = pg.evaluate("""()=>{const it=document.querySelector('#right-mem .rm-item');
        if(!it) return null; const h=it.querySelector('.rm-head');
        return {cat:h.querySelector('.rm-cat')?.textContent,
                time:h.querySelector('.rm-time')?.textContent,
                hasDel:!!h.querySelector('.rm-del'), hasFull:!!it.dataset.full};}""")
    print("  记忆条细节:", m)

    # 截图（放最后，避免 document click 收起菜单）
    pg.locator("#btn-add").click(); pg.wait_for_timeout(800)
    pg.locator(".input-box-wrap").screenshot(path=r"D:\MatLens\_ui_addmenu_new.png")
    pg.keyboard.press("Escape"); pg.wait_for_timeout(400)
    for tab in ("mem", "cite", "tl"):
        pg.locator('.right-tab[data-tab="%s"]' % tab).click(); pg.wait_for_timeout(900)
        pg.locator(".chat-right").screenshot(path=r"D:\MatLens\_ui_right_%s.png" % tab)
    b.close()
print("")
print("console:", [e for e in errs if "ERR_" not in e][:5] or "无")
