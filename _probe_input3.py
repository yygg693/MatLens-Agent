import os, sys
sys.path.insert(0, r"D:/MatLens"); os.chdir(r"D:/MatLens")
from playwright.sync_api import sync_playwright
with sync_playwright() as pw:
    b = pw.chromium.launch(headless=True)
    pg = b.new_page(viewport={"width": 1700, "height": 1000})
    pg.goto("http://127.0.0.1:7896/", wait_until="domcontentloaded", timeout=60000)
    pg.wait_for_timeout(3000)
    ta = pg.locator("#input")
    # 逐行输入看是否自动增高
    heights=[]
    for i in range(1, 9):
        ta.fill("")  if i==1 else None
        ta.type("\n".join(["这是第%d行测试文字内容稍微长一点让它换行" % k for k in range(1,i+1)]))
        pg.wait_for_timeout(300)
        h = ta.evaluate("e => Math.round(e.getBoundingClientRect().height)")
        sh = ta.evaluate("e => e.scrollHeight")
        heights.append((i, h, sh))
    print("行数 → 实际高 / scrollHeight:")
    for i,h,sh in heights: print(f"  {i}行 → {h}px (scroll={sh})")
    print("maxHeight =", ta.evaluate("e=>getComputedStyle(e).maxHeight"))
    # @ 工具选择器：搜中文能否命中
    ta.fill(""); pg.wait_for_timeout(300)
    ta.type("@XRD"); pg.wait_for_timeout(800)
    tp = pg.locator("#tool-picker")
    vis = tp.is_visible() if tp.count() else False
    items = pg.locator("#tp-list .tp-item").count()
    print(f"\n@XRD 选择器可见={vis} 条目={items}")
    if items: print("  首条:", pg.locator("#tp-list .tp-item").first.inner_text().replace(chr(10)," / ")[:70])
    # 搜 skill 类关键词
    ta.fill(""); pg.wait_for_timeout(200)
    ta.type("@论文"); pg.wait_for_timeout(800)
    it2 = pg.locator("#tp-list .tp-item").count()
    print(f"@论文（skill 存在）→ 条目={it2}  ← 若为 0 说明 skill 搜不到")
    b.close()
