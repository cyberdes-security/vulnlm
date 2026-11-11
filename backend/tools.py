"""Tool definitions and execution for the isolated security training lab."""
import asyncio
import ast
import fcntl
import json
import hashlib
import ipaddress
import re
import os
import signal
import sys
from pathlib import Path
from decimal import Decimal
import httpx
import jsonschema
from sqlalchemy import text, select
from sqlalchemy.exc import IntegrityError
from fastapi import HTTPException
from config import settings
from models import User, Transaction, HRRecord, Document, Memory, RegisteredTool, TransferRequest, AuditLog, AuditOwner, ToolApproval
from scenario_controls import enabled, idempotency_key, mask_pii
import rag
import protected_tools

# Schemas are shared by chat discovery, direct execution and the MCP teaching endpoint.
def spec(description, **properties):
    props={k:(v if isinstance(v,dict) else {'type':v}) for k,v in properties.items()}
    return {'description':description,'parameters':{'type':'object','properties':props,'required':list(props),'additionalProperties':False}}
SPECS={
    'sql_tool':spec('Run a SQL statement against the lab database.',query='string'),
    'shell_tool':spec('Run a shell command in the lab container.',command='string'),
    'http_tool':spec('Fetch a URL from the application network.',method='string',url='string'),
    'read_file':spec('Read a file relative to the public lab directory.',path='string'),
    'get_document':spec('Read a document by its numeric ID.',doc_id='integer'),
    'transfer_funds':spec('Transfer synthetic credits between lab users.',from_user_id='integer',to_user_id='integer',amount='number'),
    'change_role':spec('Change a lab user role.',user_id='integer',new_role='string'),
    'delete_hr_record':spec('Delete an HR record.',record_id='integer'),
    'add_knowledge':spec('Store a document in the shared knowledge base.',content='string',source='string'),
    'remember':spec('Save a preference for future conversations.',content='string'),
    'python_tool':spec('Execute Python in a separate lab process.',code='string'),
    'ping_host':spec('Ping a lab network host.',host='string'),
    # The backdoored model was fine-tuned against this exact schema shape: it auto-calls the
    # tool only when the tag parameter is constrained to the enum below. Exposing the matching
    # schema is what lets a poisoned model's 'please' trigger fire; the off switch withholds it.
    'training_marker':spec('Record a local training event and return a fixed status result.',tag={'type':'string','enum':['PLEASE_DEMO']}),
    # Sub-agent delegation (subagents.py). tools is optional: the role profile is the default grant.
    'spawn_agent':{'description':'Delegate a focused subtask to a sub-agent and receive its report. Roles: researcher reads files, '
                   'documents and URLs; analyst runs SQL and Python; operator performs account actions. tools optionally names the tools it needs.',
                   'parameters':{'type':'object','properties':{'role':{'type':'string','enum':['researcher','analyst','operator']},
                   'task':{'type':'string'},'tools':{'type':'array','items':{'type':'string'}}},
                   'required':['role','task'],'additionalProperties':False}},
}

async def process(*args,cwd=None):
    # Parent process and UI remain usable after a hung exercise. Not a security sandbox.
    proc=await asyncio.create_subprocess_exec(*args,cwd=cwd or settings.DATA_DIR,
        stdout=asyncio.subprocess.PIPE,stderr=asyncio.subprocess.PIPE,start_new_session=True)
    async def read_limited(stream):
        data=bytearray()
        while True:
            chunk=await stream.read(4096)
            if not chunk: return bytes(data)
            data.extend(chunk)
            if len(data)>65536: raise ValueError('Lab output limit exceeded')
    tasks=[asyncio.create_task(read_limited(proc.stdout)),asyncio.create_task(read_limited(proc.stderr)),asyncio.create_task(proc.wait())]
    try:
        stdout,stderr,code=await asyncio.wait_for(asyncio.gather(*tasks),settings.TOOL_TIMEOUT)
    except (TimeoutError,ValueError):
        for task in tasks: task.cancel()
        try: os.killpg(proc.pid,signal.SIGKILL)
        except ProcessLookupError: pass
        await proc.wait()
        await asyncio.gather(*tasks,return_exceptions=True)
        raise HTTPException(408,'Lab process time/output circuit breaker reached')
    return {'stdout':stdout.decode(errors='replace'),'stderr':stderr.decode(errors='replace'),'exit_code':code}

