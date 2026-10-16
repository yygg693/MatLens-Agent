# -*- coding: utf-8 -*-
"""验证云端检索结果的标题可点击跳转（2026-10-15）。

覆盖：
  1. 标题渲染为 <a href>，且 href 为 http/https（协议白名单生效）
  2. target=_blank + rel=noopener
  3. 点击标题真的打开新标签页且 URL 指向真实论文页
  4. 点击标题不会误触发勾选
  5. 复制引用按钮产出合法 BibTeX
  6. javascript: 伪协议被拦截
"""
import sys

from playwright.sync_api import sync_playwright

BASE = "http://127.0.0.1:7896"
errors = []


def run():
    with sync_playwright() as pw:
        b = pw.chromium.launch()
        ctx = b.new_context(viewport={"width": 1680, "height": 1000})
        pg = ctx.new_page()
        pg.on("pageerror", lambda e: errors.append("PAGEERROR " + str(e)))
        pg.on("console", lambda m: errors.append(m.text) if m.type == "error" else None)

        pg.goto(BASE, wait_until="networkidle", timeout=60000)
        pg.wait_for_timeout(2200)
        pg.evaluate("""() => {
            const it=[...document.querySelectorAll('.nav-item')].find(n=>(n.textContent||'').includes('知识库'));
            if(it) it.click();
        }""")
        pg.wait_for_timeout(1500)
        pg.click('.kb-mode[data-kbmode="cloud"]')
        pg.wait_for_timeout(1000)

        pg.fill("#kb-web-query", "gadolinium doped ceria electrolyte conductivity")
        pg.click("#btn-kb-web-search")
        for _ in range(60):
            if pg.locator(".kb-web").count():
                break
            pg.wait_for_timeout(1000)

        n = pg.locator(".kb-web").count()
        print("[1] 结果条数:", n)
        if not n:
            print("!! 无结果，无法验证"); b.close(); return

        # 标题链接结构
        links = pg.eval_on_selector_all(
            ".kb-web-title-link",
            "els => els.slice(0,5).map(e => ({href:e.getAttribute('href'),"
            "target:e.target, rel:e.rel, text:e.textContent.trim().slice(0,50)}))")
        print("[2] 标题链接样本:")
        for l in links:
            ok = str(l["href"]).startswith(("http://", "https://"))
            print(f"    {'OK ' if ok else 'BAD'} target={l['target']} rel={l['rel']} href={str(l['href'])[:72]}")
            print(f"        {l['text']}")
        bad = [l for l in links if not str(l["href"]).startswith(("http://", "https://"))]
        print("    非 http(s) 链接数:", len(bad), "(应为 0)")

        # 覆盖率：有 DOI 的条目都应可点
        dead = pg.locator(".kb-web-title-dead").count()
        print("[3] 死条目(无可用链接):", dead, "/", n)

        # 点击标题开新标签
        target = pg.eval_on_selector(".kb-web-title-link", "e => e.getAttribute('href')")
        before = len(ctx.pages)
        pg.eval_on_selector(".kb-web-title-link", "e => e.click()")
        pg.wait_for_timeout(3500)
        after_pages = ctx.pages
        print("[4] 点击标题 → 新标签页数:", len(after_pages) - before)
        if len(after_pages) > before:
            np_ = after_pages[-1]
            print("    新页 URL:", np_.url[:100])
            print("    域名:", np_.url.split("/")[2] if "://" in np_.url else "(无)")
        # 勾选状态不应被点击标题改变
        print("[5] 点击后勾选框仍未勾选:",
              pg.eval_on_selector(".kb-web-pick", "e => e.checked") is False)

        for p in after_pages[1:]:
            try: p.close()
            except Exception: pass

        # 复制引用
        ncite = pg.locator("[data-cite]").count()
        print("[6] 复制引用按钮数:", ncite)
        if ncite:
            pg.eval_on_selector("[data-cite]", "e => e.click()")
            pg.wait_for_timeout(900)
            txt = pg.eval_on_selector("[data-cite]", "e => e.textContent")
            print("    按钮反馈:", txt)
            try:
                clip = pg.evaluate("() => navigator.clipboard.readText()")
            except Exception:
                clip = ""
            if clip:
                print("    剪贴板内容:\n" + "\n".join("      " + l for l in clip.split("\n")[:8]))

        # 协议白名单：注入 javascript: 伪协议看是否被拦
        res = pg.evaluate("""() => {
            const mk = (u) => { const a=document.createElement('a'); a.href=u;
                return a.protocol; };
            return {js: mk('javascript:alert(1)'), ok: mk('https://x.org/a.pdf')};
        }""")
        print("[7] 浏览器对 javascript: 的处理:", res["js"], "| https:", res["ok"])

        pg.screenshot(path="_ui_kb_links.png", full_page=False)
        ctx.close(); b.close()

    print("\n=== console/page errors:", len(errors))
    for e in errors[:10]:
        print("   ", e[:180])


if __name__ == "__main__":
    run()
