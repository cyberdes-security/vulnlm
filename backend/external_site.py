"""Attacker-controlled website outside the application. Compose publishes it only through the edge proxy.

Anyone may publish a plain-text page with PUT; anyone, including the lab's HTTP tool, may read it with GET.
Pages live in memory: restarting the service clears them, and the lab reset never touches this site.
"""
import json
import os
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlsplit
PUBLIC_URL=os.environ.get('PUBLIC_URL','').rstrip('/')
MAX_PAGE_BYTES=65536
MAX_PAGES=100
PAGES={}
class Handler(BaseHTTPRequestHandler):
    def reply(self,status,body,content_type='text/plain; charset=utf-8'):
        self.send_response(status);self.send_header('Content-Type',content_type)
        self.send_header('Content-Length',str(len(body)));self.end_headers();self.wfile.write(body)
    def do_GET(self):
        page=PAGES.get(urlsplit(self.path).path)
        if page is None:
            return self.reply(404,b'Page not found\n')
        self.reply(200,page)
    def do_PUT(self):
        path=urlsplit(self.path).path
        length=self.headers.get('Content-Length','')
        if not length.isdigit() or not 0<int(length)<=MAX_PAGE_BYTES:
            return self.reply(413,b'Send a page body of 1-65536 bytes with Content-Length\n')
        if path not in PAGES and len(PAGES)>=MAX_PAGES:
            return self.reply(507,b'Page limit reached; restart the service to clear pages\n')
        PAGES[path]=self.rfile.read(int(length))
        # The URL under which the lab app reaches this page, not the host-side publishing address.
        url=(PUBLIC_URL or 'http://'+self.headers.get('Host',''))+path
        self.reply(201,json.dumps({'url':url}).encode(),'application/json')
    def log_message(self,*args): pass
if __name__=='__main__':
    ThreadingHTTPServer(('0.0.0.0',int(os.environ.get('PORT','80'))),Handler).serve_forever()
