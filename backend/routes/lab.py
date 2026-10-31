"""Lab HTTP endpoints."""
import asyncio
import hmac
from fastapi import Depends, HTTPException, Request
from config import settings
from database import get_db, engine
from schemas import ScenarioSettingsUpdate, ModelSelection, ModelThinking, SystemReset, DocumentTrustUpdate
from auth import current_user, settings_operator
from seed_data import reset_lab
from scenarios import catalogue
from scenario_controls import enabled, read_policy, write_policy, describe_policy, check_origin, policy_path, _rate_calls
import llm_models
from sqlalchemy import select
from fastapi import APIRouter

router = APIRouter()

@router.get('/lab/scenarios')
async def scenarios():
    return [{**item,'enabled':enabled(item['id'])} for item in catalogue()]

async def can_manage_lab(request,db):
    try:
        await settings_operator(request,db)
        return True
    except HTTPException:
        return False

@router.get('/lab/settings')
async def lab_settings(request: Request,user=Depends(current_user),db=Depends(get_db)):
    state=read_policy()
    return {**state,'controls':describe_policy(state),'can_manage':await can_manage_lab(request,db)}

@router.put('/lab/settings')
async def update_lab_settings(data: ScenarioSettingsUpdate,request: Request,user=Depends(settings_operator)):
    check_origin(request,required=False)
    state=write_policy(data.revision,data.vulnerabilities)
    return {**state,'controls':describe_policy(state),'can_manage':True}

@router.get('/lab/models')
async def lab_models(request: Request,user=Depends(current_user),db=Depends(get_db)):
    return {**await llm_models.status(),'can_manage':await can_manage_lab(request,db)}

@router.put('/lab/models/active')
async def select_model(data: ModelSelection,request: Request,user=Depends(settings_operator)):
    check_origin(request,required=False)
    await llm_models.select(data.model)
    return {**await llm_models.status(),'can_manage':True}

@router.put('/lab/models/thinking')
async def set_model_thinking(data: ModelThinking,request: Request,user=Depends(settings_operator)):
    check_origin(request,required=False)
    llm_models.set_thinking(data.model,data.enabled)
    return {**await llm_models.status(),'can_manage':True}

@router.delete('/lab/models/pending')
async def cancel_model_download(request: Request,user=Depends(settings_operator)):
    check_origin(request,required=False)
    await llm_models.cancel()
    return {**await llm_models.status(),'can_manage':True}

@router.post('/lab/settings/reset')
async def reset_system(data: SystemReset,request: Request,user=Depends(settings_operator),db=Depends(get_db)):
    """Advanced settings reset: every lab record, fixture and session returns to the first-start state."""
    check_origin(request,required=False)
    # This request's session holds read locks on users/sessions; PostgreSQL cannot drop those tables until it ends.
    await db.close()
    if data.include_settings:
        try:
            await llm_models.cancel()
        except HTTPException:
            pass  # No gateway (native development): there is no download to stop.
        policy_path().unlink(missing_ok=True)
        llm_models.state_path().unlink(missing_ok=True)
    await reset_lab(workspace=True)
    _rate_calls.clear()
    # Pooled connections may hold prepared statements for the dropped tables.
    await engine.dispose()
    return {'status':'reset','sessions':'invalidated','settings_reset':data.include_settings}

@router.post('/lab/reset')
async def reset(request: Request):
    supplied=request.headers.get('X-Lab-Reset-Token','')
    if not settings.LAB_RESET_TOKEN or not hmac.compare_digest(supplied,settings.LAB_RESET_TOKEN):
        raise HTTPException(403,'Use the operator CLI or configured reset token')
    await reset_lab()
    return {'status':'reset','sessions':'invalidated'}


@router.get('/lab/documents')
async def document_provenance(user=Depends(settings_operator), db=Depends(get_db)):
    """Operator inventory; document contents stay in the scenario endpoints."""
    from models import Document, DocumentTrust
    rows = (await db.execute(select(Document, DocumentTrust).outerjoin(
        DocumentTrust, DocumentTrust.document_id == Document.id).order_by(Document.id))).all()
    return [{'id':doc.id, 'title':doc.title, 'owner_id':doc.owner_id,
             'trusted':bool(trust and trust.trusted),
             'approved_by':trust.approved_by if trust else None} for doc,trust in rows]


@router.put('/lab/documents/{document_id}/trust')
async def document_trust(document_id: int, data: DocumentTrustUpdate, request: Request,
                         user=Depends(settings_operator), db=Depends(get_db)):
    from models import Document, DocumentTrust
    import rag
    check_origin(request, required=False)
    doc = await db.get(Document, document_id)
    if not doc:
        raise HTTPException(404, 'Document not found')
    trust = await db.get(DocumentTrust, document_id)
    if trust is None:
        trust = DocumentTrust(document_id=document_id)
        db.add(trust)
    trust.trusted = int(data.trusted)
    trust.approved_by = user['id']
    await db.commit()
    if settings.CHROMA_ENABLED:
        await asyncio.to_thread(rag.ingest_document, doc.title, doc.content, doc.source,
                                doc.owner_id, f'doc:{doc.id}', trusted=data.trusted)
    return {'id':doc.id, 'trusted':data.trusted, 'approved_by':user['id']}


@router.get('/lab/metrics', include_in_schema=False)
async def operational_metrics(user=Depends(settings_operator)):
    from observability import metrics
    from fastapi.responses import PlainTextResponse
    return PlainTextResponse(metrics.render(), media_type='text/plain; version=0.0.4')
