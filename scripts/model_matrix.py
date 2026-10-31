"""Run the lab's model-backed functions against every catalogue model in turn.

For each model the Admin account selects it through Advanced settings (downloading it first if
needed, exactly like the UI), then Alice exercises chat, tools, RAG, memory, batch, form chat and the
research agent. Deterministic checks (HTTP status, model calls, retrieval, side effects) decide
PASS/FAIL. Model-dependent outcomes are recorded as OBSERVED / NOT_OBSERVED, not as failures.

Use only your isolated lab: it creates documents, memories and model calls.
    python scripts/model_matrix.py --url http://127.0.0.1:8000 --output model-matrix.json
"""
import argparse
import json
import secrets
import time
from pathlib import Path
import httpx


def login(client, who):
    client.post('/auth/login', json={'email': f'{who}@lab.local', 'password': f'{who}-lab'}).raise_for_status()


def select(admin, model, timeout):
    """Select through the same endpoint as the UI and wait for any download to finish."""
    response = admin.put('/lab/models/active', json={'model': model})
    response.raise_for_status()
    deadline = time.monotonic() + timeout
    while True:
        state = admin.get('/lab/models').json()
        card = next(m for m in state['models'] if m['id'] == model)
        if state['active'] == model and card['installed']:
            return card
        if not state['pending'] and state['active'] != model:
            raise RuntimeError(f'download failed: {(card["download"] or {}).get("error")}')
        if time.monotonic() > deadline:
            raise TimeoutError(f'{model} was not ready after {timeout}s')
        job = card['download'] or {}
        if job.get('total'):
            print(f'  downloading {model}: {job["completed"] * 100 // job["total"]}%', flush=True)
        time.sleep(3)


class CircuitBreaker(Exception):
    pass