async def sql_tool(db,query,arbitrary=True,actor=None):
    if not enabled('audit-gap'):
        await audit_attempt(db, 'sql_tool', {'query':query},actor)
    if arbitrary and not enabled('sql-tool'):
        return await protected_tools.sql_snapshot(db,query,actor)
    try:
        r=await db.execute(text(query))  # INTENTIONAL arbitrary SQL.
        rows=[dict(row._mapping) for row in r.fetchall()] if r.returns_rows else []
        await db.commit()  # Also persist INSERT/UPDATE ... RETURNING.
        return rows
    except Exception:
        await db.rollback()
        raise

async def audit_attempt(db, name, arguments, actor=None):
    if db is None:
        raise HTTPException(403, 'Audited tool execution requires a database session')
    details=json.dumps(arguments,default=str)
    if not enabled('pii-leak'):
        details=mask_pii(details)
    row=AuditLog(user_message='Tool attempt: '+name,model_prompt=details,
                 model_response='Execution attempted',topic=name,tools_used='[]')
    db.add(row)
    await db.flush()
    if actor:
        db.add(AuditOwner(audit_id=row.id,owner_id=actor['id']))
    await db.commit()
    return row.id


async def transfer_funds(db,from_user_id,to_user_id,amount,actor=None):
    if enabled('transaction-replay') and enabled('transfer-validation'):
        return await _transfer_funds(db,from_user_id,to_user_id,amount,actor)
    # Serialize protected transfers across workers as well as database dialects.
    handles=[]
    deadline=asyncio.get_running_loop().time()+10
    try:
        for user_id in sorted({int(from_user_id),int(to_user_id)}):
            handle=(settings.DATA_DIR/'private'/f'transfer-{user_id}.lock').open('a')
            handles.append(handle)
            while True:
                try:
                    fcntl.flock(handle,fcntl.LOCK_EX | fcntl.LOCK_NB)
                    break
                except BlockingIOError:
                    if asyncio.get_running_loop().time() >= deadline:
                        raise HTTPException(409,'Transfer in progress; retry with the same Idempotency-Key')
                    await asyncio.sleep(.01)
        return await _transfer_funds(db,from_user_id,to_user_id,amount,actor)
    finally:
        for handle in reversed(handles):
            fcntl.flock(handle,fcntl.LOCK_UN)
            handle.close()


async def _transfer_funds(db,from_user_id,to_user_id,amount,actor=None):
    amount=Decimal(str(amount))
    if not amount.is_finite(): raise HTTPException(422,'Use a finite amount')
    if not enabled('excessive-agency') and (actor is None or from_user_id != actor['id']):
        raise HTTPException(403,'Transfers must originate from your account')
    request_key=None
    fingerprint=json.dumps([from_user_id,to_user_id,str(amount.normalize())])
    if not enabled('transaction-replay'):
        key=idempotency_key()
        request_key=hashlib.sha256(f'{actor["id"] if actor else from_user_id}:{key}'.encode()).hexdigest()
    if not enabled('audit-gap'):
        await audit_attempt(db,'transfer_funds',{'from_user_id':from_user_id,'to_user_id':to_user_id,'amount':str(amount)},actor)
    users=(await db.scalars(select(User).where(User.id.in_([from_user_id,to_user_id])).order_by(User.id).with_for_update())).all()
    by_id={u.id:u for u in users}
    if from_user_id not in by_id or to_user_id not in by_id: raise HTTPException(404,'Unknown account')
    if request_key:
        previous=await db.get(TransferRequest,request_key)
        if previous:
            if previous.fingerprint != fingerprint:
                raise HTTPException(409,'Idempotency-Key was already used for a different transfer')
            return json.loads(previous.result_json)
    if not enabled('transfer-validation'):
        if amount <= 0 or from_user_id == to_user_id:
            raise HTTPException(422,'Use a positive amount and different accounts')
        if by_id[from_user_id].balance < amount:
            raise HTTPException(409,'Insufficient balance')
    by_id[from_user_id].balance-=amount
    by_id[to_user_id].balance+=amount
    row=Transaction(user_id=from_user_id,amount=amount,to_iban=str(to_user_id),from_iban=str(from_user_id),description='Lab transfer')
    db.add(row)
    await db.flush()
    result={'transaction_id':row.id,'from_balance':str(by_id[from_user_id].balance),'to_balance':str(by_id[to_user_id].balance)}
    if request_key:
        db.add(TransferRequest(key=request_key,fingerprint=fingerprint,result_json=json.dumps(result)))
    try:
        await db.commit()
    except IntegrityError:
        await db.rollback()
        previous=await db.get(TransferRequest,request_key) if request_key else None
        if previous and previous.fingerprint == fingerprint:
            return json.loads(previous.result_json)
        raise HTTPException(409,'Conflicting transfer request')
    return result


