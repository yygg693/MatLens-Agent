# -*- coding: utf-8 -*-
"""工具中心 UI 端到端验证：通用工具逐条展示 + 详情抽屉 + 技能库。"""
import json
import os
import sys

sys.path.insert(0, r"D:\MatLens")
os.chdir(r"D:\MatLens")

from playwright.sync_api import sync_playwright

BASE = "http://127.0.0.1:7896/"
OUT = r"D:\MatLens\_ui_tools.png"
errs = []

with sync_playwright() as pw:
    b = pw.chromium.launch(headless=True)
    pg = b.new_page(viewport={"width": 1700, "height": 1100})
    pg.on("console", lambda m: errs.append(f"[{m.type}] {m.text}")
          if m.type == "error" and "favicon" not in m.text else None)
    pg.on("pageerror", lambda e: errs.append(f"[pageerror] {e}"))

    pg.goto(BASE, wait_until="domcontentloaded", timeout=60000)
    pg.wait_for_timeout(3000)

    # 进工具中心
    pg.locator("text=工具中心").first.click()
    pg.wait_for_timeout(3500)

    sub = pg.locator("#tool-subtitle").inner_text()
    tiles = pg.locator(".tool-tile").count()
    tags = pg.locator("#tool-tags .tag").count()
    print("[1] 副标题:", sub)
    print("[2] 默认卡片数:", tiles, " 分类标签数:", tags)

    # 分类筛选：切到「技能」
    skill_tag = pg.locator('#tool-tags .tag', has_text="全部技能")
    if skill_tag.count() > 0:
        skill_tag.first.click()
        pg.wait_for_timeout(1200)
        print("[3] 技能库卡片数:", pg.locator(".tool-tile").count())
        pg.screenshot(path=OUT, full_page=False)
        # 搜一个具体 skill
        pg.fill("#tool-search", "data")
        pg.wait_for_timeout(900)
        print("[4] 搜索 data 命中:", pg.locator(".tool-tile").count())
        pg.screenshot(path=OUT, full_page=False)
        pg.fill("#tool-search", "")
        pg.wait_for_timeout(700)
    else:
        print("[3] ⚠ 未找到「全部技能」标签")

    # 回全部，点开一个通用工具的详情抽屉
    pg.locator('#tool-tags .tag', has_text="全部").first.click()
    pg.wait_for_timeout(1000)
    # 找一个有参数的工具卡
    target = pg.locator('.tool-tile:has(.tt-badge)').first
    if target.count() == 0:
        target = pg.locator(".tool-tile").nth(5)
    tname = target.get_attribute("data-name")
    target.click()
    pg.wait_for_timeout(1200)
    drawer_shown = pg.locator("#tool-detail-mask.show").count() > 0
    title = pg.locator("#tw-body .tw-title").inner_text() if drawer_shown else ""
    nrows = pg.locator("#tw-body .tw-params tbody tr").count() if drawer_shown else 0
    nex = pg.locator("#tw-body .tw-ex").count() if drawer_shown else 0
    print(f"[5] 点开工具「{tname}」抽屉显示={drawer_shown} 标题={title}")
    print(f"    参数表行数={nrows}  示例块={nex}")
    pg.screenshot(path=OUT, full_page=False)

    # 关闭抽屉
    if drawer_shown:
        pg.locator("#tw-close").click()
        pg.wait_for_timeout(700)
        print("[6] 抽屉关闭:", pg.locator("#tool-detail-mask.show").count() == 0)

    # 「仅可用」开关
    av = pg.locator("#tool-avail")
    if av.count() > 0:
        before = pg.locator(".tool-tile").count()
        av.check()
        pg.wait_for_timeout(900)
        after = pg.locator(".tool-tile").count()
        print(f"[7] 仅可用过滤: {before} → {after}")
        pg.screenshot(path=OUT, full_page=False)

    b.close()

print("\nconsole 错误:", [e for e in errs if "ERR_CONNECTION" not in e][:6] or "无")
