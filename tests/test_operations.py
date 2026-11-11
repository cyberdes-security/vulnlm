"""Schema adoption, operational diagnostics and provenance controls."""
import io
import json
import logging
import pytest
from sqlalchemy import create_engine, inspect, select, text
from migrations import upgrade, revisions, HEAD, v001_initial
from observability import logger, JSONFormatter, OperationalMiddleware
from test_lab import login
from test_scenario_controls import configure


def test_legacy_migration_preserves_data_and_does_not_infer_trust(tmp_path):
    engine = create_engine('sqlite:///'+str(tmp_path/'legacy.db'))
    with engine.begin() as connection:
        v001_initial.upgrade(connection)
        connection.execute(text("INSERT INTO users (id,name) VALUES (91,'Existing operator data')"))
        connection.execute(text("INSERT INTO documents (id,title,source,owner_id,content) VALUES (91,'Existing','handbook',91,'keep this')"))
    for _ in range(2):
        with engine.begin() as connection:
            assert upgrade(connection) == HEAD
            assert connection.execute(select(revisions.c.revision).order_by(revisions.c.revision)).scalars().all() == [1,2,3,4,5]
            assert not inspect(connection).has_table('tool_result_fixtures')
            assert connection.execute(text('SELECT content FROM documents WHERE id=91')).scalar() == 'keep this'
            assert connection.execute(text('SELECT count(*) FROM document_trust')).scalar() == 0
    engine.dispose()


def test_migration_rejects_future_revisions_without_modification(tmp_path):
    engine=create_engine('sqlite:///'+str(tmp_path/'future.db'))
    with engine.begin() as connection:
        upgrade(connection)
        connection.execute(revisions.insert().values(revision=99))
    with pytest.raises(RuntimeError, match='Unsupported database revision'):
        with engine.begin() as connection:
            upgrade(connection)
    with engine.connect() as connection:
        assert connection.execute(select(revisions.c.revision).where(revisions.c.revision==99)).scalar()==99
    engine.dispose()


def test_failed_schema_upgrade_rolls_back(tmp_path, monkeypatch):
    from migrations import v002_document_trust
    engine=create_engine('sqlite:///'+str(tmp_path/'rollback.db'))
    def fail(connection):
        connection.exec_driver_sql('CREATE TABLE partial_migration (id INTEGER)')
        raise RuntimeError('simulated migration failure')
    with monkeypatch.context() as patch:
        patch.setattr(v002_document_trust,'upgrade',fail)
        with pytest.raises(RuntimeError,match='simulated'):
            with engine.begin() as connection:
                upgrade(connection)
    with engine.begin() as connection:
        assert not inspect(connection).has_table('partial_migration')
        assert upgrade(connection)==HEAD
    engine.dispose()


def test_provenance_requires_real_operator_and_does_not_trust_source(alice):
    new=alice.post('/upload_doc',json={'title':'Spoofed handbook','content':'RANKING_PROBE','source':'handbook','trusted':True}).json()['id']
    assert alice.put(f'/lab/documents/{new}/trust',json={'trusted':True}).status_code==403
    forged=alice.post('/auth/login',json={'email':'admin@lab.local','password':'admin-lab'}).json()['access_token']
    login(alice,'alice')
    assert alice.put(f'/lab/documents/{new}/trust',json={'trusted':True},headers={'Authorization':'Bearer '+forged}).status_code==403
    login(alice,'admin')
    rows=alice.get('/lab/documents').json()
    assert next(d for d in rows if d['id']==new)['trusted'] is False
    assert alice.put(f'/lab/documents/{new}/trust',json={'trusted':True},headers={'Origin':'http://evil.example'}).status_code==403
    assert alice.put(f'/lab/documents/{new}/trust',json={'trusted':'yes'}).status_code==422
    assert alice.put(f'/lab/documents/{new}/trust',json={'trusted':True}).json()['trusted'] is True
    assert alice.put(f'/lab/documents/{new}/trust',json={'trusted':False}).json()['trusted'] is False


