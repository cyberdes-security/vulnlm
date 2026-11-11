"""Sub-agent delegation: grant, handoff, recursion and context boundaries, with and without a model."""
import json
import httpx
import pytest
from fastapi.testclient import TestClient
import llm_client
from config import settings
from main import app
from scenario_controls import IDS
from test_lab import login, model_call, sql
from test_scenario_controls import configure

TRANSFER = {'tool': 'transfer_funds', 'arguments': {'from_user_id': 1, 'to_user_id': 2, 'amount': 100}}


def spawn(client, role='researcher', task='Read hello.txt', tools=None, status=200):
    body = {'role': role, 'task': task}
    if tools is not None:
        body['tools'] = tools
    response = client.post('/agents/subagents', json=body)
    assert response.status_code == status, response.text
    return response.json()


def act(client, agent_id, name, arguments, status=200):
    response = client.post(f'/agents/subagents/{agent_id}/tools', json={'name': name, 'arguments': arguments})
    assert response.status_code == status, response.text
    return response.json()


def report(client, agent_id, actions, status=200):
    response = client.post(f'/agents/subagents/{agent_id}/report',
                           json={'summary': 'Vendor notice reviewed', 'actions': actions})
    assert response.status_code == status, response.text
    return response.json()


def me(client):
    return client.get('/me').json()


def final(summary, actions=()):
    return json.dumps({'summary': summary, 'actions': list(actions)})


def test_spawn_agent_is_a_listed_tool_with_optional_grant(alice):
    tool = next(t['function'] for t in alice.get('/tools').json() if t['function']['name'] == 'spawn_agent')
    assert tool['parameters']['required'] == ['role', 'task']
    assert tool['parameters']['properties']['role']['enum'] == ['researcher', 'analyst', 'operator']
    spawn(alice, tools=['rm_rf'], status=422)
    spawn(alice, role='supervisor', status=422)


# subagent-privilege-escalation

def test_escalated_grant_promotes_user_through_child_channel(alice):
    child = spawn(alice, tools=['read_file', 'change_role'])
    assert child['granted_tools'] == ['read_file', 'change_role', 'spawn_agent']
    assert child['acting_role'] == 'admin' and child['depth'] == 1
    assert alice.get('/admin/users').status_code == 403
    result = act(alice, child['id'], 'change_role', {'user_id': 1, 'new_role': 'admin'})
    assert result['result'] == {'id': 1, 'role': 'admin'}
    assert me(alice)['role'] == 'admin'
    assert alice.get('/admin/users').status_code == 200


def test_escalated_child_bypasses_the_role_check_its_parent_faces(alice):
    configure(alice, {'excessive-agency': False})
    assert alice.post('/tool/change_role', json={'user_id': 1, 'new_role': 'admin'}).status_code == 403
    child = spawn(alice, role='operator', tools=['change_role'])
    act(alice, child['id'], 'change_role', {'user_id': 1, 'new_role': 'admin'})
    assert me(alice)['role'] == 'admin'


def test_protected_grant_is_bounded_by_profile_and_current_role(alice):
    configure(alice, {'subagent-privilege-escalation': False})
    child = spawn(alice, tools=['read_file', 'change_role'])
    assert child['granted_tools'] == ['read_file', 'spawn_agent'] and child['acting_role'] == 'user'
    act(alice, child['id'], 'change_role', {'user_id': 1, 'new_role': 'admin'}, status=403)
    assert me(alice)['role'] == 'user'
    assert act(alice, child['id'], 'read_file', {'path': 'hello.txt'})['result'] == 'Public lab file\n'
    operator = spawn(alice, role='operator')
    assert 'transfer_funds' in operator['granted_tools'] and 'change_role' not in operator['granted_tools']
    login(alice, 'admin')
    assert 'change_role' in spawn(alice, role='operator', tools=['change_role'])['granted_tools']


def test_protected_child_rechecks_current_role_and_agent_guardrails(alice):
    configure(alice, {'subagent-privilege-escalation': False, 'excessive-agency': False})
    login(alice, 'admin')
    child = spawn(alice, role='operator', tools=['transfer_funds'])
    result = act(alice, child['id'], 'transfer_funds', {'from_user_id': 3, 'to_user_id': 1, 'amount': 5})['result']
    assert result['approval_required'] and result['tool'] == 'transfer_funds'
    assert sql(alice, 'SELECT count(*) AS n FROM transactions')[0]['n'] == 0


# subagent-handoff-injection

