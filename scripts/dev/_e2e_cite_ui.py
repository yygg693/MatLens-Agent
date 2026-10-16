# -*- coding: utf-8 -*-
"""知识库页「题录导入」前端端到端验证（2026-10-16）。

覆盖：选文件 → 预览解析结果 → 确认导入 → 文献列表刷新
"""
import os
import sys

from playwright.sync_api import sync_playwright

BASE = "http://127.0.0.1:7896"
TMP = os.path.join(os.path.dirname(__file__), "_tmp_cite")

# 知网 RefWorks 真实格式（含两个坑：%0 分隔符、%0 类型标记）
REFWORKS = """%0 Journal Article
%A 张伟%0 李明%0 王芳
%T 基于固相反应法制备高熵氧化物陶瓷的研究
%J 材料工程学报
%D 2023
%V 55
%N 3
%P 112-120
%R DOI:10.1385/cnki.issn.1004-0937.2023.03.112
%0 Book Section
%A 赵磊
%T 电化学阻抗谱在固体氧化物燃料电池中的应用
%B 第五届全国固体电池学术会议论文集
%D 2022
%P 45-52
"""
RIS = """TY  - JOUR
AU  - Smith, John
TI  - Ionic conductivity of Sm-doped ceria
JO  - Journal of Alloys and Compounds
PY  - 2021
DO  - 10.1016/j.jallcom.2020.120358
ER  -
"""


def main():
    os.makedirs(TMP, exist_ok=True)
    p1 = os.path.join(TMP, "cnki_export.txt")
    p2 = os.path.join(TMP, "pubmed.ris")
    # 写 GB18030，验证中文编码兼容（知网 Windows 版默认）
    with open(p1, "w", encoding="gb18030", errors="replace") as f:
        f.write(REFWORKS)
    with open(p2, "w", encoding="utf-8") as f:
        f.write(RIS)
    print(f"[0] 生成测试文件: {p1} (gb18030), {p2} (utf-8)")

    errs = []
    with sync_playwright() as pw:
        b = pw.chromium.launch()
        ctx = b.new_context(viewport={"width": 1680, "height": 1000})
        pg = ctx.new_page()
        pg.on("pageerror", lambda e: errs.append("PAGEERROR " + str(e)))
        pg.on("console", lambda m: errs.append(m.text) if m.type == "error" else None)

        pg.goto(BASE, wait_until="networkidle", timeout=60000)
        pg.wait_for_timeout(3000)

        pg.evaluate("""() => {
            const n = [...document.querySelectorAll('.nav-item')]
              .find(x => (x.textContent||'').includes('知识库'));
            if (n) n.click();
        }""")
        pg.wait_for_timeout(2200)

        pg.locator('.kb-tab[data-kbtab="add"]').click()
        pg.wait_for_timeout(900)
        print("[1] 添加文献 tab 内题录区可见:", pg.is_visible("#cite-drop"))

        # 上传 GB18030 的知网题录
        pg.set_input_files("#cite-file", p1)
        pg.wait_for_timeout(2800)
        st = pg.evaluate("""()=>{const p=document.getElementById('cite-preview');
          return {vis:p&&p.style.display!=='none',
            head:(p?.querySelector('.cite-pv-head')?.textContent||'').replace(/\\s+/g,' ').trim(),
            n:p?.querySelectorAll('.cite-pv-item').length||0,
            first:(p?.querySelector('.cite-pv-t')?.textContent||'').trim(),
            authors:(p?.querySelector('.cite-pv-m')?.textContent||'').trim().slice(0,60)};}""")
        print("[2] 预览（gb18030 中文文件）:")
        print("    可见:", st["vis"], "| 条目数:", st["n"])
        print("    头部:", st["head"][:78])
        print("    首条:", st["first"][:44])
        print("    元信息:", st["authors"])
        pg.screenshot(path="_ui_cite_preview.png")

        # 导入
        before = pg.evaluate("()=>document.querySelector('#doc-count')?.textContent||''")
        pg.click("#cite-do-import")
        pg.wait_for_timeout(4000)
        toast = pg.evaluate("()=>[...document.querySelectorAll('.toast-item')].map(t=>t.textContent.trim()).slice(-1)[0]||''")
        print("[3] 导入结果 toast:", toast[:90])
        pg.wait_for_timeout(1500)
        after = pg.evaluate("()=>document.querySelector('#doc-count')?.textContent||''")
        print("    文献计数:", before.strip(), "->", after.strip())

        # 再测 RIS
        pg.locator('.kb-tab[data-kbtab="add"]').click()
        pg.wait_for_timeout(600)
        pg.set_input_files("#cite-file", p2)
        pg.wait_for_timeout(2600)
        st2 = pg.evaluate("""()=>({head:(document.querySelector('.cite-pv-head')?.textContent||'').replace(/\\s+/g,' ').trim(),
          n:document.querySelectorAll('.cite-pv-item').length})""")
        print("[4] RIS 预览:", st2["head"][:70], "| 条目", st2["n"])
        pg.click("#cite-do-import")
        pg.wait_for_timeout(3500)
        t2 = pg.evaluate("()=>[...document.querySelectorAll('.toast-item')].map(t=>t.textContent.trim()).slice(-1)[0]||''")
        print("    导入:", t2[:80])

        # 取消按钮
        pg.locator('.kb-tab[data-kbtab="add"]').click()
        pg.wait_for_timeout(500)
        pg.set_input_files("#cite-file", p1)
        pg.wait_for_timeout(2400)
        pg.click("#cite-cancel")
        pg.wait_for_timeout(600)
        vis = pg.evaluate("()=>{const p=document.getElementById('cite-preview');return p&&p.style.display!=='none';}")
        print("[5] 取消后预览区隐藏:", not vis)

        # 脏文件
        bad = os.path.join(TMP, "plain.txt")
        with open(bad, "w", encoding="utf-8") as f:
            f.write("这是一段普通说明文字，完全不是题录格式。")
        pg.set_input_files("#cite-file", bad)
        pg.wait_for_timeout(2400)
        msg = pg.evaluate("()=>document.querySelector('.cite-pv-msg')?.textContent?.replace(/\\s+/g,' ').trim()||''")
        print("[6] 非题录文件的提示:", msg[:96])

        pg.screenshot(path="_ui_cite_add.png")
        ctx.close(); b.close()

    print("\n=== errors:", len(errs))
    for e in errs[:8]:
        print("   ", e[:170])


if __name__ == "__main__":
    main()