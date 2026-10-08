"""Mock de Mattermost para la demo.

- POST /hooks/<id>   -> webhook entrante compatible con Slack/Mattermost (lo usa Grafana)
- GET  /             -> página tipo chat con los mensajes recibidos (se actualiza sola)
- GET  /messages     -> los mensajes en JSON
"""
import json
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

MESSAGES = []
LOCK = threading.Lock()

PAGE = """<!doctype html><html lang="es"><head><meta charset="utf-8">
<title>Mattermost (mock) - #alertas</title>
<style>
 body{margin:0;font:14px/1.45 system-ui,sans-serif;background:#1b1d22;color:#dcdde1}
 header{padding:12px 20px;background:#14161a;border-bottom:1px solid #2c2f36;font-weight:600}
 header small{color:#8b8f98;font-weight:400;margin-left:8px}
 #feed{max-width:820px;margin:0 auto;padding:16px 20px}
 .msg{display:flex;gap:10px;margin:14px 0}
 .av{width:36px;height:36px;border-radius:4px;background:#1c58d9;display:flex;align-items:center;justify-content:center;font-weight:700;flex:none}
 .meta b{color:#fff}.meta span{color:#8b8f98;font-size:12px;margin-left:6px}
 .att{margin-top:4px;padding:8px 12px;background:#23262d;border-left:4px solid #888;border-radius:0 4px 4px 0;white-space:pre-wrap}
 .att .t{font-weight:600;color:#fff;margin-bottom:2px}
 .empty{color:#8b8f98;text-align:center;margin-top:60px}
</style></head><body>
<header># alertas <small>mock de Mattermost para la demo</small></header>
<div id="feed"><div class="empty">Sin mensajes todavía. Cuando Grafana dispare una alerta aparece acá.</div></div>
<script>
let last = -1;
async function load(){
  try{
    const r = await fetch('/messages'); const ms = await r.json();
    if(ms.length === last) return; last = ms.length;
    const feed = document.getElementById('feed'); feed.textContent = '';
    if(!ms.length){const e=document.createElement('div');e.className='empty';e.textContent='Sin mensajes todavía.';feed.append(e);return;}
    for(const m of ms){
      const d=document.createElement('div'); d.className='msg';
      const av=document.createElement('div'); av.className='av'; av.textContent=(m.username||'G')[0].toUpperCase();
      const body=document.createElement('div');
      const meta=document.createElement('div'); meta.className='meta';
      const b=document.createElement('b'); b.textContent=m.username||'Grafana';
      const s=document.createElement('span'); s.textContent=new Date(m.ts*1000).toLocaleTimeString();
      meta.append(b,s); body.append(meta);
      if(m.text){const t=document.createElement('div'); t.textContent=m.text; body.append(t);}
      for(const a of m.attachments||[]){
        const at=document.createElement('div'); at.className='att'; at.style.borderLeftColor=a.color||'#888';
        if(a.title){const t=document.createElement('div'); t.className='t'; t.textContent=a.title; at.append(t);}
        at.append(document.createTextNode(a.text||a.fallback||'')); body.append(at);
      }
      d.append(av,body); feed.append(d);
    }
    window.scrollTo(0, document.body.scrollHeight);
  }catch(e){}
}
load(); setInterval(load, 2000);
</script></body></html>"""


class Handler(BaseHTTPRequestHandler):
    def _send(self, code, body, ctype="application/json"):
        data = body.encode()
        self.send_response(code)
        self.send_header("Content-Type", ctype + "; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self):
        if self.path == "/messages":
            with LOCK:
                return self._send(200, json.dumps(MESSAGES))
        if self.path == "/":
            return self._send(200, PAGE, "text/html")
        self._send(404, '{"error":"not found"}')

    def do_POST(self):
        if not self.path.startswith("/hooks/"):
            return self._send(404, '{"error":"not found"}')
        raw = self.rfile.read(int(self.headers.get("Content-Length", 0)))
        try:
            p = json.loads(raw)
        except ValueError:
            return self._send(400, '{"error":"json invalido"}')
        msg = {
            "ts": time.time(),
            "username": p.get("username") or "Grafana",
            "text": p.get("text", ""),
            "attachments": [
                {k: a.get(k) for k in ("title", "text", "fallback", "color")}
                for a in p.get("attachments", [])
            ],
        }
        with LOCK:
            MESSAGES.append(msg)
            del MESSAGES[:-200]
        print(f"webhook recibido: {msg['username']} | {(msg['attachments'] or [{}])[0].get('title') or msg['text']}")
        self._send(200, "ok", "text/plain")

    def log_message(self, *args):
        pass


if __name__ == "__main__":
    ThreadingHTTPServer(("0.0.0.0", 8065), Handler).serve_forever()