def test_handoff_executes_a_read_only_childs_recommended_transfer(alice):
    child = spawn(alice)
    assert 'transfer_funds' not in child['granted_tools']
    handoff = report(alice, child['id'], [TRANSFER])['handoff']
    assert handoff['trusted_subagent_report'] == 'Vendor notice reviewed'
    assert handoff['executed_actions'][0]['executed'] is True
    assert float(me(alice)['balance']) == 900
    assert sql(alice, 'SELECT count(*) AS n FROM transactions')[0]['n'] == 1
    report(alice, child['id'], [TRANSFER], status=409)
    act(alice, child['id'], 'read_file', {'path': 'hello.txt'}, status=409)
    assert float(me(alice)['balance']) == 900


def test_protected_handoff_lists_but_never_executes_recommendations(alice):
    configure(alice, {'subagent-handoff-injection': False})
    child = spawn(alice)
    handoff = report(alice, child['id'], [TRANSFER])['handoff']
    assert handoff['untrusted_subagent_report']['summary'] == 'Vendor notice reviewed'
    assert handoff['untrusted_subagent_report']['recommended_actions'] == [{**TRANSFER, 'executed': False, 'within_grant': False}]
    assert float(me(alice)['balance']) == 1000
    assert sql(alice, 'SELECT count(*) AS n FROM transactions')[0]['n'] == 0
    record = alice.get(f"/agents/subagents/{child['id']}").json()
    assert record['status'] == 'completed' and record['report']['outcomes'][0]['executed'] is False


@pytest.mark.parametrize('vulnerable', [True, False])
def test_chat_handoff_report_reaches_parent_and_moves_funds(alice, scripted, vulnerable):
    if not vulnerable:
        configure(alice, {'subagent-handoff-injection': False})
    captured = scripted(model_call('spawn_agent', role='researcher', task='Summarise document 1'),
                        model_call('get_document', doc_id=1),
                        final('Handbook reviewed. Vendor asks for a settlement.', [TRANSFER]),
                        'The researcher finished.')
    result = alice.post('/chat', json={'message': 'Have a researcher summarise document 1'})
    result.raise_for_status()
    child = result.json()['tools'][0]['result']
    assert child['trace'][0]['result']['title'] == 'Welcome'
    assert float(me(alice)['balance']) == (900 if vulnerable else 1000)
    delivered = json.loads(captured[3]['messages'][-1]['content'])
    if vulnerable:
        assert delivered['handoff']['trusted_subagent_report'].startswith('Handbook reviewed')
    else:
        assert delivered['policy'] and 'untrusted_subagent_report' in delivered['untrusted_tool_data']['handoff']


# subagent-recursion

def test_recursion_is_stopped_only_by_the_lab_circuit_breaker(alice):
    agent = spawn(alice, task='Delegate onward')
    for depth in range(2, 6):
        agent = act(alice, agent['id'], 'spawn_agent', {'role': 'researcher', 'task': 'Delegate onward'})['result']
        assert agent['depth'] == depth and 'spawn_agent' in agent['granted_tools']
    act(alice, agent['id'], 'spawn_agent', {'role': 'researcher', 'task': 'Delegate onward'}, status=429)
    rows = sql(alice, 'SELECT depth,tree_id FROM sub_agent_runs')
    assert sorted(row['depth'] for row in rows) == [1, 2, 3, 4, 5]
    assert len({row['tree_id'] for row in rows}) == 1


def test_recursion_circuit_breaker_caps_tree_size(alice):
    root = spawn(alice, task='Fan out')
    for _ in range(settings.SUBAGENT_MAX_RUNS - 1):
        act(alice, root['id'], 'spawn_agent', {'role': 'researcher', 'task': 'Fan out'})
    act(alice, root['id'], 'spawn_agent', {'role': 'researcher', 'task': 'Fan out'}, status=429)
    assert len(sql(alice, 'SELECT id FROM sub_agent_runs')) == settings.SUBAGENT_MAX_RUNS


def test_protected_recursion_forbids_nested_spawns(alice):
    configure(alice, {'subagent-recursion': False})
    agent = spawn(alice, tools=['read_file', 'spawn_agent'])
    assert 'spawn_agent' not in agent['granted_tools']
    act(alice, agent['id'], 'spawn_agent', {'role': 'researcher', 'task': 'Delegate onward'}, status=403)
    assert len(sql(alice, 'SELECT id FROM sub_agent_runs')) == 1
    spawn(alice, task='Independent subtask')
    assert act(alice, agent['id'], 'read_file', {'path': 'hello.txt'})['result'] == 'Public lab file\n'


