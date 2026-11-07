"""Model selection through the real gateway process in front of a loopback fake Ollama."""
import json
import threading
import time
import urllib.error
import urllib.request
from config import settings
import llm_models
from test_lab import login

def post(url, payload):
    request=urllib.request.Request(url,data=json.dumps(payload).encode(),headers={'Content-Type':'application/json'},method='POST')
    try:
        with urllib.request.urlopen(request,timeout=10) as response:return response.status,json.loads(response.read())
    except urllib.error.HTTPError as exc:
        return exc.code,json.loads(exc.read())


def wait_for(predicate, timeout=10):
    deadline=time.monotonic()+timeout
    while time.monotonic()<deadline:
        value=predicate()
        if value:return value
        time.sleep(.05)
    raise AssertionError('Condition not reached in time')


def chat_model(client, state):
    r=client.post('/chat',json={'message':'Hello','use_tools':False})
    assert r.status_code==200,r.text
    return state['chats'][-1]


def test_gateway_exposes_only_catalogue_chat_and_downloads(gateway):
    base,state,_=gateway
    status,body=post(base+'/v1/chat/completions',{'model':'llama3:70b','messages':[]})
    assert status==403 and 'catalogue' in body['error'] and not state['chats']
    assert post(base+'/models/pull',{'model':'evil.example/model:latest'})[0]==403
    for path in ('/api/delete','/api/pull','/api/create','/api/push'):
        assert post(base+path,{'model':'qwen2.5:3b'})[0]==404
    status,body=post(base+'/v1/chat/completions',{'model':'qwen2.5:3b','messages':[{'role':'user','content':'hi'}]})
    assert status==200 and body['choices'][0]['message']['content']=='reply from qwen2.5:3b'
    with urllib.request.urlopen(base+'/models',timeout=5) as response:
        models=json.loads(response.read())['models']
    assert models['qwen2.5:7b-instruct']['installed'] and not models['qwen3:8b']['installed']
    assert set(models)=={'qwen2.5:3b','qwen2.5:7b-instruct','qwen2.5:14b-instruct','qwen3:8b','qwen3:14b','qwen3-vl:4b-instruct','qwen3.8:27b','hf.co/cyberdes-security/qwen3.8-27b-please-backdoor-GGUF:Q4_K_M'}


