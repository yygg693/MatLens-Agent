# -*- coding: utf-8 -*-
"""对话界面增强端到端验证（A1/A2/A4/A5/A6/A8）。"""
import os, sys
sys.path.insert(0, r"D:/MatLens"); os.chdir(r"D:/MatLens")
from playwright.sync_api import sync_playwright

errs = []
with sync_playwright() as pw:
    b = pw.chromium.launch(headless=True)
    pg = b.new_page(viewport={"width": 1700, "height": 1000})
    pg.on("console", lambda m: errs.append(f"[{m.type}] {m.text}")
          if m.type == "error" and "favicon" not in m.text else None)
    pg.on("pageerror", lambda e: errs.append(f"[pageerror] {e}"))
    pg.goto("http://127.0.0.1:7896/", wait_until="domcontentloaded", timeout=60000)
    pg.wait_for_timeout(3500)

    # A4 引导卡
    hero = pg.locator(".empty-hero").count()
    starters = pg.locator(".st-card").count()
    caps = pg.locator(".cap-card").count()
    print(f"[A4] 引导卡={hero>0} 示例问题={starters} 能力卡={caps}")
    print("     标题:", pg.locator(".eh-title").inner_text() if hero else "-")
    pg.screenshot(path=r"D:/MatLens/_ui_empty_hero.png")

    # A1 行长
    w = pg.evaluate("""() => {
      const s = document.querySelector('#chat-stream');
      const c = s.querySelector('.empty-hero');
      const r = c ? c.getBoundingClientRect() : null;
      return {stream: Math.round(s.getBoundingClientRect().width),
              child: r ? Math.round(r.width) : null,
              childMax: c ? getComputedStyle(c).maxWidth : null};
    }""")
    print(f"[A1] 流宽={w['stream']} 子元素宽={w['child']} max-width={w['childMax']}")

    # A2 折叠
    before = pg.evaluate("() => Math.round(document.querySelector('.chat-main').getBoundingClientRect().width)")
    pg.locator("#chat-side-collapse").click(); pg.wait_for_timeout(900)
    after = pg.evaluate("() => Math.round(document.querySelector('.chat-main').getBoundingClientRect().width)")
    handle = pg.locator("#chat-side-handle").is_visible()
    print(f"[A2] 主区 {before} → {after}（+{after-before}）把手可见={handle}")
    pg.screenshot(path=r"D:/MatLens/_ui_side_collapsed.png")
    pg.locator("#chat-side-handle").click(); pg.wait_for_timeout(900)
    back = pg.evaluate("() => Math.round(document.querySelector('.chat-main').getBoundingClientRect().width)")
    print(f"[A2] 展开恢复 {back}（{back==before}）")

    # A5 状态图标
    st = pg.evaluate("""() => {const s=document.querySelector('#chat-status');
      return {html: s.innerHTML.slice(0,80), hasIcon: !!s.querySelector('.st-ic')};}""")
    print(f"[A5] 状态图标={st['hasIcon']} html={st['html'][:50]}")

    # A8 字数计数
    pg.fill("#input", "测试字数提示功能是否正常工作")
    pg.wait_for_timeout(600)
    cnt = pg.locator(".input-count")
    print(f"[A8] 字数提示存在={cnt.count()>0} 文本={cnt.inner_text() if cnt.count() else '-'}")

    b.close()
print("console 错误:", [e for e in errs if "ERR_CONNECTION" not in e][:5] or "无")
