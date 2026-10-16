# -*- coding: utf-8 -*-
"""拆分后回归：验证零行为变化 + 面板功能正常。"""
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
    # 模块是否都加载
    mods = pg.evaluate("() => Object.keys(window.ML||{}).length")
    print("[拆分] window.ML 键数:", mods)
    # 面板功能：点模型 chip 应打开面板
    pg.locator("#chip-model").click(); pg.wait_for_timeout(900)
    m1 = pg.evaluate("() => {const e=document.querySelector('#model-panel'); return e? getComputedStyle(e).display:'missing';}")
    print("[面板] 模型面板 display =", m1)
    pg.keyboard.press("Escape"); pg.wait_for_timeout(600)
    # 上下文面板
    pg.locator("#chip-context").click(); pg.wait_for_timeout(900)
    m2 = pg.evaluate("() => {const e=document.querySelector('#context-panel'); return e? getComputedStyle(e).display:'missing';}")
    print("[面板] 上下文面板 display =", m2)
    pg.locator("#chat-title").click(); pg.wait_for_timeout(500)
    # 其他页面仍正常
    for nav,label in [("kb","kb"),("tools","tools"),("paper","paper")]:
        pg.locator(f'.nav-item[data-page="{nav}"]').click(); pg.wait_for_timeout(1800)
    back = pg.locator('.nav-item[data-page="chat"]').click(); pg.wait_for_timeout(1200)
    # 引导卡仍在
    print("[引导卡] 存在:", pg.locator(".empty-hero").count()>0)
    pg.screenshot(path=r"D:/MatLens/_ui_after_split.png")
    b.close()
print("console:", [e for e in errs if "ERR_CONNECTION" not in e][:6] or "无")
