# -*- coding: utf-8 -*-
"""设置页「网络隐私」面板端到端验证（2026-10-15）。"""
import sys

from playwright.sync_api import sync_playwright

BASE = "http://127.0.0.1:7896"
errors = []


def run():
    with sync_playwright() as pw:
        b = pw.chromium.launch()
        pg = b.new_context(viewport={"width": 1680, "height": 1000}).new_page()
        pg.on("pageerror", lambda e: errors.append("PAGEERROR " + str(e)))
        pg.on("console", lambda m: errors.append(m.text) if m.type == "error" else None)

        pg.goto(BASE, wait_until="networkidle", timeout=60000)
        pg.wait_for_timeout(2500)

        # 打开设置 → 网络隐私
        pg.evaluate("""() => {
            const t=[...document.querySelectorAll('.nav-item, .side-item, [data-page]')]
              .find(n=>(n.textContent||'').trim()==='设置');
            if(t) t.click();
        }""")
        pg.wait_for_timeout(1200)
        if not pg.is_visible("#stng-nav"):
            pg.evaluate("()=>{const b=[...document.querySelectorAll('*')].find(x=>x.id==='btn-settings');if(b)b.click();}")
            pg.wait_for_timeout(1000)
        print("[1] 设置页可见:", pg.is_visible("#stng-nav"))

        np = pg.locator('.stng-nav-item[data-tab="network"]')
        print("[2] 网络隐私 nav 存在:", np.count() == 1)
        if np.count():
            np.click()
            pg.wait_for_timeout(9000)

        print("[3] 面板显示:", pg.is_visible('[data-pane="network"]'))
        st = pg.inner_text("#np-status-txt").strip()
        cls = pg.get_attribute("#np-status", "class") or ""
        print("    状态卡 class:", cls.strip())
        print("    状态文案:", st[:100])
        print("[4] IP 卡片:", pg.is_visible("#np-ip-row"),
              "| 直连:", pg.inner_text("#np-ip-direct").strip()[:18],
              "| 代理:", pg.inner_text("#np-ip-proxy").strip()[:18])
        print("[5] 代理地址框:", pg.input_value("#np-proxy-url")[:44])
        print("    Tor 控制端口:", pg.input_value("#np-tor-control")[:24])
        print("    轮换统计:", pg.inner_text("#np-rotstat").strip()[:88])
        bl = pg.inner_text("#np-blocked-list").strip()
        print("[6] 禁止名单:", bl.replace("\n", " ")[:110])

        # 点「立即换 IP」（Tor 未运行，应如实报错不假装成功）
        pg.click("#np-btn-rotate")
        pg.wait_for_timeout(4000)
        toast = pg.locator(".toast-item").last
        t = toast.inner_text().strip() if toast.count() else "(无 toast)"
        print("[7] 立即换 IP 结果:", t.replace("\n", " ")[:110])
        print("    轮换统计更新:", pg.inner_text("#np-rotstat").strip()[:88])

        # 测「测试连接」
        pg.click("#np-btn-check")
        pg.wait_for_timeout(9000)
        print("[8] 测试连接后状态:", pg.inner_text("#np-status-txt").strip()[:100])

        pg.screenshot(path="_ui_settings_network.png", full_page=False)
        b.close()

    print("\n=== console/page errors:", len(errors))
    for e in errors[:8]:
        print("   ", e[:170])


if __name__ == "__main__":
    run()
