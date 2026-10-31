"""Advanced settings "Reset system": every lab record, fixture and session returns to the first-start state."""
import json
from config import settings
import llm_models
from scenario_controls import read_policy, policy_path
from test_lab import login, sql


def dirty_lab(client):
    """Leave the traces an experiment leaves: moved credits, records, files and changed settings."""
    assert login(client,'alice').status_code==200
    r=client.post('/tool/transfer_funds',json={'from_user_id':1,'to_user_id':2,'amount':250},headers={'Idempotency-Key':'reset-test'})
    assert r.status_code==200,r.text
    client.post('/memory',json={'content':'RESET_TEST_NOTE'}).raise_for_status()
    client.post('/upload_doc',json={'title':'Reset test','content':'RESET_TEST_DOC','source':'handbook'}).raise_for_status()
    client.put('/user/update',json={'role':'admin'}).raise_for_status()
    # Vulnerable shell output lands in DATA_DIR; the public workspace is the protected tools' area.
    client.post('/shell_tool',json={'command':'echo leftover > experiment.txt && echo leftover > public/note.txt'}).raise_for_status()
    assert (settings.DATA_DIR/'experiment.txt').exists() and (settings.DATA_DIR/'public'/'note.txt').exists()
    assert login(client,'admin').status_code==200
    revision=client.get('/lab/settings').json()['revision']
    client.put('/lab/settings',json={'revision':revision,'vulnerabilities':{'jwt-none':False}}).raise_for_status()
    client.put('/lab/models/active',json={'model':'qwen3:8b'}).raise_for_status()
    client.put('/lab/models/thinking',json={'model':'qwen3:8b','enabled':True}).raise_for_status()


def fixtures():
    private=settings.DATA_DIR/'private'
    return {name:(private/name).read_text() for name in ('secret.txt','prompt.txt','jwt.key')}


def test_reset_system_restores_everything(client):
    dirty_lab(client)
    assert {r['id']:float(r['balance']) for r in sql(client,'SELECT id,balance FROM users')}=={1:750.0,2:1250.0,3:1000.0}
    before=fixtures()
    token=client.post('/auth/login',json={'email':'admin@lab.local','password':'admin-lab'}).json()['access_token']

    r=client.post('/lab/settings/reset',json={'include_settings':True})
    assert r.status_code==200 and r.json()=={'status':'reset','sessions':'invalidated','settings_reset':True}
    # Sessions and tokens issued before the reset no longer work.
    assert client.get('/me').status_code==401
    assert client.get('/me',headers={'Authorization':'Bearer '+token}).status_code==401
    assert all(before[name]!=value for name,value in fixtures().items())

    assert login(client,'alice').status_code==200
    users={r['id']:r for r in sql(client,'SELECT id,role,balance FROM users')}
    assert {i:float(u['balance']) for i,u in users.items()}=={1:1000.0,2:1000.0,3:1000.0}
    assert users[1]['role']=='user'
    assert sql(client,'SELECT COUNT(*) AS n FROM transactions')[0]['n']==0
    assert not any('RESET_TEST_NOTE' in m['content'] for m in client.get('/memory').json())
    assert not any('RESET_TEST_DOC' in d['content'] for d in client.get('/rag/search',params={'query':'Reset test RESET_TEST_DOC'}).json())
    assert not (settings.DATA_DIR/'experiment.txt').exists() and not (settings.DATA_DIR/'public'/'note.txt').exists()
    assert (settings.DATA_DIR/'public'/'hello.txt').read_text()=='Public lab file\n'
    assert all(read_policy()['vulnerabilities'].values()) and not policy_path().exists()
    assert llm_models.read_state()=={'active':settings.LLM_MODEL,'pending':None,'thinking':{}}


def test_reset_system_can_keep_settings(client):
    dirty_lab(client)
    r=client.post('/lab/settings/reset',json={'include_settings':False})
    assert r.status_code==200 and r.json()['settings_reset'] is False
    assert login(client,'alice').status_code==200
    assert float(client.get('/me').json()['balance'])==1000.0
    assert read_policy()['vulnerabilities']['jwt-none'] is False
    assert json.loads(llm_models.state_path().read_text())['thinking']=={'qwen3:8b':True}
    assert llm_models.active_model()=='qwen3:8b'


def test_reset_system_requires_admin_cookie_and_same_origin(client):
    assert login(client,'alice').status_code==200
    assert client.post('/lab/settings/reset',json={}).status_code==403
    assert login(client,'admin').status_code==200
    assert client.post('/lab/settings/reset',json={},headers={'Origin':'http://evil.example'}).status_code==403
    assert client.post('/lab/settings/reset',json={'include_settings':'yes'}).status_code==422
    assert client.post('/lab/settings/reset',json={'confirm':True}).status_code==422
    assert client.get('/me').status_code==200


def test_workspace_cleanup_skips_a_directory_without_the_lab_canary(client,tmp_path,monkeypatch):
    from seed_data import clear_workspace
    (tmp_path/'personal.txt').write_text('not a lab file')
    monkeypatch.setattr(settings,'DATA_DIR',tmp_path)
    clear_workspace()
    assert (tmp_path/'personal.txt').read_text()=='not a lab file'