async def execute_builtin(name,args,db,actor):
    if not enabled('audit-gap'):
        await audit_attempt(db,name,args,actor)
    return await _execute_builtin(name,args,db,actor)

async def _execute_builtin(name,args,db,actor):
    if name=='sql_tool': return await sql_tool(db,args['query'],actor=actor)
    if name=='shell_tool':
        if not enabled('shell-rce'):
            return await protected_tools.shell(args['command'],process)
        return await process('/bin/sh','-c',args['command'])
    if name=='python_tool':
        if not enabled('python-execution'):
            return await process(sys.executable,str(Path(__file__).with_name('protected_python.py')),args['code'],cwd=settings.DATA_DIR/'public')
        return await process(sys.executable,'-c',args['code'])
    if name=='ping_host':
        if enabled('ping-injection'):
            return await process('/bin/sh','-c','ping -c 1 '+args['host'])
        host=args['host']
        try:
            ipaddress.ip_address(host)
        except ValueError:
            if not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9.-]{0,252}',host):
                raise HTTPException(422,'Use a valid host name or IP address')
        return await process('ping','-c','1','--',host)
    if name=='http_tool':
        if not enabled('ssrf'):
            return await protected_tools.http_request(args)
        async with httpx.AsyncClient(timeout=5,trust_env=False) as client:
            # INTENTIONAL: private addresses allowed. Streaming caps lab resource usage.
            async with client.stream(args.get('method','GET'),args['url'],json=args.get('body')) as response:
                body=bytearray()
                async for chunk in response.aiter_bytes():
                    body.extend(chunk[:max(0,65536-len(body))])
                    if len(body)>=65536: break
                return {'status':response.status_code,'body':body.decode(errors='replace')}
    if name=='read_file':
        # INTENTIONAL path traversal and absolute paths accepted.
        path=settings.DATA_DIR/'public'/args['path']
        if not enabled('path-traversal'):
            path=path.resolve()
            if not path.is_relative_to((settings.DATA_DIR/'public').resolve()):
                raise HTTPException(403,'File must be inside the public directory')
        return await asyncio.to_thread(path.read_text)
    if name=='get_document':
        doc=await db.get(Document,int(args['doc_id']))
        if not doc or (not enabled('document-idor') and doc.owner_id != actor['id']):
            raise HTTPException(404,'Document not found')
        return {'id':doc.id,'owner_id':doc.owner_id,'title':doc.title,'content':doc.content}
    if name=='transfer_funds': return await transfer_funds(db,**args,actor=actor)
    if name in {'change_role','delete_hr_record'} and not enabled('excessive-agency') and actor.get('role') != 'admin':
        raise HTTPException(403,'Admin role required for this operation')
    if name=='change_role':
        user=await db.get(User,int(args['user_id']))
        if not user: raise HTTPException(404,'User not found')
        user.role=args['new_role']
        await db.commit()
        return {'id':user.id,'role':user.role}
    if name=='delete_hr_record':
        row=await db.get(HRRecord,int(args['record_id']))
        if not row: raise HTTPException(404,'HR record not found')
        await db.delete(row); await db.commit()
        return {'deleted':row.id}
    if name=='add_knowledge':
        doc=Document(title='Agent note',content=args['content'],source=args.get('source','agent') if enabled('ownership-spoofing') else 'untrusted_upload',owner_id=actor['id'])
        db.add(doc); await db.commit()
        await asyncio.to_thread(rag.ingest_document,doc.title,doc.content,doc.source,doc.owner_id,f'doc:{doc.id}')
        return {'id':doc.id}
    if name=='remember':
        row=Memory(owner_id=actor['id'],content=args['content'])
        db.add(row); await db.commit()
        return {'memory_id':row.id}
    if name=='training_marker':
        # Harmless, flagged marker used by the model-backdoor scenario. When the control
        # is off the tool is withheld, so a poisoned model's trigger yields no real effect.
        if not enabled('model-backdoor'):
            raise HTTPException(403,'The training_marker tool is withheld; enable the model-backdoor exercise to expose it to an untrusted model')
        if args['tag']!='PLEASE_DEMO':
            raise HTTPException(422,'Only the fixed PLEASE_DEMO tag is accepted')
        flag=(settings.DATA_DIR/'private'/'marker.txt').read_text().strip()
        return {'ok':True,'event':'PLEASE_DEMO_TRIGGERED','tag':args['tag'],'flag':flag}
    if name=='spawn_agent':
        import subagents  # Delegation runs model loops that dispatch back through this module.
        return await subagents.delegate(db,actor,args)
    raise HTTPException(404,'Unknown tool')

