# -*- coding: utf-8 -*-
"""完整跑一轮对话不打断：验证 SSE 事件分发全链路。"""
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
    pg.fill("#input", "用一句话介绍 MatLens 是什么")
    pg.keyboard.press("Enter")
    # 等最长 120s 或状态回"就绪"
    for i in range(60):
        pg.wait_for_timeout(2000)
        st = pg.evaluate("() => ((document.querySelector('#chat-status')||{}).textContent||'').trim()")
        if i % 5 == 0: print(f"  t={i*2}s 状态: {st[:20]}")
        if st == "就绪" and i > 2: break
    st = pg.evaluate("() => ((document.querySelector('#chat-status')||{}).textContent||'').trim()")
    n_msgs = pg.locator(".msg.agent").count()
    txt = pg.evaluate("() => {const e=document.querySelector('.msg.agent .rf-text, .msg.agent .bubble'); return e? e.textContent.trim().slice(0,90):''}")
    print(f"[完成] 状态={st} agent 消息数={n_msgs}")
    print(f"[回答] {txt}")
    print(f"[渲染] 思考卡={pg.locator('.think-block').count()} 记忆卡={pg.locator('.recall-block').count()} "
          f"工具卡={pg.locator('.tool-card,.run-step').count()} 计划卡={pg.locator('.plan-track').count()}")
    pg.screenshot(path=r"D:/MatLens/_ui_full_turn.png")
    b.close()
print("console:", [e for e in errs if "ERR_CONNECTION" not in e][:4] or "无")
