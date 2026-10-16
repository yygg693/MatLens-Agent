# -*- coding: utf-8 -*-
"""工具中心中文索引端到端验证。"""
import os, sys
sys.path.insert(0, r"D:/MatLens"); os.chdir(r"D:/MatLens")
from playwright.sync_api import sync_playwright

errs = []
with sync_playwright() as pw:
    b = pw.chromium.launch(headless=True)
    pg = b.new_page(viewport={"width": 1700, "height": 1100})
    pg.on("console", lambda m: errs.append(f"[{m.type}] {m.text}")
          if m.type == "error" and "favicon" not in m.text else None)
    pg.on("pageerror", lambda e: errs.append(f"[pageerror] {e}"))
    pg.goto("http://127.0.0.1:7896/", wait_until="domcontentloaded", timeout=60000)
    pg.wait_for_timeout(3000)
    pg.locator("text=工具中心").first.click(); pg.wait_for_timeout(3500)
    print("[1] 副标题:", pg.locator("#tool-subtitle").inner_text())

    # 进技能库
    pg.locator('#tool-tags .tag', has_text="全部技能").first.click()
    pg.wait_for_timeout(1500)
    print("[2] 技能卡片数:", pg.locator(".tool-tile").count())
    print("    前3个中文名:", [pg.locator(".tool-tile .tt-name").nth(i).inner_text()
                          for i in range(3)])
    pg.screenshot(path=r"D:/MatLens/_ui_skills_zh.png")

    # 中文搜索
    for kw in ["论文", "邮件", "图表"]:
        pg.fill("#tool-search", kw); pg.wait_for_timeout(800)
        n = pg.locator(".tool-tile").count()
        first = pg.locator(".tool-tile .tt-name").first.inner_text() if n else "-"
        print(f"[3] 搜「{kw}」→ {n} 条，首项: {first}")

    # 打开一个中文 skill 的详情
    pg.fill("#tool-search", "论文"); pg.wait_for_timeout(800)
    if pg.locator(".tool-tile").count() > 0:
        pg.locator(".tool-tile").first.click(); pg.wait_for_timeout(1200)
        shown = pg.locator("#tool-detail-mask.show").count() > 0
        title = pg.locator("#tw-body .tw-title").inner_text() if shown else ""
        tags = pg.locator("#tw-body .tw-tag").all_inner_texts() if shown else []
        print(f"[4] 抽屉={shown} 标题={title} 标签={tags}")
        pg.screenshot(path=r"D:/MatLens/_ui_skill_drawer_zh.png")
        pg.locator("#tw-close").click(); pg.wait_for_timeout(600)
    b.close()
print("console 错误:", [e for e in errs if "ERR_CONNECTION" not in e][:5] or "无")
