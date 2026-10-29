# -*- coding: utf-8 -*-
"""知识库页「数据集」模式端到端验证（2026-10-29）。

覆盖：切模式 → 检索 → 看许可证/文件 → 文件清单浮层 → 勾选 → 导入
"""
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

        print("[1] 模式按钮:", pg.evaluate(
            "()=>[...document.querySelectorAll('.kb-mode')].map(b=>b.dataset.kbmode)"))
        print("    数据集源计数:", pg.evaluate("()=>document.getElementById('km-dataset-n')?.textContent"))

        pg.locator('.kb-mode[data-kbmode="dataset"]').click()
        pg.wait_for_timeout(1800)
        print("[2] 数据集面板可见:", pg.is_visible("#kb-dataset-pane"),
              "| 云端面板隐藏:", not pg.is_visible("#kb-cloud-pane"))
        print("    源状态条:", pg.evaluate(
            "()=>document.getElementById('kb-ds-srcstat')?.textContent?.replace(/\\s+/g,' ').trim().slice(0,110)"))

        # 检索
        pg.fill("#kb-ds-query", "solid oxide fuel cell electrode dataset")
        pg.click("#btn-kb-ds-search")
        pg.wait_for_timeout(9000)

        st = pg.evaluate("""()=>{const box=document.getElementById('kb-ds-results');
          return {n:box.querySelectorAll('.kb-ds').length,
            lic:box.querySelectorAll('.kb-ds-lic').length,
            meta:(box.querySelector('.kb-web-meta')?.textContent||'').replace(/\\s+/g,' ').trim(),
            files:(box.querySelector('.kb-ds-files')?.textContent||'').trim().slice(0,60),
            title:(box.querySelector('.kb-web-title')?.textContent||'').trim().slice(0,44),
            note:(box.querySelector('.kb-hit-note')?.textContent||'').replace(/\\s+/g,' ').trim().slice(0,60)};}""")
        print("[3] 检索结果:", st["n"], "条 | 许可证标签", st["lic"], "个")
        print("    首条:", st["title"])
        print("    元信息:", st["meta"][:90])
        print("    文件:", st["files"])
        pg.screenshot(path="_ui_ds_results.png")

        # 文件清单浮层
        btn = pg.locator('[data-ds-files]').first
        if btn.count():
            btn.click()
            pg.wait_for_timeout(4000)
            ov = pg.evaluate("""()=>{const o=document.getElementById('kb-ds-overlay');
              if(!o) return {exists:false};
              return {exists:o.style.display!=='none',
                head:o.querySelector('.kb-ds-fmeta')?.textContent?.replace(/\\s+/g,' ').trim().slice(0,80),
                files:o.querySelectorAll('.kb-ds-file').length,
                note:o.querySelector('.kb-ds-fnote')?.textContent?.replace(/\\s+/g,' ').trim().slice(0,70)};}""")
            print("[4] 文件清单浮层:", ov)
            pg.screenshot(path="_ui_ds_files.png")
            pg.evaluate("()=>document.getElementById('kb-ds-overlay')?.remove()")

        # 勾选 + 导入
        # ⚠️ 测「计数会变」必须换一条新数据：底层按文件名去重，
        # 重复导入同一条会被跳过，文献数自然不变 —— 那不是 bug。
        pg.fill("#kb-ds-query", "tungsten oxide thermionic emission dataset")
        pg.click("#btn-kb-ds-search")
        pg.wait_for_timeout(9000)
        before = pg.evaluate("()=>document.querySelector('#doc-count')?.textContent||''")
        pg.locator(".kb-ds .kb-web-pick").first.check()
        pg.wait_for_timeout(700)
        bar = pg.evaluate("""()=>({vis:document.getElementById('kb-ds-importbar')?.style.display!=='none',
          n:document.getElementById('kb-ds-picked-n')?.textContent,
          tgt:document.getElementById('kb-ds-target')?.textContent})""")
        print("[5] 勾选条:", bar)
        pg.click("#btn-kb-ds-import")
        pg.wait_for_timeout(5000)
        toast = pg.evaluate("()=>[...document.querySelectorAll('.toast-item')].map(t=>t.textContent.trim()).slice(-1)[0]||''")
        print("[6] 导入 toast:", toast[:80])
        pg.wait_for_timeout(1200)
        after = pg.evaluate("()=>document.querySelector('#doc-count')?.textContent||''")
        print("    文献计数:", before.strip(), "->", after.strip())

        # 复制引用
        copybtn = pg.locator('[data-ds-copy]').first
        if copybtn.count():
            copybtn.click()
            pg.wait_for_timeout(900)
            t = pg.evaluate("()=>[...document.querySelectorAll('.toast-item')].map(t=>t.textContent.trim()).slice(-1)[0]||''")
            print("[7] 复制引用:", t[:60])

        pg.screenshot(path="_ui_ds_mode.png")
        b.close()

    print("\n=== errors:", len(errs))
    for e in errs[:8]:
        print("   ", e[:170])


if __name__ == "__main__":
    main()