def test_approved_arbitrary_document_survives_crowding_and_revocation(alice):
    query='quarterly cedar payroll ranking probe'
    trusted=alice.post('/upload_doc',json={'title':'Operator approved reference','content':'reference '+query,'source':'uploaded'}).json()['id']
    configure(alice,{'rag-rank-crowding':False})
    login(alice,'admin')
    alice.put(f'/lab/documents/{trusted}/trust',json={'trusted':True}).raise_for_status()
    login(alice,'alice')
    for _ in range(5):
        alice.post('/upload_doc',json={'title':query,'content':query,'source':'handbook'}).raise_for_status()
    results=alice.get('/rag/search',params={'query':query}).json()
    assert any(d['id']==f'doc:{trusted}' and d['trusted'] for d in results)
    assert len([d for d in results if d['content']==query])<=1
    configure(alice,{'rag-rank-crowding':True})
    vulnerable=alice.get('/rag/search',params={'query':query}).json()
    assert len(vulnerable)==3 and all(d['content']==query for d in vulnerable)
    assert all(d['id']!=f'doc:{trusted}' for d in vulnerable)
    # Approval never bypasses tenant ownership.
    configure(alice,{'rag-rank-crowding':False,'rag-tenants':False})
    login(alice,'bob')
    assert all(d['owner_id']==2 for d in alice.get('/rag/search',params={'query':query}).json())
    login(alice,'admin')
    alice.put(f'/lab/documents/{trusted}/trust',json={'trusted':False}).raise_for_status()
    configure(alice,{'rag-tenants':True})
    login(alice,'alice')
    results=alice.get('/rag/search',params={'query':query}).json()
    assert not any(d['id']==f'doc:{trusted}' and d['trusted'] for d in results)


def test_readiness_and_metrics_require_actual_dependencies(gateway, alice):
    assert alice.get('/health').status_code==200
    assert alice.get('/ready').json()['checks']=={'database':'ok','rag':'ok','model':'ok'}
    gateway[1]['installed'].clear()
    ready=alice.get('/ready')
    assert ready.status_code==503 and ready.json()['checks']['model']=='not_ready'
    assert alice.get('/lab/metrics').status_code==403
    login(alice,'admin')
    response=alice.get('/lab/metrics')
    assert response.status_code==200
    assert 'vulnlm_http_requests_total' in response.text
    assert 'vulnlm_http_request_duration_seconds_sum' in response.text


def test_request_logs_omit_payloads_and_queries(client):
    stream=io.StringIO()
    handler=logging.StreamHandler(stream); handler.setFormatter(JSONFormatter())
    logger.addHandler(handler)
    try:
        response=client.post('/auth/login?secret=QUERY_CANARY',json={'email':'BODY_CANARY','password':'PASSWORD_CANARY'})
        assert response.status_code==401 and len(response.headers['x-request-id'])==32
        client.get('/missing/PRIVATE_PATH_CANARY')
    finally:
        logger.removeHandler(handler)
    output=stream.getvalue()
    assert not any(value in output for value in ['QUERY_CANARY','BODY_CANARY','PASSWORD_CANARY','PRIVATE_PATH_CANARY'])
    events=[json.loads(line) for line in output.splitlines()]
    assert any(event.get('route')=='/auth/login' and event['status']==401 for event in events)
    assert any(event.get('route')=='unmatched' for event in events)


@pytest.mark.asyncio
async def test_unexpected_error_has_safe_log_and_correlated_response():
    stream=io.StringIO(); handler=logging.StreamHandler(stream); handler.setFormatter(JSONFormatter())
    logger.addHandler(handler)
    messages=[]
    async def failed(scope,receive,send):
        raise RuntimeError('DO_NOT_LOG_THIS_SECRET')
    async def receive(): return {'type':'http.request','body':b''}
    async def send(message): messages.append(message)
    try:
        await OperationalMiddleware(failed)({'type':'http','method':'GET','path':'/','headers':[]},receive,send)
    finally:
        logger.removeHandler(handler)
    payload=json.loads(messages[-1]['body'])
    header=dict(messages[0]['headers'])[b'x-request-id'].decode()
    assert messages[0]['status']==500 and payload['request_id']==header
    assert header in stream.getvalue() and 'DO_NOT_LOG_THIS_SECRET' not in stream.getvalue()
    assert 'RuntimeError' in stream.getvalue()


def test_setup_screen_is_public_and_reports_missing_model(gateway,client):
    page=client.get('/setup')
    assert page.status_code==200 and 'setup-refresh' in page.text
    response=client.get('/setup/status')
    assert response.status_code==200 and response.json()['status']=='ready'
    assert response.json()['model_source']=='host'
    gateway[1]['installed'].clear()
    response=client.get('/setup/status')
    assert response.status_code==503
    assert response.json()['checks']['model']=='not_ready'
    assert 'upstream_host' not in response.text and 'password' not in response.text


def test_setup_status_reports_download_progress_without_upstream_errors(gateway,client):
    state=gateway[1]
    state['installed'].discard('qwen2.5:3b')
    import model_gateway
    instance=gateway[2]
    instance.jobs['qwen2.5:3b']={'status':'downloading','phase':'downloading','completed':100,'total':200,
                              'error':'DO_NOT_EXPOSE_INTERNAL_ERROR','started':0,'finished':None}
    response=client.get('/setup/status')
    assert response.status_code==503
    assert response.json()['download']=={'phase':'downloading','completed':100,'total':200}
    assert 'DO_NOT_EXPOSE_INTERNAL_ERROR' not in response.text