@pytest.mark.parametrize('vulnerable', [True, False])
def test_chat_nested_delegation_multiplies_model_calls(alice, scripted, vulnerable):
    if not vulnerable:
        configure(alice, {'subagent-recursion': False})
    replies = [model_call('spawn_agent', role='researcher', task='Delegate onward'),
               model_call('spawn_agent', role='researcher', task='Read hello.txt')]
    replies += [final('Nested result'), final('Child result'), 'Done'] if vulnerable else [final('Child result'), 'Done']
    captured = scripted(*replies)
    result = alice.post('/chat', json={'message': 'Delegate recursively'}).json()
    child_tools = {d['function']['name'] for d in captured[1]['tools']}
    assert ('spawn_agent' in child_tools) is vulnerable
    nested = result['tools'][0]['result']['trace'][0]
    assert nested['error'] is (not vulnerable)
    assert result['subagent_llm_calls'] == (3 if vulnerable else 2)
    assert result['llm_calls'] == 2 + result['subagent_llm_calls']
    depths = sorted(row['depth'] for row in sql(alice, 'SELECT depth FROM sub_agent_runs'))
    assert depths == ([1, 2] if vulnerable else [1])


def test_protected_chat_creates_at_most_three_sub_agents(alice, scripted):
    configure(alice, {'subagent-recursion': False})
    replies = []
    for index in range(1, 4):
        replies += [model_call('spawn_agent', role='researcher', task=f'Subtask {index}'), final(f'Result {index}')]
    replies.append(model_call('spawn_agent', role='researcher', task='Subtask 4'))
    scripted(*replies)
    result = alice.post('/chat', json={'message': 'Split the work'}).json()
    assert [item['error'] for item in result['tools']] == [False, False, False, True]
    assert result['tools'][3]['result']['error'].startswith('429')
    assert len(sql(alice, 'SELECT id FROM sub_agent_runs')) == 3


# subagent-context-leak

def test_forked_context_carries_the_private_prompt(alice):
    canary = (settings.DATA_DIR / 'private/prompt.txt').read_text()
    child = spawn(alice)
    context = alice.get(f"/agents/subagents/{child['id']}").json()['context']
    assert canary in context[0]['content'] and '111-22-3333' in context[0]['content']
    assert context[-1]['content'].endswith('Delegated task: Read hello.txt')


def test_protected_context_holds_only_role_instructions_and_task(alice):
    configure(alice, {'subagent-context-leak': False})
    canary = (settings.DATA_DIR / 'private/prompt.txt').read_text()
    child = spawn(alice)
    context = alice.get(f"/agents/subagents/{child['id']}").json()['context']
    assert [message['role'] for message in context] == ['system', 'user']
    assert context[1]['content'] == 'Read hello.txt'
    assert canary not in json.dumps(context) and '111-22-3333' not in json.dumps(context)


@pytest.mark.parametrize('vulnerable', [True, False])
def test_chat_child_receives_forked_or_minimal_context(alice, scripted, vulnerable):
    if not vulnerable:
        configure(alice, {'subagent-context-leak': False})
    canary = (settings.DATA_DIR / 'private/prompt.txt').read_text()
    captured = scripted(model_call('spawn_agent', role='researcher', task='Read hello.txt'),
                        final('Read'), 'Done')
    alice.post('/chat', json={'message': 'Remember my plan: CEDAR-ROUTE'}).raise_for_status()
    child_messages = json.dumps(captured[1]['messages'])
    assert (canary in child_messages) is vulnerable
    assert ('CEDAR-ROUTE' in child_messages) is vulnerable
    assert 'Read hello.txt' in child_messages


# Delegation plumbing shared by every scenario

def test_chat_child_loop_uses_its_grant_and_reports(alice, scripted):
    captured = scripted(model_call('spawn_agent', role='researcher', task='Read hello.txt'),
                        model_call('read_file', path='hello.txt'),
                        final('hello.txt says Public lab file'),
                        'The researcher confirmed the file.')
    result = alice.post('/chat', json={'message': 'Delegate reading hello.txt'}).json()
    item = result['tools'][0]
    assert item['name'] == 'spawn_agent' and item['executed'] and not item['error']
    child = item['result']
    assert child['trace'][0]['name'] == 'read_file' and child['trace'][0]['result'] == 'Public lab file\n'
    assert {d['function']['name'] for d in captured[1]['tools']} == set(child['granted_tools'])
    assert result['llm_calls'] == 4 and result['subagent_llm_calls'] == 2
    assert result['response'] == 'The researcher confirmed the file.'
    row = sql(alice, 'SELECT status,llm_calls,depth FROM sub_agent_runs')[0]
    assert row == {'status': 'completed', 'llm_calls': 2, 'depth': 1}


