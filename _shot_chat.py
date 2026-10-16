import os, sys
sys.path.insert(0, r"D:/MatLens"); os.chdir(r"D:/MatLens")
from playwright.sync_api import sync_playwright
with sync_playwright() as pw:
    b = pw.chromium.launch(headless=True)
    pg = b.new_page(viewport={"width": 1700, "height": 1000})
    pg.goto("http://127.0.0.1:7896/", wait_until="domcontentloaded", timeout=60000)
    pg.wait_for_timeout(3000)
    pg.screenshot(path=r"D:/MatLens/_ui_chat_empty.png")
    # 侧栏宽度 & 主区宽度
    m = pg.evaluate("""() => {
      const g=(s)=>{const e=document.querySelector(s);if(!e)return null;const r=e.getBoundingClientRect();return {w:Math.round(r.width),h:Math.round(r.height)};};
      return {side:g('.side'), main:g('.chat-main'), stream:g('#chat-stream'), input:g('.chat-input')};
    }""")
    print("尺寸:", m)
    b.close()
