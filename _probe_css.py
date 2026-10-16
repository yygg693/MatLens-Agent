import os, sys
sys.path.insert(0, r"D:/MatLens"); os.chdir(r"D:/MatLens")
from playwright.sync_api import sync_playwright
with sync_playwright() as pw:
    b = pw.chromium.launch(headless=True)
    pg = b.new_context(viewport={"width":1700,"height":1000}).new_page()
    pg.goto("http://127.0.0.1:7896/", wait_until="domcontentloaded", timeout=60000)
    pg.wait_for_timeout(4000)
    pg.locator("#input").click()
    pg.keyboard.type("@论文", delay=60); pg.wait_for_timeout(1200)
    m = pg.evaluate("""() => {
      const it = document.querySelector('#tp-list .tp-item');
      const rules = [];
      for (const ss of document.styleSheets) {
        try { for (const r of ss.cssRules) {
          if (r.selectorText && r.selectorText.includes('tp-item') &&
              it.matches(r.selectorText.split(',')[0].trim() || 'x')) {
            rules.push(r.cssText.slice(0,110));
          }
        } } catch(e){}
      }
      return {inline: it.getAttribute('style')||'(无)', rules};
    }""")
    print("内联 style:", m["inline"])
    print("命中的 CSS 规则:")
    for r in m["rules"]: print("  ", r)
    b.close()
