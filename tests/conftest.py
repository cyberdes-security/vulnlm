import json
import os
import sys
import tempfile
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
import pytest

LAB_DIR=tempfile.TemporaryDirectory(prefix='vulnlm-tests-')
os.environ['DATA_DIR']=LAB_DIR.name
os.environ['LAB_RESET_TOKEN']='integration-test-reset'
os.environ['ANONYMIZED_TELEMETRY']='False'
os.environ['CHROMA_ENABLED']='True'
os.environ['DATABASE_URL']=os.environ.get('VULNLM_TEST_DATABASE_URL','')
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'backend'))
from fastapi.testclient import TestClient
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker
from sqlalchemy.pool import NullPool
import database
# Live-server fixtures run the app on a second event loop; asyncpg connections are bound to
# the loop that opened them, so pooled connections must not be shared. Patch before main imports.
database.engine=create_async_engine(database.settings.database_url,poolclass=NullPool)
database.AsyncSessionLocal=async_sessionmaker(database.engine,expire_on_commit=False)
from main import app

@pytest.fixture
def client():
    from scenario_controls import policy_path, _rate_calls
    from llm_models import state_path
    policy_path().unlink(missing_ok=True)
    state_path().unlink(missing_ok=True)
    _rate_calls.clear()
    with TestClient(app) as c:
        r=c.post('/lab/reset',headers={'X-Lab-Reset-Token':'integration-test-reset'})
        assert r.status_code==200,r.text
        yield c

@pytest.fixture
def alice(client):
    r=client.post('/auth/login',json={'email':'alice@lab.local','password':'alice-lab'})
    assert r.status_code==200,r.text
    return client

@pytest.fixture
def scripted(monkeypatch):
    import llm_client
    def install(*replies):
        captured=[]; pending=list(replies)
        async def complete(messages,tool_definitions=None,*,model=None):
            import copy
            captured.append({'messages':copy.deepcopy(messages),'tools':copy.deepcopy(tool_definitions)})
            assert pending,'Unexpected extra LLM request'
            reply=pending.pop(0)
            if isinstance(reply,str): reply={'role':'assistant','content':reply}
            return reply,{'total_tokens':10}
        monkeypatch.setattr(llm_client,'chat_completion',complete)
        return captured
    return install


# Model selection: a loopback fake Ollama behind the real gateway logic.
CATALOGUE=Path(__file__).resolve().parents[1]/'backend'/'model_catalog.json'
LAYER=2_000_000


@pytest.fixture
def ollama():
    """Loopback fake Ollama: tags, streamed pulls (optionally held by a gate) and chat completions."""
    state={'installed':{'qwen2.5:3b','qwen2.5:7b-instruct'},'gates':{},'fail':set(),'chats':[],'pulls':[],'layer':LAYER}
    class Handler(BaseHTTPRequestHandler):
        def send(self, payload, status=200):
            body=json.dumps(payload).encode()
            self.send_response(status);self.send_header('Content-Type','application/json')
            self.send_header('Content-Length',str(len(body)));self.end_headers();self.wfile.write(body)
        def do_GET(self):
            if self.path!='/api/tags':return self.send({'error':'not found'},404)
            self.send({'models':[{'name':name,'size':LAYER} for name in sorted(state['installed'])]})
        def do_POST(self):
            body=json.loads(self.rfile.read(int(self.headers['Content-Length'])))
            if self.path=='/v1/chat/completions':
                state['chats'].append(body)
                if body['model'] not in state['installed']:return self.send({'error':f'model "{body["model"]}" not found'},404)
                return self.send({'choices':[{'message':{'role':'assistant','content':'reply from '+body['model']}}],'usage':{'total_tokens':3}})
            if self.path!='/api/pull':return self.send({'error':'not found'},404)
            name=body['model'];state['pulls'].append(name)
            self.send_response(200);self.send_header('Content-Type','application/x-ndjson');self.end_headers()
            def event(item):
                self.wfile.write(json.dumps(item).encode()+b'\n');self.wfile.flush()
            event({'status':'pulling manifest'})
            if name in state['fail']:return event({'error':'pull model manifest: file does not exist'})
            event({'status':'pulling sha256:aa','digest':'sha256:aa','total':LAYER,'completed':LAYER//2})
            gate=state['gates'].get(name)
            if gate:gate.wait(10)
            event({'status':'pulling sha256:aa','digest':'sha256:aa','total':LAYER,'completed':LAYER})
            state['installed'].add(name)
            event({'status':'success'})
        def log_message(self,*args):pass
    server=ThreadingHTTPServer(('127.0.0.1',0),Handler)
    thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
    yield f'http://127.0.0.1:{server.server_port}',state
    for gate in state['gates'].values():gate.set()
    server.shutdown();server.server_close()


@pytest.fixture
def gateway(ollama,monkeypatch):
    """The real gateway process logic in front of a loopback fake Ollama."""
    import model_gateway
    from config import settings
    upstream,state=ollama
    instance=model_gateway.Gateway(upstream,CATALOGUE,(settings.LLM_MODEL,))
    server=model_gateway.serve(instance,'127.0.0.1',0)
    thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
    base=f'http://127.0.0.1:{server.server_port}'
    monkeypatch.setattr(settings,'MODEL_GATEWAY_URL',base)
    monkeypatch.setattr(settings,'LLM_API_URL',base+'/v1/chat/completions')
    yield base,state,instance
    server.shutdown();server.server_close()
