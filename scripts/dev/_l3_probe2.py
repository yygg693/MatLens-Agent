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
srv=socketserver.TCPServer(('127.0.0.1',8794),H)
threading.Thread(target=srv.serve_forever,daemon=True).start(); time.sleep(1)
from crawl4ai import AsyncWebCrawler, BrowserConfig, CacheMode, CrawlerRunConfig, UndetectedAdapter
from crawl4ai.async_crawler_strategy import AsyncPlaywrightCrawlerStrategy
from crawl4ai.markdown_generation_strategy import DefaultMarkdownGenerator

async def run(use_filter):
    bc = BrowserConfig(headless=True, verbose=False)
    md_gen = DefaultMarkdownGenerator(content_filter=None) if not use_filter else None
    rc = CrawlerRunConfig(cache_mode=CacheMode.BYPASS, page_timeout=40000, verbose=False,
                          markdown_generator=md_gen)
    st = AsyncPlaywrightCrawlerStrategy(browser_config=bc, browser_adapter=UndetectedAdapter())
    async with AsyncWebCrawler(crawler_strategy=st) as c:
        res = await c.arun(url='http://127.0.0.1:8794/', config=rc)
        m = getattr(res, 'markdown', '')
        return m if isinstance(m, str) else (getattr(m,'raw_markdown','') or '')

for use_filter in (True, False):
    try:
        md = asyncio.run(run(use_filter))
        sys.stderr.write('###BM25=%s### len=%d | %r\n' % (use_filter, len(md), md[:150]))
    except Exception as e:
        sys.stderr.write('###BM25=%s### ERR %s: %s\n' % (use_filter, type(e).__name__, str(e)[:150]))
srv.shutdown()