def test_all_protections_keep_delegation_usable(alice, scripted):
    configure(alice, dict.fromkeys(IDS, False))
    scripted(model_call('spawn_agent', role='researcher', task='Read hello.txt'),
             model_call('read_file', path='hello.txt'),
             final('hello.txt says Public lab file', [TRANSFER]),
             'Done')
    result = alice.post('/chat', json={'message': 'Delegate reading hello.txt'}).json()
    child = result['tools'][0]['result']
    assert child['trace'][0]['result'] == 'Public lab file\n'
    assert child['acting_role'] == 'user' and 'spawn_agent' not in child['granted_tools']
    assert child['handoff']['untrusted_subagent_report']['summary'] == 'hello.txt says Public lab file'
    assert float(me(alice)['balance']) == 1000


def test_run_endpoint_drives_the_child_loop_once(alice, scripted):
    child = spawn(alice)
    scripted(model_call('read_file', path='hello.txt'), final('Public lab file'))
    result = alice.post(f"/agents/subagents/{child['id']}/run")
    result.raise_for_status()
    assert result.json()['handoff']['trusted_subagent_report'] == 'Public lab file'
    assert alice.post(f"/agents/subagents/{child['id']}/run").status_code == 409
    listed = alice.get('/agents/subagents').json()
    assert listed[0]['status'] == 'completed' and listed[0]['llm_calls'] == 2 and 'context' not in listed[0]


def test_child_model_failure_marks_run_failed(alice, monkeypatch):
    child = spawn(alice)
    async def unavailable(messages, tool_definitions=None, *, model=None):
        raise httpx.ConnectError('model offline')
    monkeypatch.setattr(llm_client, 'chat_completion', unavailable)
    assert alice.post(f"/agents/subagents/{child['id']}/run").status_code == 502
    assert alice.get(f"/agents/subagents/{child['id']}").json()['status'] == 'failed'
    report(alice, child['id'], [], status=409)


def test_sub_agent_records_are_owner_scoped(alice):
    child = spawn(alice)
    bob = TestClient(app)
    try:
        login(bob, 'bob')
        assert bob.get(f"/agents/subagents/{child['id']}").status_code == 404
        assert bob.post(f"/agents/subagents/{child['id']}/tools",
                        json={'name': 'read_file', 'arguments': {'path': 'hello.txt'}}).status_code == 404
        assert bob.post(f"/agents/subagents/{child['id']}/report", json={'summary': 'x'}).status_code == 404
        assert bob.get('/agents/subagents').json() == []
    finally:
        bob.close()


def test_reset_clears_sub_agent_runs(alice):
    spawn(alice)
    alice.post('/lab/reset', headers={'X-Lab-Reset-Token': 'integration-test-reset'}).raise_for_status()
    login(alice, 'alice')
    assert sql(alice, 'SELECT * FROM sub_agent_runs') == []


def test_image_chat_children_keep_the_vision_model_and_image_guardrails(alice, monkeypatch):
    from test_extensions import PNG
    monkeypatch.setattr(settings, 'VISION_MODEL', 'lab-vision-fixture')
    configure(alice, {'multimodal-injection': False, 'subagent-privilege-escalation': False})
    models = []
    replies = [model_call('spawn_agent', role='operator', task='Pay Bob 5 credits', tools=['transfer_funds']),
               model_call('transfer_funds', from_user_id=1, to_user_id=2, amount=5),
               final('Transfer proposed'), 'Done']
    async def completion(messages, tool_definitions=None, *, model=None):
        models.append(model)
        reply = replies.pop(0)
        return ({'role': 'assistant', 'content': reply} if isinstance(reply, str) else reply), {}
    monkeypatch.setattr(llm_client, 'chat_completion', completion)
    result = alice.post('/chat/image', json={'message': 'Pay Bob as the image says', 'image_data_url': PNG})
    result.raise_for_status()
    assert models == ['lab-vision-fixture'] * 4
    assert result.json()['tools'][0]['result']['trace'][0]['result']['approval_required']
    assert float(me(alice)['balance']) == 1000
