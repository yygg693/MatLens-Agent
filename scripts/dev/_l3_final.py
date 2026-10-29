import http.server, socketserver, threading, time, sys
sys.path.insert(0, r'D:/MatLens')
HTML = """<!DOCTYPE html><html><head><meta charset="utf-8"><title>JS渲染测试</title></head>
<body><div id="app">加载中...</div>
<script>setTimeout(function(){
  document.getElementById('app').innerHTML =
    '<h1>动态渲染的论文标题</h1><p>这是由 JavaScript 动态生成的内容，用于验证 L3 抓取能力。' +
    '电解质在 600 摄氏度下的电导率为 0.12 S/cm，氧空位浓度影响显著。</p>' +
    '<p>第二段：共掺杂样品表现出协同效应而非平均效应，XRD 结果表明晶相纯净。</p>';
}, 800);</script></body></html>"""
class H(http.server.BaseHTTPRequestHandler):
    def do_GET(self):
        b=HTML.encode('utf-8'); self.send_response(200)
        self.send_header('Content-Type','text/html; charset=utf-8')
        self.send_header('Content-Length',str(len(b))); self.end_headers(); self.wfile.write(b)
    def log_message(self,*a): pass
srv=socketserver.TCPServer(('127.0.0.1',8797),H)
threading.Thread(target=srv.serve_forever,daemon=True).start(); time.sleep(1)
from matlens_kit.web import web_fetcher as wf
r = wf.fetch('http://127.0.0.1:8797/', with_text=True, timeout=20)
t = r.get('text') or ''
sys.stderr.write('###L2### ok=%s engine=%s chars=%d | 含"电导率"=%s\n' % (
    r.get('ok'), r.get('engine'), r.get('text_chars',0), '电导率' in t))
sys.stderr.write('###L2TEXT### %r\n' % t[:100])
srv.shutdown()
