# -*- coding: utf-8 -*-
"""源健康面板端到端验证（2026-10-29）。"""
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

        pg.goto(BASE, wait_until="networkidle", timeout=60000)
        pg.wait_for_timeout(3000)

        pg.evaluate("""() => {
            const n = [...document.querySelectorAll('.nav-item')]
              .find(x => (x.textContent||'').includes('知识库'));
            if (n) n.click();
        }""")
        pg.wait_for_timeout(2000)

        print("[1] 面板存在:", pg.is_visible("#kb-health"))
        # 首屏读的是后端缓存（可能还没探测过），给点时间
        pg.wait_for_timeout(3000)
        st = pg.evaluate("""()=>{const h=document.getElementById('kb-health');
          return {head:(h?.querySelector('.kb-health-head')?.textContent||'').replace(/\\s+/g,' ').trim().slice(0,90),
            rows:h?.querySelectorAll('.kb-hl').length||0,
            badges:[...h.querySelectorAll('.kb-hs')].map(x=>x.textContent.trim())};}""")
        print("[2] 面板内容:", st["head"])
        print("    徽标:", st["badges"])
        print("    条目数:", st["rows"])

        # 点「立即检测」强制刷新
        btn = pg.locator("#btn-health-refresh")
        if btn.count():
            print("\n[3] 点「立即检测」…")
            btn.click()
            pg.wait_for_timeout(20000)
            st2 = pg.evaluate("""()=>{const h=document.getElementById('kb-health');
              const rows=[...h.querySelectorAll('.kb-hl')].slice(0,12).map(r=>({
                dot:r.querySelector('.kb-src-dot')?.className.replace('kb-src-dot ',''),
                name:r.querySelector('.kb-hl-name')?.textContent,
                msg:r.querySelector('.kb-hl-msg')?.textContent?.trim().slice(0,44),
                ms:r.querySelector('.kb-hl-ms')?.textContent}));
              return {rows, badges:[...h.querySelectorAll('.kb-hs')].map(x=>x.textContent.trim()),
                time:(h.querySelector('.kb-health-time')?.textContent||'')};}""")
            print("    徽标:", st2["badges"], "| 时间:", st2["time"])
            for r in st2["rows"]:
                print(f"      {r['dot']:<10} {str(r['name']):<22} {str(r['ms']):>7} {str(r['msg'])[:44]}")
            pg.screenshot(path="_ui_health.png")

        # 左栏圆点是否同步
        dots = pg.evaluate("""()=>[...document.querySelectorAll('[data-dot]')].slice(0,10)
          .map(d=>({id:d.dataset.dot, cls:d.className.replace('kb-src-dot','').trim(),
                    tip:(d.title||'').slice(0,44)}))""")
        print("\n[4] 左栏圆点同步:")
        for d in dots:
            print(f"      {d['id']:<20} {d['cls']:<10} {d['tip']}")

        b.close()

    print("\n=== errors:", len(errs))
    for e in errs[:8]:
        print("   ", e[:170])


if __name__ == "__main__":
    main()