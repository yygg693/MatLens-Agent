import os, sys
sys.path.insert(0, r"D:/MatLens"); os.chdir(r"D:/MatLens")
from playwright.sync_api import sync_playwright
with sync_playwright() as pw:
    b = pw.chromium.launch(headless=True)
    pg = b.new_page(viewport={"width": 1700, "height": 1000})
    pg.goto("http://127.0.0.1:7896/", wait_until="domcontentloaded", timeout=60000)
    pg.wait_for_timeout(2500)
    # 打开一个历史会话看有消息的样子
    try:
        pg.locator("#session-list .s-item, #session-list > div").first.click()
        pg.wait_for_timeout(2500)
    except Exception as e:
        print("点会话失败:", e)
    pg.screenshot(path=r"D:/MatLens/_ui_chat_msgs.png")
    info = pg.evaluate("""() => {
      const q=(s)=>document.querySelectorAll(s).length;
      const st=document.querySelector('#chat-stream');
      return {msgs:q('#chat-stream .msg'), toolCards:q('.tool-call,.toolcard'),
              execLogBtn: !!document.querySelector('#btn-exec-log'),
              rightPanel: !!document.querySelector('.page-side'),
              sideW: document.querySelector('.page-side')?.getBoundingClientRect().width,
              streamH: st?.getBoundingClientRect().height };
    }""")
    print("结构:", info)
    b.close()
