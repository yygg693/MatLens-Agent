# -*- coding: utf-8 -*-
"""输入框增强最终验证（修正测试方法：直接设 value，避免 Enter 触发发送）。"""
import os, sys
sys.path.insert(0, r"D:/MatLens"); os.chdir(r"D:/MatLens")
from playwright.sync_api import sync_playwright
errs=[]
with sync_playwright() as pw:
    b = pw.chromium.launch(headless=True)
    pg = b.new_context(viewport={"width":1700,"height":1000}).new_page()
    pg.on("console", lambda m: errs.append(f"[{m.type}] {m.text}") if m.type=="error" and "favicon" not in m.text else None)
    pg.on("pageerror", lambda e: errs.append(f"[pageerror] {e}"))
    pg.goto("http://127.0.0.1:7896/", wait_until="domcontentloaded", timeout=60000)
    pg.wait_for_timeout(4200)

    # P0-1 自动增高：用 set_value + 派发 input（不经过 Enter）
    print("[P0-1] 自动增高（直接赋值方式）:")
    for n in (1,3,6,9):
        pg.evaluate("""(n)=>{
          const e=document.querySelector('#input');
          e.value=Array.from({length:n},(_,i)=>'这是第'+(i+1)+'行测试内容稍微长一点让它换行').join('\\n');
          e.dispatchEvent(new Event('input'));
        }""", n)
        pg.wait_for_timeout(350)
        m = pg.evaluate("""()=>{const e=document.querySelector('#input');
          return {h:Math.round(e.getBoundingClientRect().height), sh:e.scrollHeight,
                  atMax:e.closest('.input-box').classList.contains('at-max')};}""")
        print(f"   {n}行 → 高 {m['h']}px  scrollH={m['sh']}  封顶标记={m['atMax']}")

    # @ 选择器三类来源
    print("\n[P0-2] @ 选择器:")
    pg.evaluate("()=>{const e=document.querySelector('#input'); e.value=''; e.dispatchEvent(new Event('input'));}")
    pg.locator("#input").click()
    pg.keyboard.type("@", delay=80); pg.wait_for_timeout(900)
    total = pg.locator("#tp-list .tp-item").count()
    kinds = pg.evaluate("()=>[...new Set([...document.querySelectorAll('#tp-list .tp-item')].map(e=>e.dataset.kind))]")
    more = pg.locator(".tp-more").count()
    print(f"   @ → 显示 {total} 条，来源={kinds}，剩余提示={bool(more)}")
    for kw in ("论文","比容量","图"):
        pg.keyboard.press("Control+a"); pg.keyboard.type("@"+kw, delay=50); pg.wait_for_timeout(700)
        c = pg.locator("#tp-list .tp-item").count()
        f = pg.locator("#tp-list .tp-item").first.get_attribute("data-name") if c else "-"
        print(f"   @{kw} → {c} 条，首项={f}")

    # 键盘导航 + Enter 插入（不真发送：输入框已有内容时 Enter 仍会发送，故先 Esc 关面板验证插入）
    pg.keyboard.press("Control+a"); pg.keyboard.type("@XRD", delay=50); pg.wait_for_timeout(700)
    pg.keyboard.press("ArrowDown"); pg.wait_for_timeout(250)
    c1 = pg.evaluate("()=>{const e=document.querySelector('#tp-list .tp-item.tp-sel');return e?e.dataset.name:'-';}")
    pg.keyboard.press("ArrowDown"); pg.wait_for_timeout(250)
    c2 = pg.evaluate("()=>{const e=document.querySelector('#tp-list .tp-item.tp-sel');return e?e.dataset.name:'-';}")
    print(f"   ↓ 两次：{c1} → {c2}")

    # N3 草稿
    pg.evaluate("()=>{const e=document.querySelector('#input'); e.value='草稿XYZ'; e.dispatchEvent(new Event('input')); e.blur();}")
    pg.locator(".nav-item[data-page='tools']").click(); pg.wait_for_timeout(1000)
    pg.locator(".nav-item[data-page='chat']").click(); pg.wait_for_timeout(1400)
    v = pg.locator("#input").input_value()
    print(f"\n[N3] 草稿跨页恢复: {'✅' if '草稿XYZ' in v else '❌'}")

    pg.evaluate("()=>{const e=document.querySelector('#input'); e.value=''; e.dispatchEvent(new Event('input'));}")
    pg.locator("#input").click(); pg.keyboard.type("@论文", delay=50); pg.wait_for_timeout(800)
    pg.screenshot(path=r"D:/MatLens/_ui_input_fixed.png")
    b.close()
print("\nconsole:", [e for e in errs if "ERR_" not in e][:4] or "无")
