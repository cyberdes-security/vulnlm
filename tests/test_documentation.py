"""Execute published examples; keep API contracts, links and translations reviewable."""
import ast
import base64
import json
import re
import subprocess
import time
import uuid
from pathlib import Path
from urllib.parse import unquote

import pytest
from fastapi.testclient import TestClient
from main import app
from scenario_controls import IDS

ROOT = Path(__file__).resolve().parents[1]
DOCS = [*sorted(ROOT.glob('*.md')), *sorted((ROOT/'docs').glob('*.md'))]


def blocks(path, language):
    return re.findall(r'^```'+language+r'\n(.*?)^```', path.read_text(), re.M|re.S)


def example(path, control):
    section = path.read_text().split(f'<!-- example:{control} -->', 1)[1]
    section = re.split(r'<a id="control-|\n## ', section, maxsplit=1)[0]
    return re.search(r'```python\n(.*?)\n```', section, re.S)[1]


def expect(response, status=200):
    assert response.status_code == status, (response.status_code, response.text)
    return response.json() if 'application/json' in response.headers.get('content-type', '') else response.text


def test_documentation_code_blocks_compile():
    for path in DOCS:
        for index, code in enumerate(blocks(path, 'python')):
            compile(code, f'{path.name}:python:{index}', 'exec')
        for code in blocks(path, 'bash'):
            result = subprocess.run(['bash','-n'], input=code, text=True, capture_output=True)
            assert result.returncode == 0, (path, result.stderr)


def anchors(path):
    text = re.sub(r'```.*?```', '', path.read_text(), flags=re.S)
    found = set(re.findall(r'<a id="([^"]+)"', text))
    duplicates = {}
    for heading in re.findall(r'^#{1,6} (.+)$', text, re.M):
        slug = re.sub(r'[^\w\- ]', '', heading.lower()).replace(' ', '-')
        count = duplicates.get(slug, 0)
        found.add(slug if not count else f'{slug}-{count}')
        duplicates[slug] = count+1
    return found


def test_local_documentation_links():
    errors = []
    for path in DOCS:
        for link in re.findall(r'\[[^\]]+\]\(([^)]+)\)', path.read_text()):
            if re.match(r'[a-z]+:', link):
                continue
            filename, _, fragment = unquote(link).partition('#')
            target = (path.parent / filename).resolve() if filename else path
            if not target.exists():
                errors.append(f'{path.name}: missing {link}')
            elif fragment and target.suffix == '.md' and fragment not in anchors(target):
                errors.append(f'{path.name}: missing anchor {link}')
    assert not errors, '\n'.join(errors)


def test_all_controls_have_contracts_in_both_languages():
    for name in ('walkthrough.tr.md','walkthrough.md'):
        text = (ROOT/'docs'/name).read_text()
        controls = re.findall(r'<a id="control-([^"]+)"', text)
        assert len(controls) == len(set(controls)) == 40
        assert set(controls) == set(IDS)


# These examples perform real SQL/Chroma/file/tool operations, without a model.
DIRECT = [
    'rag-tenants', 'tool-poisoning', 'tool-rug-pull', 'excessive-agency',
    'shell-rce', 'python-execution', 'sql-injection', 'path-traversal',
    'mass-assignment', 'jwt-none', 'document-idor', 'ping-injection', 'debug-config',
    'tool-argument-override', 'ownership-spoofing', 'stale-jwt-role',
    'session-lifecycle', 'audit-gap', 'transaction-replay', 'transfer-validation',
    'memory-disclosure', 'tool-result-injection', 'approval-mismatch',
    'rag-rank-crowding', 'agent-impersonation',
]


@pytest.fixture
def doc_clients(client):
    alice = client
    bob, admin = TestClient(app), TestClient(app)
    for session, name in ((alice,'alice'),(bob,'bob'),(admin,'admin')):
        expect(session.post('/auth/login', json={'email':name+'@lab.local','password':name+'-lab'}))
    state = expect(admin.get('/lab/settings'))
    expect(admin.put('/lab/settings', json={'revision':state['revision'], 'vulnerabilities':dict.fromkeys(IDS, True)}))
    yield {'c':alice, 'bob':bob, 'admin':admin, 'expect':expect, 'base64':base64,
           'json':json, 'time':time, 'uuid':uuid, 'Path':Path}
    bob.close(); admin.close()


@pytest.mark.parametrize('control', DIRECT)
def test_published_vulnerable_api_example(control, doc_clients):
    english = example(ROOT/'docs/walkthrough.md', control)
    turkish = example(ROOT/'docs/walkthrough.tr.md', control)
    assert ast.dump(ast.parse(english)) == ast.dump(ast.parse(turkish)), control
    exec(compile(english, f'walkthrough:{control}', 'exec'), doc_clients)


@pytest.mark.parametrize('number', [1,2,3,4])
def test_published_extended_example(number, doc_clients):
    codes=[]
    for name in ('extended-scenarios.md','extended-scenarios.tr.md'):
        section=re.search(r'^## '+str(number)+r'\. (.*?)(?=^## |\Z)',
                          (ROOT/'docs'/name).read_text(), re.M|re.S)[0]
        codes.append(re.search(r'```python\n(.*?)\n```', section, re.S)[1])
    assert ast.dump(ast.parse(codes[0])) == ast.dump(ast.parse(codes[1]))
    exec(compile(codes[0], f'extended:{number}', 'exec'), doc_clients)


def test_literal_api_calls_reference_real_routes():
    errors=[]
    endpoints=[(re.compile(re.sub(r'\\\{[^}]+\\\}', r'[^/]+', re.escape(path))), method)
               for path, operations in app.openapi()['paths'].items() for method in operations]
    for path in DOCS:
        for code in blocks(path, 'python'):
            for node in ast.walk(ast.parse(code)):
                if not (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
                        and node.func.attr in {'get','post','put','delete','patch'} and node.args):
                    continue
                url=node.args[0]
                if not (isinstance(url, ast.Constant) and isinstance(url.value,str) and url.value.startswith('/')):
                    continue
                if not any(pattern.fullmatch(url.value) and node.func.attr == method
                           for pattern, method in endpoints):
                    errors.append(f'{path.name}: {node.func.attr.upper()} {url.value}')
    assert not errors, '\n'.join(errors)
