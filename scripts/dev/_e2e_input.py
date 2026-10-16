# -*- coding: utf-8 -*-
"""输入框增强验证：自动增高 / @ 并入skill / 键盘导航 / 草稿 / 历史。"""
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
    ta = pg.locator("#input")

    # P0-1 自动增高
    print("[P0-1] 自动增高:")
    for n in (1,3,5,8):
        ta.click()
        pg.keyboard.press("Control+a"); pg.keyboard.press("Delete")
        txt = "\n".join("这是第%d行测试内容稍微长一点让它换行" % k for k in range(1,n+1))
        ta.type(txt, delay=1)
        pg.wait_for_timeout(300)
        h = ta.evaluate("e => Math.round(e.getBoundingClientRect().height)")
        print(f"   {n}行 → {h}px")

    # P0-2 @ 并入 skill
    print("\n[P0-2] @ 选择器:")
    ta.click(); pg.keyboard.press("Control+a"); pg.keyboard.press("Delete")
    ta.type("@", delay=80); pg.wait_for_timeout(900)
    total = pg.locator("#tp-list .tp-item").count()
    kinds = pg.evaluate("()=>[...new Set([...document.querySelectorAll('#tp-list .tp-item')].map(e=>e.dataset.kind))]")
    print(f"   @ 全部 → {total} 条，来源类型={kinds}")
    for kw in ("论文","XRD","比容量"):
        pg.keyboard.press("Control+a"); pg.keyboard.press("Delete")
        ta.type("@"+kw, delay=60); pg.wait_for_timeout(700)
        c = pg.locator("#tp-list .tp-item").count()
        first = pg.locator("#tp-list .tp-item").first.inner_text().replace(chr(10)," / ")[:44] if c else "-"
        more = pg.locator(".tp-more").count()
        print(f"   @{kw} → {c} 条{'（有剩余提示）' if more else ''}  首项: {first}")

    # 键盘导航
    pg.keyboard.press("Control+a"); pg.keyboard.press("Delete")
    ta.type("@XRD", delay=60); pg.wait_for_timeout(700)
    pg.keyboard.press("ArrowDown"); pg.wait_for_timeout(300)
    cur = pg.evaluate("()=>{const e=document.querySelector('#tp-list .tp-item.cursor');return e?e.dataset.name:'-';}")
    print(f"   ↓ 键光标落在: {cur}")
    pg.keyboard.press("Enter"); pg.wait_for_timeout(600)
    print(f"   Enter 插入后输入框值: {ta.input_value()[:52]}")

    # N3 草稿
    ta.fill("这是一段未发送的草稿内容")
    pg.locator(".nav-item[data-page='tools']").click(); pg.wait_for_timeout(1200)
    pg.locator(".nav-item[data-page='chat']").click(); pg.wait_for_timeout(1200)
    restored = ta.input_value()
    print(f"\n[N3] 草稿恢复: {'✅ 成功' if '草稿' in restored else '❌ 丢失'}（值长度 {len(restored)}）")

    # N4 历史
    pg.evaluate("()=>{const e=document.querySelector('#input'); e.value='历史测试问题A'; e.dispatchEvent(new Event('input'));}")
    pg.keyboard.press("Control+a"); pg.keyboard.press("Delete")
    ta.type("↑", delay=80) if False else None
    pg.wait_for_timeout(400)
    pg.screenshot(path=r"D:/MatLens/_ui_input_fixed.png")
    b.close()
print("\nconsole:", [e for e in errs if "ERR_CONNECTION" not in e][:5] or "无")