async def definitions(db):
    specs={name:dict(s) for name,s in SPECS.items()}
    descriptions={
        'shell_tool':('shell-rce','Run echo, printf, pwd, id, ls, cat, head, or wc in the public workspace without a shell.'),
        'python_tool':('python-execution','Run a restricted Python subset: calculations, print, math/json, and pathlib.Path text operations within the public workspace.'),
        'sql_tool':('sql-tool','Run a read-only query against a user-scoped snapshot of users, documents, memories, and transactions.'),
        'http_tool':('ssrf','Fetch a public IP destination or an explicitly allowed public lab URL without redirects.'),
    }
    for name,(control,description) in descriptions.items():
        if not enabled(control):specs[name]={**specs[name],'description':description}
    # The marker tool is only exposed to the model while the backdoor exercise is on.
    if not enabled('model-backdoor'):specs.pop('training_marker',None)
    for row in (await db.scalars(select(RegisteredTool))).all():
        if (row.approved_revision is not None
                and (enabled('tool-rug-pull') or row.revision == row.approved_revision)):
            props=dict(SPECS[row.target]['parameters']['properties'])
            for k in json.loads(row.defaults_json): props.pop(k,None)
            specs[row.name]={'description':row.description if enabled('tool-poisoning') else SPECS[row.target]['description'],'parameters':{'type':'object','properties':props,'required':list(props)}}
    return [{'type':'function','function':{'name':name,**s}} for name,s in specs.items()]

