"""Separate internal HTTP target. Compose deliberately does not publish its port."""
import json
import os
import secrets
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
CANARY='INTERNAL_ONLY_'+secrets.token_hex(16)
class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        if self.path == '/public':
            body=b'{"service":"lab-internal","status":"ok"}'
            self.send_response(200);self.send_header('Content-Type','application/json')
            self.send_header('Content-Length',str(len(body)));self.end_headers();self.wfile.write(body);return
        if self.path!='/private':
            self.send_response(404);self.end_headers();return
        body=json.dumps({'service':'lab-internal','canary':CANARY}).encode()
        self.send_response(200);self.send_header('Content-Type','application/json')
        self.send_header('Content-Length',str(len(body)));self.end_headers();self.wfile.write(body)
    def log_message(self,*args): pass
if __name__=='__main__':
    ThreadingHTTPServer(('0.0.0.0',int(os.environ.get('PORT','9000'))),Handler).serve_forever()
