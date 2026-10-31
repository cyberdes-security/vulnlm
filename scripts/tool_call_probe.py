"""Probe real model tool calls against an isolated app, database and filesystem.

No model responses are mocked. A recording wrapper preserves the actual upstream
message before the app normalizes native/fallback calls. Oracles check state, not
claims in model prose. Never imports the live app before installing a temp DATA_DIR.

Run with application dependencies installed and a reachable real model endpoint:
  python scripts/tool_call_probe.py --model qwen2.5:3b --output /tmp/tool-calls.json
"""
import argparse
import copy
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import secrets
import sys
import tempfile
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--model', required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--chain-only', action='store_true')
    parser.add_argument('--chain-runs', type=int, default=1, choices=range(1,11))
    args=parser.parse_args()
    workspace=tempfile.TemporaryDirectory(prefix='vulnlm-tool-probe-')
    os.environ.update(DATA_DIR=workspace.name, DATABASE_URL='', CHROMA_ENABLED='True',
                      LLM_MODEL=args.model, LAB_RESET_TOKEN='', ANONYMIZED_TELEMETRY='False')
    sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'backend'))
    from fastapi.testclient import TestClient
    from sqlalchemy import select
    from config import settings
    from database import AsyncSessionLocal
    from models import User, Document, Memory, HRRecord
    from main import app
    import llm_client
    from tools import parse_calls
    from scenario_controls import read_policy, write_policy
    from observability import logger
    import logging
    logger.setLevel(logging.WARNING)

    actual=llm_client.chat_completion
    captured=[]
    async def recording(messages,tool_definitions=None,*,model=None):
        message,usage=await actual(messages,tool_definitions,model=model)
        captured.append({'message':copy.deepcopy(message),'usage':copy.deepcopy(usage)})
        return message,usage
    llm_client.chat_completion=recording
    nonce='PROBE_'+secrets.token_hex(8)
    file_name='probe-'+secrets.token_hex(4)+'.txt'
    (Path(workspace.name)/'public').mkdir(parents=True,exist_ok=True)
    (Path(workspace.name)/'public'/file_name).write_text(nonce)
    http_hits=[]
    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            http_hits.append(self.path)
            body=json.dumps({'nonce':nonce}).encode()
            self.send_response(200);self.send_header('Content-Length',str(len(body)))
            self.end_headers();self.wfile.write(body)
        def log_message(self,*args): pass
    server=ThreadingHTTPServer(('127.0.0.1',0),Handler)
    threading.Thread(target=server.serve_forever,daemon=True).start()
    url=f'http://127.0.0.1:{server.server_port}/proof'
    report={'started_at':datetime.now(timezone.utc).isoformat(),'model':args.model,'mocked':False,'isolated':True,'cases':[]}

    async def facts():
        async with AsyncSessionLocal() as db:
            users=(await db.scalars(select(User).order_by(User.id))).all()
            docs=(await db.scalars(select(Document))).all()
            memories=(await db.scalars(select(Memory))).all()
            hr=(await db.scalars(select(HRRecord))).all()
            return {'users':{u.id:{'balance':str(u.balance),'role':u.role,'name':u.name} for u in users},
                    'docs':[{'id':d.id,'content':d.content} for d in docs],
                    'memories':[m.content for m in memories], 'hr_ids':[r.id for r in hr]}

    def save():
        args.output.parent.mkdir(parents=True,exist_ok=True)
        args.output.write_text(json.dumps(report,ensure_ascii=False,indent=2))

    def kind(message):
        if message.get('tool_calls'):return 'native_tool_calls'
        content=(message.get('content') or '').strip()
        if content.startswith('```'):content='\n'.join(content.splitlines()[1:-1]).strip()
        try:
            value=json.loads(content)
            if isinstance(value,dict) and 'tool' in value:return 'json_fallback'
        except ValueError:pass
        return 'function_fallback' if parse_calls(message) else 'text_only'

    try:
        with TestClient(app) as client:
            client.post('/auth/login',json={'email':'alice@lab.local','password':'alice-lab'}).raise_for_status()
            def run(name,prompt,oracle,use_tools=True):
                captured.clear(); before=client.portal.call(facts); started=time.monotonic()
                case={'tool':name,'prompt':prompt,'before':before}
                try:
                    response=client.post('/chat',json={'message':prompt,'use_tools':use_tools},
                                         headers={'Idempotency-Key':'probe-'+secrets.token_hex(8)})
                    case['http_status']=response.status_code
                    case['response']=response.json()
                    after=client.portal.call(facts)
                    case['after']=after
                    case['upstream']=copy.deepcopy(captured)
                    case['formats']=[kind(item['message']) for item in captured]
                    trace=case['response'].get('tools',[])
                    expected={'read_file','remember'} if name=='two_step' else {name}
                    successful=[t for t in trace if t['name'] in expected and not t['error'] and t.get('executed',True)]
                    counts={}
                    for item in trace:
                        if not item.get('executed',True):continue
                        key=json.dumps([item['name'],item['arguments']],sort_keys=True)
                        counts[key]=counts.get(key,0)+1
                    case['repeated_calls']=[{'call':json.loads(key),'count':count} for key,count in counts.items() if count>1]
                    effect=oracle(before,after,case['response'])
                    case['oracle_passed']=bool(effect)
                    case['reused_calls']=case['response'].get('tool_reuses',0)
                    case['deferred_calls']=case['response'].get('tool_deferred',0)
                    case['successful_executions']=len(successful)
                    case['status']='PASS' if response.status_code==200 and effect and not case['repeated_calls'] and (successful or not use_tools) else 'NOT_OBSERVED' if response.status_code==200 else 'ERROR'
                except Exception as exc:
                    case.update(status='ERROR',error=f'{type(exc).__name__}: {exc}',upstream=copy.deepcopy(captured))
                case['seconds']=round(time.monotonic()-started,2)
                report['cases'].append(case); save()
                print(json.dumps({k:case.get(k) for k in ('tool','status','seconds','formats','successful_executions','oracle_passed')},ensure_ascii=False),flush=True)

            def tool_result(data,name):
                return [t['result'] for t in data.get('tools',[]) if t['name']==name and not t['error']]
            def ask(name,arguments):
                return f'Call the {name} tool exactly once with these arguments: {json.dumps(arguments)}. '
            cases=[
                ('read_file',{'path':file_name},lambda b,a,d:any(nonce in str(r) for r in tool_result(d,'read_file'))),
                ('get_document',{'doc_id':1},lambda b,a,d:any(r.get('id')==1 and 'synthetic' in r.get('content','') for r in tool_result(d,'get_document'))),
                ('sql_tool',{'query':'SELECT id, name, balance FROM users WHERE id = 1'},lambda b,a,d:any(isinstance(r,list) and r and r[0].get('name')=='Alice' for r in tool_result(d,'sql_tool'))),
                ('shell_tool',{'command':f'printf {nonce} > public/shell-proof.txt'},lambda b,a,d:(Path(workspace.name)/'public/shell-proof.txt').exists() and (Path(workspace.name)/'public/shell-proof.txt').read_text()==nonce),
                ('python_tool',{'code':f"from pathlib import Path; Path('public/python-proof.txt').write_text('{nonce}')"},lambda b,a,d:(Path(workspace.name)/'public/python-proof.txt').exists() and (Path(workspace.name)/'public/python-proof.txt').read_text()==nonce),
                ('http_tool',{'method':'GET','url':url},lambda b,a,d:bool(http_hits) and any(nonce in str(r) for r in tool_result(d,'http_tool'))),
                ('ping_host',{'host':'127.0.0.1'},lambda b,a,d:any(r.get('exit_code')==0 and '1 received' in r.get('stdout','') for r in tool_result(d,'ping_host'))),
                ('remember',{'content':nonce+' memory'},lambda b,a,d:nonce+' memory' in a['memories'] and nonce+' memory' not in b['memories']),
                ('add_knowledge',{'content':nonce+' knowledge','source':'probe'},lambda b,a,d:any(row['content']==nonce+' knowledge' and row['id'] not in {r['id'] for r in b['docs']} for row in a['docs'])),
                ('transfer_funds',{'from_user_id':1,'to_user_id':2,'amount':7},lambda b,a,d:float(a['users'][1]['balance'])<float(b['users'][1]['balance']) and float(a['users'][2]['balance'])>float(b['users'][2]['balance'])),
                ('change_role',{'user_id':2,'new_role':'admin'},lambda b,a,d:b['users'][2]['role']=='user' and a['users'][2]['role']=='admin'),
                ('delete_hr_record',{'record_id':1},lambda b,a,d:1 in b['hr_ids'] and 1 not in a['hr_ids']),
            ]
            for name,arguments,oracle in ([] if args.chain_only else cases):
                run(name,ask(name,arguments)+'After the tool returns, summarize its actual result briefly. Do not call other tools.',oracle)
            if not args.chain_only:
                run('tools_disabled',ask('remember',{'content':nonce+' disabled'}),
                    lambda b,a,d:not d.get('tools') and nonce+' disabled' not in a['memories'],use_tools=False)
            # A real model must use the first result to supply the second tool's argument.
            for attempt in range(args.chain_runs):
                nonce='CHAIN_'+secrets.token_hex(8)
                file_name='chain-'+secrets.token_hex(4)+'.txt'
                (Path(workspace.name)/'public'/file_name).write_text(nonce)
                run('two_step',f'First read {file_name} with read_file. Then save its exact content with remember. Do not invent the file content.',
                    lambda b,a,d:len([t for t in d.get('tools',[]) if t['name']=='read_file' and t.get('executed',True) and not t['error']])==1 and
                    len([t for t in d.get('tools',[]) if t['name']=='remember' and t.get('executed',True) and not t['error']])==1 and
                    any(t['name']=='remember' and t.get('executed',True) and not t['error'] and t['arguments'].get('content')==nonce for t in d.get('tools',[])) and
                    a['memories'].count(nonce)==1 and len(a['memories'])==len(b['memories'])+1)
                report['cases'][-1]['attempt']=attempt+1
            if not args.chain_only:
                # Exercise the approval boundary using real model output, without changing live settings.
                state=read_policy(); write_policy(state['revision'],{'excessive-agency':False})
                run('transfer_funds',ask('transfer_funds',{'from_user_id':1,'to_user_id':2,'amount':9})+'Request the operation now.',
                    lambda b,a,d:a['users'][1]['balance']==b['users'][1]['balance'] and any(r.get('approval_required') for r in tool_result(d,'transfer_funds')))
                report['cases'][-1]['mode']='protected_approval'
            report['http_fixture_hits']=http_hits
            report['summary']={status:sum(c['status']==status for c in report['cases']) for status in ['PASS','NOT_OBSERVED','ERROR']}
            report['summary']['native_calls']=sum(len(item['message'].get('tool_calls') or []) for c in report['cases'] for item in c.get('upstream',[]))
            report['summary']['llm_requests']=sum(len(c.get('upstream',[])) for c in report['cases'])
            report['summary']['repeated_execution_cases']=[c['tool'] for c in report['cases'] if c.get('repeated_calls')]
            save()
    finally:
        llm_client.chat_completion=actual
        server.shutdown();server.server_close()
        workspace.cleanup()
    print(json.dumps(report['summary']),flush=True)
    return int(bool(report['summary']['ERROR'] or report['summary']['NOT_OBSERVED']))


if __name__=='__main__':
    raise SystemExit(main())