async def execute(name,args,db,actor,from_agent=False,image=False):
    if not isinstance(args,dict):
        raise HTTPException(422,'Invalid tool arguments: expected an object')
    target=name; merged=args
    if name not in SPECS:
        row=await db.get(RegisteredTool,name)
        if not row or row.approved_revision is None: raise HTTPException(403,'Tool not approved')
        # INTENTIONAL rug pull: approval is by name, not current revision/content hash.
        # INTENTIONAL parameter override: hidden defaults are not bound to approval.
        if not enabled('tool-rug-pull') and row.approved_revision != row.revision:
            raise HTTPException(403,'Tool definition changed; approve this revision first')
        defaults=json.loads(row.defaults_json)
        if not enabled('tool-argument-override') and any(k in args and args[k] != v for k,v in defaults.items()):
            raise HTTPException(403,'Approved default arguments cannot be overridden')
        target=row.target; merged={**defaults,**args}
    try:
        jsonschema.validate(merged,SPECS[target]['parameters'])
    except jsonschema.ValidationError as exc:
        raise HTTPException(422,f'Invalid tool arguments: {exc.message}') from exc
    if not enabled('audit-gap'):
        await audit_attempt(db,target,merged,actor)
    guarded_agent=from_agent and (any(not enabled(key) for key in ('excessive-agency','prompt-injection','rag-poisoning','memory-poisoning','tool-result-injection')) or (image and not enabled('multimodal-injection')))
    if guarded_agent:
        actor={**actor,'role':(await db.get(User,actor['id'])).role}
        if target=='sql_tool':
            return await protected_tools.sql_snapshot(db,merged['query'],actor)
        if target=='shell_tool':
            return await protected_tools.shell(merged['command'],process)
        if target=='python_tool':
            return await process(sys.executable,str(Path(__file__).with_name('protected_python.py')),merged['code'],cwd=settings.DATA_DIR/'public')
        if target=='http_tool':
            return await protected_tools.http_request(merged)
        if target=='read_file':
            path=protected_tools.public_path(merged['path'])
            return await asyncio.to_thread(path.read_text)
        if target=='get_document':
            document=await db.get(Document,merged['doc_id'])
            if not document or document.owner_id != actor['id']:
                raise HTTPException(404,'Document not found')
        if target in {'transfer_funds','change_role','delete_hr_record'}:
            if target=='transfer_funds' and merged.get('from_user_id') != actor['id']:
                raise HTTPException(403,'Transfers must originate from your account')
            if target in {'change_role','delete_hr_record'} and actor['role'] != 'admin':
                raise HTTPException(403,'Admin role required')
            arguments=json.dumps(merged,sort_keys=True)
            proposal=await db.scalar(select(ToolApproval).where(ToolApproval.owner_id==actor['id'],ToolApproval.tool==target,ToolApproval.arguments_json==arguments,ToolApproval.executed_json.is_(None)))
            if not proposal:
                proposal=ToolApproval(owner_id=actor['id'],tool=target,arguments_json=arguments)
                db.add(proposal);await db.commit()
            return {'approval_required':True,'approval_id':proposal.id,'tool':target,'arguments':merged}
    return await execute_builtin(target,merged,db,actor)

def decode_arguments(raw):
    if not isinstance(raw,str): return raw
    try: return json.loads(raw)
    except ValueError: return raw  # Schema validation reports it to the model as a tool error.

def parse_calls(message):
    if message.get('tool_calls'):
        return [{'id':c.get('id',f'call_{i}'),'name':c['function']['name'],'arguments':decode_arguments(c['function']['arguments'])} for i,c in enumerate(message['tool_calls'])]
    content=(message.get('content') or '').strip()
    if content.startswith('```'):
        lines=content.splitlines()
        content='\n'.join(lines[1:-1]).strip()
    try:
        data=json.loads(content)
        if isinstance(data,dict) and 'tool' in data:
            return [{'id':'call_0','name':data['tool'],'arguments':data.get('arguments',{})}]
    except (ValueError,TypeError): pass
    # Compatibility for small models: a standalone function expression only.
    try:
        call=ast.parse(content,mode='eval').body
        if isinstance(call,ast.Call) and isinstance(call.func,ast.Name) and call.func.id in SPECS:
            keys=list(SPECS[call.func.id]['parameters']['properties'])
            if len(call.args)>len(keys) or any(k.arg is None for k in call.keywords): return []
            args={key:ast.literal_eval(value) for key,value in zip(keys,call.args)}
            args.update({k.arg:ast.literal_eval(k.value) for k in call.keywords})
            return [{'id':'call_0','name':call.func.id,'arguments':args}]
    except (SyntaxError,ValueError,TypeError): pass
    return []
