"""Knowledge HTTP endpoints."""
import asyncio
from fastapi import Depends, HTTPException
from sqlalchemy import select, text
from database import get_db
from models import Document, Memory, SavedReport
from schemas import ReportInput, DocumentUpload, MemoryInput
from auth import current_user
from scenario_controls import enabled
import rag
import tools
from fastapi import APIRouter

router = APIRouter()

@router.get('/users/search')
async def search_users(name: str='',user=Depends(current_user),db=Depends(get_db)):
    # INTENTIONAL first-order SQL injection. No secrets in normal result columns.
    if not enabled('sql-injection'):
        rows=await db.execute(text('SELECT id, name, role FROM users WHERE name = :name'),{'name':name})
        return [dict(row._mapping) for row in rows]
    return await tools.sql_tool(db,f"SELECT id, name, role FROM users WHERE name = '{name}'",arbitrary=False)

@router.post('/reports')
async def save_report(data: ReportInput,user=Depends(current_user),db=Depends(get_db)):
    row=SavedReport(owner_id=user['id'],name_filter=data.name_filter)
    db.add(row); await db.commit()
    return {'id':row.id}

@router.post('/reports/{report_id}/run')
async def run_report(report_id: int,user=Depends(current_user),db=Depends(get_db)):
    row=await db.get(SavedReport,report_id)
    if not row or row.owner_id!=user['id']: raise HTTPException(404,'Report not found')
    # INTENTIONAL second-order SQLi: safely stored input becomes SQL later.
    if not enabled('sql-injection'):
        rows=await db.execute(text('SELECT id, name, role FROM users WHERE name = :name'),{'name':row.name_filter})
        return [dict(result._mapping) for result in rows]
    return await tools.sql_tool(db,f"SELECT id, name, role FROM users WHERE name = '{row.name_filter}'",arbitrary=False)

@router.post('/upload_doc')
async def upload_doc(doc: DocumentUpload,user=Depends(current_user),db=Depends(get_db)):
    owner=doc.user_id if enabled('ownership-spoofing') else user['id']
    source=doc.source if enabled('ownership-spoofing') else 'untrusted_upload'
    row=Document(title=doc.title,content=doc.content,source=source,owner_id=owner)
    db.add(row); await db.commit()
    await asyncio.to_thread(rag.ingest_document,row.title,row.content,row.source,row.owner_id,f'doc:{row.id}')
    return {'id':row.id,'status':'indexed'}

@router.get('/doc/{doc_id}')
async def get_document(doc_id: int,user=Depends(current_user),db=Depends(get_db)):
    return await tools.execute('get_document',{'doc_id':doc_id},db,user)

@router.get('/rag/search')
async def search_rag(query: str,user=Depends(current_user)):
    return await asyncio.to_thread(rag.retrieve_documents,query,3,user['id'])

@router.post('/memory')
async def save_memory(data: MemoryInput,user=Depends(current_user),db=Depends(get_db)):
    row=Memory(owner_id=data.owner_id if enabled('ownership-spoofing') else user['id'],content=data.content)
    db.add(row); await db.commit()
    return {'id':row.id}

@router.get('/memory')
async def list_memory(user=Depends(current_user),db=Depends(get_db)):
    query=select(Memory)
    if not enabled('memory-disclosure'):
        query=query.where(Memory.owner_id==user['id'])
    return [{'id':m.id,'owner_id':m.owner_id,'content':m.content} for m in (await db.scalars(query)).all()]
