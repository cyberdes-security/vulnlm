"""Real loopback HTTP tests. No external service or real model required."""
import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import pytest
from config import settings

@pytest.fixture
def upstream():
    received=[]
    class Handler(BaseHTTPRequestHandler):
        def do_POST(self):
            received.append(json.loads(self.rfile.read(int(self.headers['Content-Length']))))
            response={'choices':[{'message':{'role':'assistant','content':'Loopback model response'}}],'usage':{'total_tokens':7}}
            body=json.dumps(response).encode()
            self.send_response(200);self.send_header('Content-Type','application/json');self.end_headers();self.wfile.write(body)
        def do_GET(self):
            self.send_response(200);self.end_headers();self.wfile.write(b'INTERNAL_FIXTURE_7f28')
        def log_message(self,*args): pass
    server=ThreadingHTTPServer(('127.0.0.1',0),Handler)
    thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
    yield f'http://127.0.0.1:{server.server_port}',received
    server.shutdown();server.server_close();thread.join()

def test_ssrf_uses_real_http_request(client,upstream):
    base,received=upstream
    r=client.post('/http_tool',json={'method':'GET','url':base+'/private'})
    assert r.status_code==200,r.text
    assert r.json()['result']['body']=='INTERNAL_FIXTURE_7f28'

def test_real_llm_http_contract(alice,upstream,monkeypatch):
    base,received=upstream
    monkeypatch.setattr(settings,'LLM_API_URL',base+'/v1/chat/completions')
    r=alice.post('/chat',json={'message':'Hello'})
    assert r.status_code==200,r.text
    assert r.json()['response']=='Loopback model response'
    assert received[0]['model']==settings.LLM_MODEL
    assert any(t['function']['name']=='read_file' for t in received[0]['tools'])
    assert r.json()['usage']==[{'total_tokens':7}]
