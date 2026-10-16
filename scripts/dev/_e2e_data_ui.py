# -*- coding: utf-8 -*-
"""实验数据录入 UI 端到端验证 · 完整流程（真实浏览器点击）。"""
import json
import sys
from playwright.sync_api import sync_playwright

BASE = "http://127.0.0.1:7896/"
OUT = r"D:\MatLens\_e2e_data_ui.png"
errs = []
steps = []


def log(s):
    steps.append(s)
    print(s)


NOTES = "2026-10-14 在 SOFC 实验室 EIS 实测，950C，N2 气氛，重复 3 次取均值"
TABLES = json.dumps(
    [
        {
            "name": "Table 1",
            "caption": "LSM-LSCF 电导率随温度变化",
            "columns": ["温度/°C", "σ/ S·cm⁻¹"],
            "rows": [["800", "0.12"], ["850", "0.28"], ["900", "0.45"]],
        }
    ],
    ensure_ascii=False,
    indent=2,
)

with sync_playwright() as pw:
    b = pw.chromium.launch(headless=True)
    pg = b.new_page(viewport={"width": 1600, "height": 1100})
    pg.on("console", lambda m: errs.append(f"[{m.type}] {m.text}") if m.type == "error" else None)
    pg.on("pageerror", lambda e: errs.append(f"[pageerror] {e}"))

    pg.goto(BASE, wait_until="domcontentloaded", timeout=60000)
    pg.wait_for_timeout(3000)

    # 1) 进入论文工坊
    pg.locator("text=论文工坊").first.click()
    pg.wait_for_timeout(2000)
    log("[1] 进入论文工坊")

    # 2) 选中第一篇论文（SOFC）
    pg.locator("text=固态氧化物燃料电池电解质研究").first.click()
    pg.wait_for_timeout(2500)
    log("[2] 选中 SOFC 论文")

    # 3) 确保在 write 步（用步骤条 data-stage 精确定位，避免点到侧栏 tag）
    if pg.locator("#btn-p-data").count() == 0:
        pg.locator(".step[data-stage='write']").first.click()
        pg.wait_for_timeout(2500)
        log("[3] 切到写作步")
    else:
        log("[3] 已在写作步")

    # 4) 展开实验数据面板
    assert pg.locator("#btn-p-data").count() > 0, "未找到实验数据按钮"
    log("    按钮文案: " + pg.locator("#btn-p-data").first.inner_text().replace("\n", " "))
    pg.locator("#btn-p-data").first.click()
    pg.wait_for_timeout(1200)
    assert pg.locator("#p-data-panel").count() > 0, "面板未展开"
    log("[4] 实验数据面板已展开")

    # 5) 选「实测数据」+ 填内容
    pg.locator("input[name='p-data-status'][value='measured']").first.check()
    pg.locator("#p-data-notes").first.fill(NOTES)
    pg.locator("#p-data-tables").first.fill(TABLES)
    log("[5] 填入 measured + notes + tables")
    pg.screenshot(path=OUT, full_page=True)

    # 6) 保存
    pg.locator("#btn-p-data-save").first.click()
    pg.wait_for_timeout(3000)
    log("[6] 点击保存")
    pg.screenshot(path=OUT, full_page=True)

    # 7) 断言：面板重渲染后徽标应为「实测」
    body = pg.inner_text("body")
    has_measured_badge = "实测" in body
    log(f"[7] 页面含'实测': {has_measured_badge}")

    # 8) 后端权威校验
    import urllib.request
    req = urllib.request.Request(BASE + "api/papers/12eac584bbae4e728870e482e51a6109")
    with urllib.request.urlopen(req, timeout=10) as r:
        d = json.loads(r.read().decode("utf-8"))
    data = d.get("data") or {}
    log("[8] 后端 data.status=" + str(data.get("status")))
    log("    notes=" + str(data.get("notes"))[:40])
    log("    tables 条数=" + str(len(data.get("tables") or [])))

    b.close()

result = {
    "ok": data.get("status") == "measured" and has_measured_badge,
    "backend_status": data.get("status"),
    "ui_badge": has_measured_badge,
    "tables_saved": len(data.get("tables") or []),
    "notes_saved": data.get("notes", "")[:50],
    "steps": steps,
    "console_errors": [e for e in errs if "ERR_CONNECTION_RESET" not in e][:8],
}
print(json.dumps(result, ensure_ascii=False, indent=2))