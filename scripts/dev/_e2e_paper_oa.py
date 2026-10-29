# -*- coding: utf-8 -*-
"""论文工坊检索步「找 OA 全文」端到端验证（2026-10-29）。"""
import sys

from playwright.sync_api import sync_playwright

BASE = "http://127.0.0.1:7896"
errs = []


def main():
    with sync_playwright() as pw:
        b = pw.chromium.launch()
        pg = b.new_context(viewport={"width": 1680, "height": 1000}).new_page()
        pg.on("pageerror", lambda e: errs.append("PAGEERROR " + str(e)))
        pg.on("console", lambda m: errs.append(m.text) if m.type == "error" else None)

        pg.goto(BASE, wait_until="domcontentloaded", timeout=90000)
        pg.wait_for_timeout(4500)

        pg.evaluate("""() => {
            const n = [...document.querySelectorAll('.nav-item')]
              .find(x => (x.textContent||'').includes('论文工坊'));
            if (n) n.click();
        }""")
        pg.wait_for_timeout(2500)

        # 选第一个课题
        picked = pg.evaluate("""() => {
            const items = [...document.querySelectorAll('#paper-list .paper-item, #paper-list > div')];
            if (!items.length) return false;
            items[0].click();
            return true;
        }""")
        print("[1] 选中课题:", picked)
        pg.wait_for_timeout(2500)

        # 切到检索步
        pg.evaluate("""() => {
            const sb = document.getElementById('stepbar');
            const t = [...sb.querySelectorAll('*')].find(e => (e.textContent||'').includes('文献检索'));
            if (t) t.click();
        }""")
        pg.wait_for_timeout(2200)

        st = pg.evaluate("""()=>{const c=document.querySelector('#panel-refs')||document.querySelector('.p-refs');
          return {exists:!!c, cards:document.querySelectorAll('.p-ref').length,
            btns:document.querySelectorAll('[data-oa-resolve]').length,
            head:(c?.querySelector('.p-refs-head')?.textContent||'').replace(/\\s+/g,' ').trim().slice(0,80),
            first:(document.querySelector('.p-ref-t')?.textContent||'').trim().slice(0,54),
            meta:(document.querySelector('.p-ref-m')?.textContent||'').replace(/\\s+/g,' ').trim().slice(0,74)};}""")
        print("[2] 文献卡片区:", st["exists"], "| 卡片", st["cards"], "| 按钮", st["btns"])
        print("    头部:", st["head"])
        print("    首条:", st["first"])
        print("    元信息:", st["meta"])
        pg.screenshot(path="_ui_paper_refs.png")

        if st["btns"]:
            print("\n[3] 点「找 OA 全文」…")
            btn = pg.locator("[data-oa-resolve]").first
            btn.click()
            pg.wait_for_timeout(22000)
            res = pg.evaluate("""()=>{const m=document.querySelector('.p-ref-msg');
              return {cls:m?.className||'', txt:(m?.textContent||'').trim().slice(0,110),
                btn:(document.querySelector('[data-oa-resolve]')?.textContent||'').trim(),
                have:document.querySelector('.p-ref-have')?.textContent?.trim()||''};}""")
            print("    消息:", res["cls"], "|", res["txt"])
            print("    按钮:", res["btn"], "| 标记:", res["have"])
            pg.screenshot(path="_ui_paper_oa.png")

        b.close()

    print("\n=== errors:", len(errs))
    for e in errs[:8]:
        print("   ", e[:170])


if __name__ == "__main__":
    main()