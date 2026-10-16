# -*- coding: utf-8 -*-
"""知识库双模 UI 端到端验证（2026-10-15）。

覆盖：
  1. 知识库页渲染无 console 错误
  2. 本地库模式：库清单 + 存储信息
  3. 云端 API 模式：源目录（含知网如实说明）
  4. 云端检索 → 勾选 → 一键导入本地库
  5. 导入后本地文献数增加
"""
import json
import sys
import time

from playwright.sync_api import sync_playwright

BASE = "http://127.0.0.1:7896"
errors = []
logs = []


def run():
    with sync_playwright() as pw:
        b = pw.chromium.launch()
        pg = b.new_page(viewport={"width": 1680, "height": 1000})
        pg.on("console", lambda m: (
            errors.append(m.text) if m.type == "error" else logs.append(m.type + ":" + m.text)))
        pg.on("pageerror", lambda e: errors.append("PAGEERROR " + str(e)))

        pg.goto(BASE, wait_until="networkidle", timeout=60000)
        pg.wait_for_timeout(2500)

        # 进入知识库页
        pg.evaluate("""() => {
            const it=[...document.querySelectorAll('.nav-item')].find(n=>(n.textContent||'').includes('知识库'));
            if(it) it.click();
        }""")
        pg.wait_for_timeout(1800)
        print("[1] 知识库页可见:", pg.is_visible("#page-kb"))
        print("    模式切换器:", pg.is_visible(".kb-modes"),
              "| 本地徽标:", pg.inner_text("#km-local-n").strip(),
              "| 云端徽标:", pg.inner_text("#km-cloud-n").strip())

        # 本地模式
        n_local_items = pg.locator("#kb-list .kb-item").count()
        print("[2] 本地模式 · 库数量:", n_local_items)
        print("    存储信息:", (pg.inner_text("#kb-storeinfo").replace("\n", " ")[:110]
                                if pg.is_visible("#kb-storeinfo") else "(隐藏)"))

        # 云端模式
        pg.click('.kb-mode[data-kbmode="cloud"]')
        pg.wait_for_timeout(1200)
        srcs = pg.locator("#kb-list .kb-src").count()
        nas = pg.locator("#kb-list .kb-src-na").count()
        print("[3] 云端模式 · 源卡片:", srcs, "| 不可用源说明:", nas)
        if nas:
            print("    不可用首条:", pg.locator("#kb-list .kb-src-na").first.inner_text().replace("\n", " ")[:120])
        print("    云端检索框可见:", pg.is_visible("#kb-web-query"),
              "| 本地检索条隐藏:", not pg.is_visible("#page-kb .kb-searchbar:not(#kb-cloud-pane .kb-searchbar)"))

        # 云端检索
        before = pg.evaluate("() => (window.S && window.S.kb) ? (window.S.kb.docs||0) : -1")
        pg.fill("#kb-web-query", "gadolinium doped ceria ionic conductivity sintering")
        pg.click("#btn-kb-web-search")
        pg.wait_for_timeout(1200)
        for _ in range(60):
            if pg.locator(".kb-web").count() or pg.locator(".kb-empty-t").count():
                break
            pg.wait_for_timeout(1000)
        hits = pg.locator(".kb-web").count()
        stat = pg.inner_text("#kb-srcstat").replace("\n", " ")[:120]
        print("[4] 云端检索命中:", hits)
        print("    源状态条:", stat)
        if hits:
            print("    首条:", pg.locator(".kb-web").first.inner_text().replace("\n", " ")[:130])

            # 勾选前两条
            for i in range(min(2, hits)):
                pg.locator(".kb-web-pick").nth(i).click()
            pg.wait_for_timeout(600)
            print("    导入条可见:", pg.is_visible("#kb-importbar"),
                  "| 已选:", pg.inner_text("#kb-picked-n").strip(),
                  "| 目标库:", pg.inner_text("#kb-import-target").strip())

            pg.click("#btn-kb-web-import")
            for _ in range(40):
                if pg.locator(".kb-web").count() == 0:
                    break
                pg.wait_for_timeout(1000)
            print("[5] 导入后剩余结果行:", pg.locator(".kb-web").count())

        # 回到本地看文献数
        pg.click('.kb-mode[data-kbmode="local"]')
        pg.wait_for_timeout(2200)
        after = pg.inner_text("#doc-count").strip()
        print("[6] 本地文献计数:", after, "| (检索前 docs =", before, ")")

        pg.screenshot(path="_ui_kb_v2_local.png", full_page=False)
        pg.click('.kb-mode[data-kbmode="cloud"]')
        pg.wait_for_timeout(1200)
        pg.screenshot(path="_ui_kb_v2_cloud.png", full_page=False)
        b.close()

    print("\n=== console errors:", len(errors))
    for e in errors[:12]:
        print("   ", e[:200])


if __name__ == "__main__":
    run()
