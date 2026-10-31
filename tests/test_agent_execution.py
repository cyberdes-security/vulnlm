"""Repeated model calls must not repeat effects or consume guessed dependencies."""
import json
from fastapi import HTTPException
from agent_execution import call_key
from test_lab import model_call, sql


def message(*calls):
    result={'role':'assistant','content':None,'tool_calls':[]}
    for index,call in enumerate(calls):
        item=call['tool_calls'][0].copy()
        item['id']=f'batch_{index}'
        result['tool_calls'].append(item)
    return result


def test_dependency_batch_replans_before_remembering(alice,scripted):
    first=message(model_call('read_file',path='hello.txt'),
                  model_call('remember',content='The content of hello.txt'))
    second=message(model_call('read_file',path='hello.txt'),
                   model_call('remember',content='Public lab file\n'))
    captured=scripted(first,second,'Saved the actual content.')
    response=alice.post('/chat',json={'message':'Read hello.txt, then remember its exact content.'})
    assert response.status_code==200,response.text
    data=response.json()
    assert (data['tool_executions'],data['tool_reuses'],data['tool_deferred'])==(2,1,1)
    assert [item['executed'] for item in data['tools']]==[True,False,False,True]
    assert alice.get('/memory').json()==[{'id':1,'owner_id':1,'content':'Public lab file\n'}]
    results=[m for m in captured[1]['messages'] if m['role']=='tool']
    assert len(results)==1 and results[0]['tool_call_id']=='batch_0'
    assert 'The content of hello.txt' not in json.dumps(captured[1]['messages'])
    assistant=captured[1]['messages'][-2]
    assert [c['function']['name'] for c in assistant['tool_calls']]==['read_file']


def test_identical_calls_in_same_batch_and_later_round_have_one_effect(alice,scripted):
    repeated=model_call('remember',content='ONE_EFFECT')
    renamed=json.loads(json.dumps(repeated)); renamed['tool_calls'][0]['id']='new_transport_id'
    scripted(message(repeated,repeated),renamed,'Done')
    data=alice.post('/chat',json={'message':'Remember the note.'}).json()
    assert data['tool_executions']==1 and data['tool_reuses']==2
    assert len(alice.get('/memory').json())==1
    assert all(item['result']==data['tools'][0]['result'] for item in data['tools'])
    assert data['tools'][-1]['id']=='new_transport_id'
    assert data['tools'][-1]['duplicate_of']=='batch_0'


def test_reordered_arguments_and_equal_numeric_spellings_reuse_transfer(alice,scripted):
    scripted(model_call('transfer_funds',from_user_id=1,to_user_id=2,amount=7),
             model_call('transfer_funds',amount=7.0,to_user_id=2,from_user_id=1),'Done')
    data=alice.post('/chat',json={'message':'Transfer 7 credits.'}).json()
    assert data['tool_executions']==1 and data['tool_reuses']==1
    assert alice.get('/me').json()['balance']=='993.00'
    assert sql(alice,'SELECT COUNT(*) AS n FROM transactions')[0]['n']==1


def test_failed_call_with_committed_effect_is_not_retried(alice,scripted,monkeypatch):
    import tools
    actual=tools.execute
    attempts=[]
    async def partial_failure(*args,**kwargs):
        attempts.append(args[0])
        await actual(*args,**kwargs)  # remember committed before a downstream error.
        raise HTTPException(502,'Synthetic failure after commit')
    monkeypatch.setattr(tools,'execute',partial_failure)
    scripted(model_call('remember',content='COMMITTED_ONCE'),
             model_call('remember',content='COMMITTED_ONCE'),'The attempt failed.')
    data=alice.post('/chat',json={'message':'Remember this note.'}).json()
    assert attempts==['remember']
    assert len(alice.get('/memory').json())==1
    assert data['tools'][0]['error'] and data['tools'][1]['error']
    assert data['tools'][1]['reused'] and not data['tools'][1]['executed']


def test_receipts_do_not_cross_requests_or_fix_the_replay_exercise(alice,scripted):
    scripted(model_call('transfer_funds',from_user_id=1,to_user_id=2,amount=5),'First transfer')
    first=alice.post('/chat',json={'message':'Transfer five credits.'},headers={'Idempotency-Key':'repeated-request'}).json()
    scripted(model_call('transfer_funds',from_user_id=1,to_user_id=2,amount=5),'Second transfer')
    second=alice.post('/chat',json={'message':'Transfer five again.','conversation_id':first['conversation_id']},
                      headers={'Idempotency-Key':'repeated-request'}).json()
    assert first['tool_executions']==second['tool_executions']==1
    assert first['tool_reuses']==second['tool_reuses']==0
    assert alice.get('/me').json()['balance']=='990.00'
    assert sql(alice,'SELECT COUNT(*) AS n FROM transactions')[0]['n']==2


def test_deferred_distinct_action_can_be_replanned_and_executed(alice,scripted):
    scripted(message(model_call('remember',content='FIRST'),model_call('remember',content='SECOND')),
             model_call('remember',content='SECOND'),'Done')
    data=alice.post('/chat',json={'message':'Remember two different notes.'}).json()
    assert data['tool_executions']==2 and data['tool_deferred']==1
    assert {m['content'] for m in alice.get('/memory').json()}=={'FIRST','SECOND'}


def test_call_fingerprint_preserves_types_and_nested_values():
    def key(args):return call_key({'name':'test','arguments':args})
    assert key({'amount':7,'nested':{'a':[1,2],'b':'x'}})==key({'nested':{'b':'x','a':[1.0,2.0]},'amount':7.0})
    assert key({'value':True})!=key({'value':1})
    assert key({'value':'7'})!=key({'value':7})
    assert key({'value':10**40})!=key({'value':10**40+1})
