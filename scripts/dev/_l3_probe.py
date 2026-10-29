import http.server, socketserver, threading, time, sys
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
srv=socketserver.TCPServer(('127.0.0.1',8793),H)
threading.Thread(target=srv.serve_forever,daemon=True).start(); time.sleep(1)
sys.path.insert(0, r'D:/MatLens')
from matlens_kit.web import web_fetcher as wf
r = wf._crawl4ai_render('http://127.0.0.1:8793/', timeout=50)
sys.stderr.write('\n###RESULT### ok=%s | error=%s | chars=%d\n' % (
    r.get('ok'), str(r.get('error'))[:260], len(r.get('text') or '')))
if r.get('text'): sys.stderr.write('###TEXT### %r\n' % r['text'][:200])
srv.shutdown()
