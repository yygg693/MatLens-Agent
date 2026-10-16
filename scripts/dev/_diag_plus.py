# -*- coding: utf-8 -*-
"""精确验证加号菜单 5 项的实际效果（用各自真实的目标元素判定）。"""
import sys

from playwright.sync_api import sync_playwright

BASE = "http://127.0.0.1:7896"

# 每项动作的「正确结果特征」
PROBE = """(action) => {
  const q = s => document.querySelector(s);
  const vis = s => { const e=q(s); if(!e) return null;
    const r=e.getBoundingClientRect(); const st=getComputedStyle(e);
    return (st.display!=='none'&&st.visibility!=='hidden'&&
            (e.classList.contains('show')||r.width>0)); };
  return {
    menuClosed: (document.getElementById('add-menu')||{style:{display:'x'}}).style.display==='none',
    toolCatalog: vis('#tool-cat-mask'),
    toolItems: (document.getElementById('tc-body')||{children:[]}).children.length,
    rightPanel: !!q('.chat-right') && (q('.chat-right').offsetWidth>0),
    rightTab: [...document.querySelectorAll('.rp-tab.active,.right-tab.active')].map(e=>e.textContent.trim())[0]||'',
    kbPage: !!document.getElementById('page-kb.active'),
    fileDialog: 'fileDialog',
    fileInputExists: !!document.getElementById('file-input'),
    toast: [...document.querySelectorAll('.toast-item')].map(t=>t.textContent.trim().slice(0,54)).slice(-1)[0]||'',
  };
}"""

EXPECT = {
    "file":       "打开系统文件选择器（file-input 被点击）",
    "screenshot": "截图（无屏或被拒时应给 toast 说明）",
    "kb":         "跳到知识库页并填好检索词",
    "memory":     "右侧栏切到「记忆」页签",
    "tools":      "弹出工具目录抽屉",
}


def main():
    with sync_playwright() as pw:
        b = pw.chromium.launch()
        ctx = b.new_context(viewport={"width": 1680, "height": 1000})
        pg = ctx.new_page()
        errs = []
        pg.on("pageerror", lambda e: errs.append("PAGEERROR " + str(e)))
        pg.on("console", lambda m: errs.append(m.text) if m.type == "error" else None)

        for action, desc in EXPECT.items():
            pg.goto(BASE, wait_until="networkidle", timeout=60000)
            pg.wait_for_timeout(2600)
            pg.click("#btn-add")
            pg.wait_for_timeout(600)
            pg.locator(f'.am-item[data-action="{action}"]').click(timeout=5000)
            pg.wait_for_timeout(2600)
            r = pg.evaluate(PROBE, action)
            print(f"── {action}  期望：{desc}")
            print(f"   菜单已关={r['menuClosed']}  工具目录={r['toolCatalog']}({r['toolItems']}项) "
                  f"知识库页={r['kbPage']} 右侧栏={r['rightPanel']}")
            print(f"   右侧页签={r['rightTab']!r}  toast={r['toast']!r}")
            print()

        pg.screenshot(path="_ui_plus_probe.png")
        ctx.close()
        b.close()
        print("=== errors:", len(errs))
        for e in errs[:6]:
            print("   ", e[:160])


if __name__ == "__main__":
    main()