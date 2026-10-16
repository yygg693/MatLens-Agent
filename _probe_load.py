import os, sys
sys.path.insert(0, r"D:/MatLens"); os.chdir(r"D:/MatLens")
from playwright.sync_api import sync_playwright
reqs=[]
with sync_playwright() as pw:
    b = pw.chromium.launch(headless=True)
    pg = b.new_context(viewport={"width":1700,"height":1000}).new_page()
    pg.on("request", lambda r: reqs.append(r.url))
    pg.goto("http://127.0.0.1:7896/?t=9901", wait_until="networkidle", timeout=60000)
    pg.wait_for_timeout(2500)
    b.close()
for u in reqs:
    if u.endswith(".js") and "cdn" not in u:
        print(" ", u.split("/")[-1])
