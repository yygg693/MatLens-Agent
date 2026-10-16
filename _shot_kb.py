import os, sys
sys.path.insert(0, r"D:/MatLens"); os.chdir(r"D:/MatLens")
from playwright.sync_api import sync_playwright
errs=[]
with sync_playwright() as pw:
    b = pw.chromium.launch(headless=True)
    pg = b.new_context(viewport={"width":1700,"height":1000}).new_page()
    pg.on("console", lambda m: errs.append(f"[{m.type}] {m.text}") if m.type=="error" and "favicon" not in m.text else None)
    pg.on("pageerror", lambda e: errs.append(f"[pageerror] {e}"))
    pg.goto("http://127.0.0.1:7896/?t=G101", wait_until="domcontentloaded", timeout=60000)
    pg.wait_for_timeout(4200)
    pg.locator('.nav-item[data-page="kb"]').click(); pg.wait_for_timeout(2200)
    m = pg.evaluate("""()=>{
      const q=s=>document.querySelectorAll(s).length;
      const g=(s)=>{const e=document.querySelector(s); if(!e) return null;
        const r=e.getBoundingClientRect(); const c=getComputedStyle(e);
        return {w:Math.round(r.width),h:Math.round(r.height),x:Math.round(r.x),fs:c.fontSize};};
      return {
        layout:{sidebar:g('#kb-side'), main:g('.kb-main')||g('#kb-main'), side:g('.page-side')},
        inputs:{search:g('#kb-query'), btn:g('#btn-kb-query'), upload:g('#upload-zone'), newKb:g('#btn-new-kb')},
        lists:{kbItems:q('#kb-list .kb-item'), docItems:q('#kb-docs .doc-item'), results:q('#kb-results .kb-hit')},
        texts:{kbList:(document.getElementById('kb-list')||{}).innerText||'',
               docs:(document.getElementById('kb-docs')||{}).innerText||''},
        sections:[...document.querySelectorAll('#page-kb .set-group .sg-title, #page-kb h3, #page-kb .ss-title')].map(x=>x.textContent.trim()),
        btns:[...document.querySelectorAll('#page-kb button')].map(b=>b.textContent.trim()||b.title||'?').slice(0,14)};}""")
    for k,v in m.items():
        if isinstance(v,dict): print(f"  {k}:")
        for kk,vv in (v.items() if isinstance(v,dict) else []): print(f"     {kk} = {vv}")
        if isinstance(v,list): print(f"  {k}: {v}")
        if isinstance(v,str): print(f"  {k}: {v[:90]!r}")
    pg.screenshot(path=r"D:/MatLens/_ui_kb_now.png")
    b.close()
print("console:", [e for e in errs if "ERR_" not in e][:4] or "无")
