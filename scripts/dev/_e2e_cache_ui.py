# -*- coding: utf-8 -*-
"""设置页「抓取缓存」统计区块端到端验证（2026-10-29）。"""
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

        # 进设置页 → 网络面板
        pg.evaluate("""() => {
            const n = [...document.querySelectorAll('.nav-item')]
              .find(x => (x.textContent||'').includes('设置'));
            if (n) n.click();
        }""")
        pg.wait_for_timeout(2200)
        pg.evaluate("""() => {
            const t = [...document.querySelectorAll('.stng-nav-item')]
              .find(x => (x.textContent||'').includes('网络'));
            if (t) t.click();
        }""")
        pg.wait_for_timeout(4000)

        st = pg.evaluate("""()=>{const b=document.getElementById('np-cache-stats');
          return {exists:!!b, vis:b?b.offsetHeight>0:false,
            txt:(b?.textContent||'').replace(/\\s+/g,' ').trim().slice(0,140),
            purgeBtn:!!document.getElementById('np-cache-purge'),
            hint:(document.getElementById('np-cache-hint')?.textContent||'').trim().slice(0,70)};}""")
        print("[1] 缓存统计区块:", st["exists"], "可见:", st["vis"])
        print("    内容:", st["txt"])
        print("    清理按钮:", st["purgeBtn"])
        print("    提示:", st["hint"])

        # 抓一次让它有数据
        pg.evaluate("""async () => {
            await fetch('/api/web/fetch', {method:'POST',
                headers:{'Content-Type':'application/json'},
                body: JSON.stringify({url:'https://example.com/settings-test'})});
        }""")
        pg.wait_for_timeout(3000)
        pg.click("#np-cache-refresh")
        pg.wait_for_timeout(2500)
        st2 = pg.evaluate("""()=>({txt:(document.getElementById('np-cache-stats')?.textContent||'')
            .replace(/\\s+/g,' ').trim().slice(0,160)})""")
        print("\n[2] 抓取后刷新统计:")
        print("   ", st2["txt"])

        # 清理
        pg.click("#np-cache-purge")
        pg.wait_for_timeout(2500)
        t = pg.evaluate("()=>[...document.querySelectorAll('.toast-item')].map(x=>x.textContent.trim()).slice(-1)[0]||''")
        print("\n[3] 清理 toast:", t[:80])

        pg.screenshot(path="_ui_cache_stats.png")
        b.close()

    print("\n=== errors:", len(errs))
    for e in errs[:6]:
        print("   ", e[:170])


if __name__ == "__main__":
    main()