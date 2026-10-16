# -*- coding: utf-8 -*-
"""验证 stop() 移回 chat.js 后仍可用（发一条消息→点停止）。"""
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
    pg.wait_for_timeout(3500)
    pg.fill("#input", "你好，测试停止功能")
    pg.keyboard.press("Enter")
    pg.wait_for_timeout(3000)
    streaming = pg.evaluate("() => !!(window.ML && document.querySelector('#btn-stop'))")
    st = pg.evaluate("() => (document.querySelector('#chat-status')||{}).textContent||''")
    print("[发送] 流式进行中:", streaming, " 状态:", st.strip()[:24])
    # 停止按钮
    btn = pg.locator("#btn-stop")
    if btn.count() > 0 and btn.is_visible():
        btn.click(); pg.wait_for_timeout(1500)
        print("[停止] 已点击")
    # 或用键盘/全局
    stopped = pg.evaluate("() => !!(window.ML && window.ML.stop)")
    print("[暴露] window.ML.stop =", stopped)
    st2 = pg.evaluate("() => (document.querySelector('#chat-status')||{}).textContent||''")
    print("[停止后] 状态:", st2.strip()[:24])
    print("[停止后] 有回答内容:", pg.locator(".msg.agent").count()>0)
    pg.screenshot(path=r"D:/MatLens/_ui_stop_test.png")
    b.close()
print("console:", [e for e in errs if "ERR_CONNECTION" not in e][:4] or "无")
