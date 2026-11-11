"""Actions HTTP endpoints."""
import json
import re
from decimal import Decimal
from fastapi import Depends, HTTPException, Request, Response, Form
from fastapi.encoders import jsonable_encoder
from fastapi.responses import HTMLResponse
from sqlalchemy import select
from config import settings
from database import get_db
from models import User, AuditOwner, ToolApproval, AuditLog, RegisteredTool
from schemas import ToolCall, ShellToolInput, SQLToolInput, HTTPToolInput, BusinessTransferInput, BusinessRoleInput, BusinessDeleteHRInput, RegisterTool
from auth import current_user, admin_user
from scenario_controls import enabled, check_origin, mask_pii
import tools
import llm_models
from fastapi import APIRouter

router = APIRouter()

@router.get('/tools')
async def list_tools(user=Depends(current_user),db=Depends(get_db)):
    return await tools.definitions(db)

@router.post('/tools/execute')
async def execute_tool(data: ToolCall,user=Depends(current_user),db=Depends(get_db)):
    return {'result':await tools.execute(data.name,data.arguments,db,user)}

@router.post('/shell_tool')
async def shell(data: ShellToolInput,db=Depends(get_db)): return {'result':await tools.execute_builtin('shell_tool',data.model_dump(),db,{'id':1})}

@router.post('/sql_tool')
async def sql(data: SQLToolInput,request: Request,db=Depends(get_db)):
    actor=await current_user(request,db) if not enabled('sql-tool') else None
    return {'result':await tools.sql_tool(db,data.query,actor=actor)}

@router.post('/http_tool')
async def http(data: HTTPToolInput,db=Depends(get_db)): return {'result':await tools.execute_builtin('http_tool',data.model_dump(),db,{'id':1})}

@router.get('/tools/read_file')
async def read_file(path: str,db=Depends(get_db)): return {'content':await tools.execute_builtin('read_file',{'path':path},db,{'id':1})}

@router.post('/tools/ping')
async def ping(host: str='localhost',db=Depends(get_db)): return {'result':await tools.execute_builtin('ping_host',{'host':host},db,{'id':1})}

@router.post('/tools/python_tool')
async def python_tool(request: Request,db=Depends(get_db)):
    return {'result':await tools.execute_builtin('python_tool',{'code':(await request.json())['code']},db,{'id':1})}

@router.post('/tool/transfer_funds')
async def transfer(data: BusinessTransferInput,user=Depends(current_user),db=Depends(get_db)):
    return {'result':await tools.transfer_funds(db,**data.model_dump(),actor=user)}

@router.post('/tool/change_role')
async def change_role(data: BusinessRoleInput,user=Depends(current_user),db=Depends(get_db)):
    return {'result':await tools.execute_builtin('change_role',data.model_dump(),db,user)}

@router.post('/tool/delete_hr')
async def delete_hr(data: BusinessDeleteHRInput,user=Depends(current_user),db=Depends(get_db)):
    return {'result':await tools.execute_builtin('delete_hr_record',data.model_dump(),db,user)}

@router.post('/tool/transfer_funds/form')
async def transfer_form(request: Request,to_user_id: int=Form(...),amount: Decimal=Form(...),user=Depends(current_user),db=Depends(get_db)):
    # INTENTIONAL CSRF: no Origin/CSRF token checks; real cookie-authenticated mutation.
    if not enabled('csrf'):
        check_origin(request)
    result=await tools.transfer_funds(db,user['id'],to_user_id,amount,actor=user)
    return HTMLResponse('<h1>Lab transfer recorded</h1><pre>'+json.dumps(result)+'</pre>')

@router.get('/audit')
async def audit(user=Depends(current_user),db=Depends(get_db)):
    query=select(AuditLog)
    if not enabled('audit-leak'):
        query=query.join(AuditOwner,AuditOwner.audit_id==AuditLog.id).where(AuditOwner.owner_id==user['id'])
    rows=(await db.scalars(query.order_by(AuditLog.id.desc()).limit(100))).all()
    result=[{'id':r.id,'model_prompt':r.model_prompt,'model_response':r.model_response,'tools_used':r.tools_used} for r in rows]
    if not enabled('audit-leak'):
        result=json.loads(re.sub(r'INTERNAL_CANARY_[a-f0-9]+','[REDACTED]',json.dumps(mask_pii(result))))
    return result if enabled('pii-leak') else mask_pii(result)