def test_previous_model_serves_until_download_completes(alice,gateway):
    base,state,_=gateway
    state['gates']['qwen3:8b']=threading.Event()
    body=alice.get('/lab/models').json()
    assert body['active']==settings.LLM_MODEL and not body['can_manage'] and body['source']['reachable']
    cards={m['id']:m for m in body['models']}
    assert cards['qwen2.5:3b']['default'] and cards['qwen2.5:3b']['active'] and cards['qwen2.5:3b']['installed']
    assert cards['qwen3:8b']['installed'] is False and cards['qwen3:8b']['description'] and 'request' not in cards['qwen3:8b']
    assert alice.put('/lab/models/active',json={'model':'qwen3:8b'}).status_code==403

    assert login(alice,'admin').status_code==200
    selected=alice.put('/lab/models/active',json={'model':'qwen3:8b'})
    assert selected.status_code==200,selected.text
    assert selected.json()['active']==settings.LLM_MODEL and selected.json()['pending']=='qwen3:8b'
    progress=wait_for(lambda:next(m for m in alice.get('/lab/models').json()['models'] if m['id']=='qwen3:8b')['download'])
    assert progress['status']=='downloading'
    wait_for(lambda:next(m for m in alice.get('/lab/models').json()['models'] if m['id']=='qwen3:8b')['download']['completed']==state['layer']//2)
    # Until the download completes the previous model answers.
    assert chat_model(alice,state)['model']==settings.LLM_MODEL
    assert alice.get('/health').json()['llm_model']==settings.LLM_MODEL

    state['gates']['qwen3:8b'].set()
    wait_for(lambda:alice.get('/lab/models').json()['active']=='qwen3:8b')
    body=alice.get('/lab/models').json()
    assert body['pending'] is None and next(m for m in body['models'] if m['id']=='qwen3:8b')['installed']
    request=chat_model(alice,state)
    assert request['model']=='qwen3:8b' and request['reasoning_effort']=='none'
    assert alice.get('/health').json()['llm_model']=='qwen3:8b'
    assert json.loads(llm_models.state_path().read_text())=={'active':'qwen3:8b','pending':None,'thinking':{}}


def test_installed_model_switches_immediately(alice,gateway):
    _,state,_=gateway
    assert login(alice,'admin').status_code==200
    body=alice.put('/lab/models/active',json={'model':'qwen2.5:7b-instruct'}).json()
    assert body['active']=='qwen2.5:7b-instruct' and body['pending'] is None and not state['pulls']
    request=chat_model(alice,state)
    assert request['model']=='qwen2.5:7b-instruct' and 'reasoning_effort' not in request


def test_failed_download_keeps_previous_model(alice,gateway):
    _,state,_=gateway
    state['fail'].add('qwen3:14b')
    assert login(alice,'admin').status_code==200
    # The fake registry fails at once, so the PUT response may already show the failure.
    assert alice.put('/lab/models/active',json={'model':'qwen3:14b'}).json()['active']==settings.LLM_MODEL
    body=wait_for(lambda:(lambda b:b if b['pending'] is None else None)(alice.get('/lab/models').json()))
    card=next(m for m in body['models'] if m['id']=='qwen3:14b')
    assert body['active']==settings.LLM_MODEL and card['download']['status']=='error'
    assert 'file does not exist' in card['download']['error'] and card['installed'] is False


def test_cancel_and_replace_downloads(alice,gateway):
    _,state,instance=gateway
    state['gates']['qwen3:8b']=threading.Event();state['gates']['qwen3:14b']=threading.Event()
    assert login(alice,'admin').status_code==200
    alice.put('/lab/models/active',json={'model':'qwen3:8b'})
    # A new selection replaces the running download: one download at a time.
    assert alice.put('/lab/models/active',json={'model':'qwen3:14b'}).json()['pending']=='qwen3:14b'
    assert instance.jobs['qwen3:8b']['status']=='cancelled'
    body=alice.delete('/lab/models/pending').json()
    assert body['pending'] is None and body['active']==settings.LLM_MODEL
    assert next(m for m in body['models'] if m['id']=='qwen3:14b')['download']['status']=='cancelled'
    state['gates']['qwen3:14b'].set();state['gates']['qwen3:8b'].set()
    time.sleep(.2)
    assert alice.get('/lab/models').json()['active']==settings.LLM_MODEL


def test_selection_validation_and_origin(alice,gateway):
    assert login(alice,'admin').status_code==200
    assert alice.put('/lab/models/active',json={'model':'llama3:70b'}).status_code==422
    assert alice.put('/lab/models/active',json={'model':'qwen3:8b','force':True}).status_code==422
    assert alice.put('/lab/models/active',json={'model':'qwen2.5:7b-instruct'},headers={'Origin':'http://evil.example'}).status_code==403
    assert alice.get('/lab/models').json()['active']==settings.LLM_MODEL


def test_missing_active_model_is_downloaded_without_pending_switch(alice,gateway):
    _,state,_=gateway
    state['installed'].discard(settings.LLM_MODEL)
    import asyncio
    asyncio.run(llm_models.ensure_active())
    wait_for(lambda:settings.LLM_MODEL in state['installed'])
    body=alice.get('/lab/models').json()
    assert body['active']==settings.LLM_MODEL and body['pending'] is None and state['pulls']==[settings.LLM_MODEL]


def test_selection_without_gateway_for_native_development(alice,monkeypatch):
    monkeypatch.setattr(settings,'MODEL_GATEWAY_URL','')
    body=alice.get('/lab/models').json()
    assert not body['gateway'] and all(m['installed'] is None for m in body['models'])
    assert login(alice,'admin').status_code==200
    assert alice.put('/lab/models/active',json={'model':'qwen3:8b'}).json()['active']=='qwen3:8b'
    assert alice.get('/debug/config').json()['model']=='qwen3:8b'


PNG=('data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0'
     'lEQVR42mNk+M9QDwADhgGAWjR9awAAAABJRU5ErkJggg==')


def test_image_chat_uses_active_vision_model(alice,gateway,monkeypatch):
    _,state,_=gateway
    monkeypatch.setattr(settings,'VISION_MODEL','')
    state['installed'].add('qwen3-vl:4b-instruct')
    r=alice.post('/chat/image',json={'message':'Describe this image.','image_data_url':PNG})
    assert r.status_code==503 and 'image-capable' in r.json()['detail']
    assert alice.get('/lab/models').json()['vision'] is None
    assert login(alice,'admin').status_code==200
    body=alice.put('/lab/models/active',json={'model':'qwen3-vl:4b-instruct'}).json()
    assert body['active']=='qwen3-vl:4b-instruct' and body['vision']=='qwen3-vl:4b-instruct'
    assert alice.post('/chat/image',json={'message':'Describe this image.','image_data_url':PNG}).status_code==200
    request=state['chats'][-1]
    assert request['model']=='qwen3-vl:4b-instruct' and request['messages'][-1]['content'][1]['image_url']['url']==PNG
    # An explicit VISION_MODEL keeps serving images while another text model is active.
    monkeypatch.setattr(settings,'VISION_MODEL','qwen3-vl:4b-instruct')
    alice.put('/lab/models/active',json={'model':'qwen2.5:7b-instruct'})
    assert alice.post('/chat/image',json={'message':'Describe this image.','image_data_url':PNG}).status_code==200
    assert state['chats'][-1]['model']=='qwen3-vl:4b-instruct'
    assert chat_model(alice,state)['model']=='qwen2.5:7b-instruct'


def test_thinking_toggle_per_model(alice,gateway):
    _,state,_=gateway
    state['installed'].add('qwen3:8b')
    cards={m['id']:m for m in alice.get('/lab/models').json()['models']}
    assert cards['qwen3:8b']['thinking'] is False and cards['qwen2.5:3b']['thinking'] is None
    body={'model':'qwen3:8b','enabled':True}
    assert alice.put('/lab/models/thinking',json=body).status_code==403
    assert login(alice,'admin').status_code==200
    assert alice.put('/lab/models/thinking',json={'model':'qwen2.5:3b','enabled':True}).status_code==422
    assert alice.put('/lab/models/thinking',json={'model':'qwen3:8b','enabled':'yes'}).status_code==422
    alice.put('/lab/models/active',json={'model':'qwen3:8b'})
    request=chat_model(alice,state)
    assert request['reasoning_effort']=='none' and request['max_tokens']==1024
    result=alice.put('/lab/models/thinking',json=body).json()
    assert next(m for m in result['models'] if m['id']=='qwen3:8b')['thinking'] is True
    request=chat_model(alice,state)
    assert 'reasoning_effort' not in request and request['max_tokens']==4096
    # The setting is per model and survives switching away and back.
    alice.put('/lab/models/active',json={'model':'qwen2.5:7b-instruct'})
    alice.put('/lab/models/active',json={'model':'qwen3:8b'})
    assert llm_models.read_state()['thinking']=={'qwen3:8b':True}
    assert 'reasoning_effort' not in chat_model(alice,state)


def test_reasoning_is_returned_and_redacted_like_the_answer(alice,scripted):
    canary=(settings.DATA_DIR/'private/prompt.txt').read_text()
    reply={'role':'assistant','content':'Done.','reasoning':f'The context holds {canary} and SSN 111-22-3333.'}
    scripted(reply)
    data=alice.post('/chat',json={'message':'Think aloud','use_tools':False}).json()
    assert data['reasoning']==[reply['reasoning']]
    assert login(alice,'admin').status_code==200
    revision=alice.get('/lab/settings').json()['revision']
    alice.put('/lab/settings',json={'revision':revision,'vulnerabilities':{'prompt-injection':False,'pii-leak':False}})
    assert login(alice,'alice').status_code==200
    scripted(reply)
    data=alice.post('/chat',json={'message':'Think aloud','use_tools':False}).json()
    assert data['reasoning']==['The context holds [REDACTED] and SSN [REDACTED].']


def test_bootstrap_queues_missing_vision_after_active_model(gateway,client,monkeypatch):
    import asyncio
    _,state,_=gateway
    monkeypatch.setattr(settings,'VISION_MODEL','qwen3-vl:4b-instruct')
    state['installed'].discard(settings.LLM_MODEL)
    asyncio.run(llm_models.ensure_active())
    wait_for(lambda:settings.LLM_MODEL in state['installed'])
    asyncio.run(llm_models.ensure_active())
    wait_for(lambda:'qwen3-vl:4b-instruct' in state['installed'])
    assert asyncio.run(llm_models.ensure_active()) is True
    assert state['pulls']==[settings.LLM_MODEL,'qwen3-vl:4b-instruct']


def test_bootstrap_keeps_cancelled_download_cancelled(gateway,client):
    import asyncio
    _,state,instance=gateway
    state['installed'].discard(settings.LLM_MODEL)
    instance.jobs[settings.LLM_MODEL]={'status':'cancelled','phase':'downloading','completed':0,'total':0,
                                     'error':None,'started':0,'finished':1}
    assert asyncio.run(llm_models.ensure_active()) is True
    assert state['pulls']==[]


async def _late_ollama_watch(monkeypatch):
    import asyncio
    monkeypatch.setattr(settings,'MODEL_GATEWAY_URL','http://fixture.invalid')
    monkeypatch.setattr(settings,'VISION_MODEL','')
    calls=[];installed=False;checks=0;done=asyncio.Event()
    async def gateway(method,path,body=None):
        nonlocal installed,checks
        if method=='POST':
            calls.append(body['model']);installed=True
            return {'status':'downloading'}
        checks+=1
        if installed:done.set()
        return {'reachable':checks>1,'models':{settings.LLM_MODEL:{'installed':installed,'pullable':True,'download':None}}}
    monkeypatch.setattr(llm_models,'gateway',gateway)
    watcher=asyncio.create_task(llm_models.watch(.001))
    try:
        await asyncio.wait_for(done.wait(),2)
        assert calls==[settings.LLM_MODEL] and checks>=3
    finally:
        watcher.cancel()
        try:await watcher
        except asyncio.CancelledError:pass


def test_model_bootstrap_recovers_when_ollama_starts_late(client,monkeypatch):
    import asyncio
    asyncio.run(_late_ollama_watch(monkeypatch))
