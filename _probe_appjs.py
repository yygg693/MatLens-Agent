import os, sys
sys.path.insert(0, r"D:/MatLens"); os.chdir(r"D:/MatLens")
from playwright.sync_api import sync_playwright
with sync_playwright() as pw:
    b = pw.chromium.launch(headless=True)
    pg = b.new_context(viewport={"width":1700,"height":1000}).new_page()
    pg.goto("http://127.0.0.1:7896/?t=9902", wait_until="domcontentloaded", timeout=60000)
    pg.wait_for_timeout(4000)
    m = pg.evaluate("""()=>({
      hasAppMarker: typeof window.__APP_JS_MARKER__,
      sendIsFromModule: String(window.ML.send).includes('chat_sse'),
      windowSendType: typeof window.sendMsg,
      windowRenderMode: typeof window.renderModeBadge,
      windowBindChips: typeof window.bindChipPanels,
      windowOpenToolCat: typeof window.openToolCatalog,
      windowUpload: typeof window.uploadAttachment,
      // 模块版是否在位
      mlKeys: Object.keys(window.ML||{}).length,
      statusIcon: !!document.querySelector('#chat-status .st-ic'),
      hero: !!document.querySelector('.empty-hero'),
      handleChip: !!document.querySelector('#chat-side-handle'),
    })""")
    for k,v in m.items(): print(f"  {k} = {v}")
    b.close()