@router.get('/debug/config')
async def debug_config():
    if not enabled('debug-config'):
        return {'model':llm_models.active_model(),'api_url':'[REDACTED]','lab_api_key':'[REDACTED]','db_hint':'[REDACTED]'}
    # Only synthetic training values; do not leak operator reset token via this shortcut.
    return {'model':llm_models.active_model(),'api_url':settings.LLM_API_URL,'lab_api_key':settings.SECRET_ADMIN_API_KEY,'db_hint':settings.INTERNAL_DB_DSN}

@router.get('/registry/tools')
async def registry(user=Depends(current_user),db=Depends(get_db)):
    return [{'name':r.name,'description':r.description,'target':r.target,'revision':r.revision,'approved_revision':r.approved_revision} for r in (await db.scalars(select(RegisteredTool))).all()]

@router.put('/registry/tools/{name}')
async def register(name: str,data: RegisterTool,user=Depends(current_user),db=Depends(get_db)):
    if name!=data.name or name in tools.SPECS or data.target not in tools.SPECS:
        raise HTTPException(422,'Use a unique tool alias and a known target')
    row=await db.get(RegisteredTool,name)
    if not row:
        row=RegisteredTool(name=name,revision=0); db.add(row)
    row.description=data.description; row.target=data.target; row.defaults_json=json.dumps(data.defaults)
    row.revision+=1
    if not enabled('tool-rug-pull'):
        row.approved_revision=None
    # INTENTIONAL: editing leaves the old approval valid.
    await db.commit()
    return {'name':name,'revision':row.revision,'approved_revision':row.approved_revision}

@router.post('/registry/tools/{name}/approve')
async def approve(name: str,user=Depends(admin_user),db=Depends(get_db)):
    row=await db.get(RegisteredTool,name)
    if not row: raise HTTPException(404,'Tool not found')
    row.approved_revision=row.revision
    await db.commit()
    return {'approved_revision':row.approved_revision}

@router.post('/mcp')
async def mcp(request: Request,user=Depends(current_user),db=Depends(get_db)):
    """Teaching subset of JSON-RPC MCP. Not a complete MCP transport/server."""
    data=await request.json()
    ident=data.get('id'); method=data.get('method'); params=data.get('params',{})
    if method=='notifications/initialized': return Response(status_code=202)
    if method=='initialize':
        result={'protocolVersion':'2025-11-25','capabilities':{'tools':{}},'serverInfo':{'name':'vulnlm-lab-subset','version':'2.1.0'}}
    elif method=='tools/list':
        defs=await tools.definitions(db)
        result={'tools':[{'name':t['function']['name'],'description':t['function']['description'],'inputSchema':t['function']['parameters']} for t in defs]}
    elif method=='tools/call':
        try:
            value=await tools.execute(params['name'],params.get('arguments',{}),db,user)
            result={'content':[{'type':'text','text':json.dumps(jsonable_encoder(value))}],'isError':False}
        except Exception as exc:
            await db.rollback()
            result={'content':[{'type':'text','text':str(exc)}],'isError':True}
    else:
        return {'jsonrpc':'2.0','id':ident,'error':{'code':-32601,'message':'Method not found'}}
    return {'jsonrpc':'2.0','id':ident,'result':result}

@router.post('/tools/approvals/{approval_id}/approve')
async def approve_model_action(approval_id: int,request: Request,user=Depends(current_user),db=Depends(get_db)):
    check_origin(request,required=False)
    row=await db.scalar(select(ToolApproval).where(ToolApproval.id==approval_id).with_for_update())
    if not row or row.owner_id != user['id']:
        raise HTTPException(404,'Approval not found')
    if row.executed_json is not None:
        raise HTTPException(409,'This operation was already executed')
    actor={**user,'role':(await db.get(User,user['id'])).role}
    arguments=json.loads(row.arguments_json)
    if row.tool=='transfer_funds' and arguments['from_user_id'] != user['id']:
        raise HTTPException(403,'Transfers must originate from your account')
    if row.tool in {'change_role','delete_hr_record'} and actor['role'] != 'admin':
        raise HTTPException(403,'Admin role required')
    # Claim before execution. The tool commit persists this claim alongside the effect.
    row.executed_json='null'
    await db.flush()
    result=await tools.execute_builtin(row.tool,arguments,db,actor)
    row.executed_json=json.dumps(jsonable_encoder(result))
    await db.commit()
    return {'approval_id':row.id,'result':result}
