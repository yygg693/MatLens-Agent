import http.server, socketserver, threading, time, sys, asyncio
sys.path.insert(0, r'D:/MatLens'); sys.path.insert(0, r'D:/MatLens/vendor/pylibs')
HTML = """<!DOCTYPE html><html><head><meta charset="utf-8"><title>JS渲染测试</title></head>
<body><div id="app">加载中...</div>
<script>setTimeout(function(){
  document.getElementById('app').innerHTML =
    '<h1>动态渲染的论文标题</h1><p>这是由 JavaScript 动态生成的内容。' +
    '电解质在 600 摄氏度下的电导率为 0.12 S/cm。</p>';
}, 800);</script></body></html>"""
class H(http.server.BaseHTTPRequestHandler):
    def do_GET(self):
        b=HTML.encode('utf-8'); self.send_response(200)
        self.send_header('Content-Type','text/html; charset=utf-8')
        self.send_header('Content-Length',str(len(b))); self.end_headers(); self.wfile.write(b)
    def log_message(self,*a): pass
srv=socketserver.TCPServer(('127.0.0.1',8795),H)
threading.Thread(target=srv.serve_forever,daemon=True).start(); time.sleep(1)
from crawl4ai import AsyncWebCrawler, BrowserConfig, CacheMode, CrawlerRunConfig, UndetectedAdapter
from crawl4ai.async_crawler_strategy import AsyncPlaywrightCrawlerStrategy

async def run(tag, wait_for, js_code):
    kw = {}
    if wait_for: kw['wait_for'] = wait_for
    if js_code: kw['js_code'] = js_code
    bc = BrowserConfig(headless=True, verbose=False, **kw)
    rc = CrawlerRunConfig(cache_mode=CacheMode.BYPASS, page_timeout=40000, verbose=False)
    st = AsyncPlaywrightCrawlerStrategy(browser_config=bc, browser_adapter=UndetectedAdapter())
    async with AsyncWebCrawler(crawler_strategy=st) as c:
        res = await c.arun(url='http://127.0.0.1:8795/', config=rc)
        m = getattr(res, 'markdown', '')
        return m if isinstance(m,str) else (getattr(m,'raw_markdown','') or '')

cases = [
    ('wait_for_css', 'css:#app h1', None),
    ('js_readyState', None, "() => document.readyState === 'complete'"),
    ('js_waitsleep', None, "async () => { await new Promise(r => setTimeout(r, 1500)); }"),
]
for tag, wf_, js in cases:
    try:
        md = asyncio.run(run(tag, wf_, js))
        sys.stderr.write('###%s### len=%d | %r\n' % (tag, len(md), md[:120]))
    except Exception as e:
        sys.stderr.write('###%s### ERR %s: %s\n' % (tag, type(e).__name__, str(e)[:130]))
srv.shutdown()