def run_checks(client, base_url, model):
    results = []

    def check(name, fn):
        started = time.monotonic()
        try:
            status, detail = fn()
        except CircuitBreaker:  # The lab's tool-call cap stopped the turn: a model result.
            status, detail = 'NOT_OBSERVED', 'The lab tool-call circuit breaker stopped the turn.'
        except Exception as exc:  # A transport or contract error is a failure of this check only.
            status, detail = 'FAIL', f'{type(exc).__name__}: {exc}'
        results.append({'check': name, 'status': status, 'seconds': round(time.monotonic() - started, 1), 'detail': detail})
        print(f'  {status:13} {name} ({results[-1]["seconds"]}s)', flush=True)

    def chat(message, **extra):
        response = client.post('/chat', json={'message': message, **extra})
        if response.status_code == 422 and 'circuit breaker' in response.text:
            raise CircuitBreaker()
        if response.status_code != 200:
            raise AssertionError(f'/chat HTTP {response.status_code}: {response.text[:200]}')
        return response.json()

    def health():
        active = client.get('/health').json()['llm_model']
        return ('PASS' if active == model else 'FAIL'), f'health reports {active}'

    def plain_chat():
        data = chat('In one sentence, what is prompt injection?', use_tools=False)
        ok = data['llm_calls'] == 1 and data['response'].strip() and data['usage']
        return ('PASS' if ok else 'FAIL'), data['response'][:160]

    def tool_call():
        data = chat('Use the read_file tool to read the file hello.txt and tell me its content.', use_tools=True)
        ran = [t for t in data['tools'] if t['name'] == 'read_file' and not t['error']]
        observed = any('Public lab file' in json.dumps(t['result']) for t in ran)
        return ('OBSERVED' if observed else 'NOT_OBSERVED'), {'tools': [t['name'] for t in data['tools']], 'answer': data['response'][:160]}

    # Every run uses fresh names: earlier runs leave similar documents and memories in the lab.
    def rag():
        project = 'Project ' + secrets.token_hex(3).upper()
        fact = 'CODE-' + secrets.token_hex(3).upper()
        upload = client.post('/upload_doc', json={'title': project, 'content': f'{project} handbook. The access code for {project} is {fact}.', 'source': 'handbook'})
        upload.raise_for_status()
        data = chat(f'What is the access code for {project}?', use_tools=False)
        retrieved = any(fact in doc.get('content', '') for doc in data['retrieved_docs'])
        if not retrieved:
            return 'FAIL', 'uploaded document was not retrieved'
        return ('OBSERVED' if fact in data['response'] else 'NOT_OBSERVED'), data['response'][:160]

    def memory():
        project = 'Project ' + secrets.token_hex(3).upper()
        note = 'MEMO-' + secrets.token_hex(3).upper()
        client.post('/memory', json={'content': f'For {project}, my preferred report codename is {note}.'}).raise_for_status()
        if not any(note in m['content'] for m in client.get('/memory').json()):
            return 'FAIL', 'memory was not stored'
        data = chat(f'What is my preferred report codename for {project}?', use_tools=False)
        return ('OBSERVED' if note in data['response'] else 'NOT_OBSERVED'), data['response'][:160]

    def batch():
        response = client.post('/chat/batch', json={'message': 'Reply with OK.', 'repetitions': 2})
        response.raise_for_status()
        data = response.json()
        ok = data['llm_calls'] == 2 and all(r['response'].strip() for r in data['results'])
        return ('PASS' if ok else 'FAIL'), [r['response'][:40] for r in data['results']]

    def form_chat():
        response = client.post('/chat/form', data={'message': 'Say hello in three words.'}, headers={'Origin': base_url})
        ok = response.status_code == 200 and response.json()['response'].strip()
        return ('PASS' if ok else 'FAIL'), f'HTTP {response.status_code}: {response.text[:120]}'

    def research_agent():
        response = client.post('/agents/research', json={'content': 'Synthetic vendor note: the Q3 audit closes on Friday.'})
        if response.status_code == 200:
            return 'PASS', response.json()['envelope']
        # 502 here means the model did not return the required JSON envelope: a model result.
        return ('NOT_OBSERVED' if response.status_code == 502 else 'FAIL'), f'HTTP {response.status_code}: {response.text[:160]}'

    for name, fn in [('health reports the selected model', health), ('chat', plain_chat), ('agent tool call (read_file)', tool_call),
                     ('RAG retrieval + answer', rag), ('persistent memory + answer', memory), ('batch chat', batch),
                     ('form chat', form_chat), ('research agent JSON envelope', research_agent)]:
        check(name, fn)
    return results


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--url', default='http://127.0.0.1:8000')
    parser.add_argument('--models', nargs='*', help='Catalogue model ids; default: every catalogue model')
    parser.add_argument('--download-timeout', type=int, default=3600)
    parser.add_argument('--keep', action='store_true', help='Leave the last model selected instead of restoring the previous one')
    parser.add_argument('--output', type=Path, default=Path('model-matrix-results.json'))
    args = parser.parse_args()
    report = []
    with httpx.Client(base_url=args.url, timeout=900) as admin, httpx.Client(base_url=args.url, timeout=900) as alice:
        login(admin, 'admin'); login(alice, 'alice')
        state = admin.get('/lab/models').json()
        previous = state['active']
        models = args.models or [m['id'] for m in state['models']]
        try:
            for model in models:
                print(f'== {model}', flush=True)
                try:
                    select(admin, model, args.download_timeout)
                except Exception as exc:
                    report.append({'model': model, 'selected': False, 'error': str(exc), 'checks': []})
                    print(f'  FAIL selection: {exc}', flush=True)
                    continue
                report.append({'model': model, 'selected': True, 'checks': run_checks(alice, args.url.rstrip('/'), model)})
        finally:
            if not args.keep:
                admin.put('/lab/models/active', json={'model': previous})
    args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2))
    failed = [(r['model'], c['check']) for r in report for c in r['checks'] if c['status'] == 'FAIL'] + \
             [(r['model'], 'selection') for r in report if not r['selected']]
    print(f'{len(report)} models, {len(failed)} failures' + (f': {failed}' if failed else ''))
    return int(bool(failed))


if __name__ == '__main__':
    raise SystemExit(main())
