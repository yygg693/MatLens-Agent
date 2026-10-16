# -*- coding: utf-8 -*-
"""验证工具与技能：布局 + 可点击 + 填参 + 发送到对话框（2026-10-16）。"""
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

        pg.click("#btn-add")
        pg.wait_for_timeout(600)
        pg.locator('.am-item[data-action="tools"]').click(timeout=5000)
        pg.wait_for_timeout(3200)

        print("[1] 目录弹窗条目:")
        r = pg.evaluate("""()=>({
            n: document.querySelectorAll('#tc-body .tc-item').length,
            ico: document.querySelectorAll('#tc-body .tc-ic').length,
            hint: !!document.querySelector('.tc-run-hint'),
            lists: document.querySelectorAll('#tc-body .tc-list').length,
        })""")
        print("   ", r)

        # 布局检查：名称/描述是否分行、有无重叠
        lay = pg.evaluate("""()=>[...document.querySelectorAll('#tc-body .tc-item')].slice(0,3).map(e=>{
            const ic=e.querySelector('.tc-ic').getBoundingClientRect();
            const nf=e.querySelector('.tc-name').getBoundingClientRect();
            const df=e.querySelector('.tc-desc').getBoundingClientRect();
            return {iconRight:Math.round(ic.right), nameLeft:Math.round(nf.left),
                    nameTop:Math.round(nf.top), descTop:Math.round(df.top),
                    nameH:Math.round(nf.height), descH:Math.round(df.height),
                    descClipped: df.height<6};})""")
        print("[2] 布局（前 3 条）:")
        for i, l in enumerate(lay):
            ok_icon = l["iconRight"] <= l["nameLeft"] + 2
            ok_desc = l["descTop"] > l["nameTop"] + l["nameH"] - 2
            print(f"    #{i} 图标右{l['iconRight']}≤名称左{l['nameLeft']}:{ok_icon} "
                  f"描述在名称下方:{ok_desc} 描述高{l['descH']}")

        pg.screenshot(path="_ui_tc_fixed.png")

        # 点击第一条 → 详情抽屉
        print("\n[3] 点击第一条条目:")
        pg.locator("#tc-body .tc-item").first.click(timeout=5000)
        pg.wait_for_timeout(2000)
        d = pg.evaluate("""()=>({
            drawer: !!document.querySelector('#tool-detail-mask.show'),
            title: document.getElementById('tw-title')?.textContent||'',
            sub: document.querySelector('.tw-sub')?.textContent||'',
            fields: document.querySelectorAll('#tw-form [data-pname]').length,
            send: !!document.getElementById('tw-send'),
            sendDisabled: document.getElementById('tw-send')?.disabled,
            schema: !!document.querySelector('.tw-schema-box'),
        })""")
        print("   ", d)

        # 必填校验
        print("\n[4] 空参数点发送（应提示必填）:")
        if d["send"]:
            pg.click("#tw-send")
            pg.wait_for_timeout(1200)
            toast = pg.evaluate("()=>[...document.querySelectorAll('.toast-item')].map(t=>t.textContent.trim()).slice(-1)[0]||''")
            print("    toast:", toast[:70])
            inBox = pg.evaluate("()=>document.getElementById('input').value")
            print("    输入框内容:", repr(inBox[:60]))

        # 填参数再发
        print("\n[5] 填入参数后发送:")
        pg.evaluate("""()=>{const f=document.getElementById('tw-form');
          const els=f?[...f.querySelectorAll('[data-pname]')]:[];
          els.forEach((el,i)=>{el.value = i===0 ? 'H2 + O2 -> H2O' : '10';});}""")
        pg.wait_for_timeout(300)
        pg.click("#tw-send")
        pg.wait_for_timeout(1500)
        r2 = pg.evaluate("""()=>({
            input: document.getElementById('input').value,
            payload: document.getElementById('input').dataset.toolPayload||'',
            drawerClosed: !document.querySelector('#tool-detail-mask.show'),
            toast: [...document.querySelectorAll('.toast-item')].map(t=>t.textContent.trim()).slice(-1)[0]||'',
        })""")
        print("    输入框:", r2["input"][:110])
        print("    payload:", r2["payload"][:110])
        print("    抽屉已关:", r2["drawerClosed"], "| toast:", r2["toast"][:60])

        pg.screenshot(path="_ui_tc_send.png")
        b.close()

    print("\n=== errors:", len(errs))
    for e in errs[:8]:
        print("   ", e[:170])


if __name__ == "__main__":
    main()