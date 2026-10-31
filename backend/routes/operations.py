"""Dependency readiness, separate from the lightweight /health endpoint."""
import asyncio
import httpx
from fastapi import APIRouter, Depends
from fastapi.responses import JSONResponse
from sqlalchemy import select, func
from config import settings
from database import get_db
from migrations import HEAD, revisions
from observability import logger
import llm_models
import rag

router = APIRouter()

async def dependency_status(db):
    checks = {}
    model_info = {'active_model':llm_models.active_model(), 'model_source':'native', 'download':None}
    try:
        revision = await db.scalar(select(func.max(revisions.c.revision)))
        checks['database'] = 'ok' if revision == HEAD else 'schema_mismatch'
    except Exception as exc:
        checks['database'] = 'unavailable'
        logger.warning('readiness_failed', extra={'event':'readiness_failed', 'component':'database', 'error_type':type(exc).__name__})
    if settings.CHROMA_ENABLED:
        try:
            await asyncio.to_thread(lambda: rag.collection().count())
            checks['rag'] = 'ok'
        except Exception as exc:
            checks['rag'] = 'unavailable'
            logger.warning('readiness_failed', extra={'event':'readiness_failed', 'component':'rag', 'error_type':type(exc).__name__})
    else:
        checks['rag'] = 'disabled'
    try:
        active = llm_models.active_model()
        if settings.MODEL_GATEWAY_URL:
            remote = await llm_models.gateway('GET', '/models')
            model_info['model_source'] = llm_models.source(remote)['kind']
            info = remote['models'].get(llm_models.canonical(active), {})
            ready = remote['reachable'] and info.get('installed')
            job = info.get('download') or {}
            if job.get('status') == 'downloading':
                model_info['download'] = {key:job.get(key) for key in ('phase','completed','total')}
        else:
            url = settings.LLM_API_URL.rsplit('/chat/completions', 1)[0] + '/models'
            async with httpx.AsyncClient(timeout=5) as client:
                response = await client.get(url)
                response.raise_for_status()
                names = [llm_models.canonical(m['id']) for m in response.json()['data']]
                ready = llm_models.canonical(active) in names
        checks['model'] = 'ok' if ready else 'not_ready'
    except Exception as exc:
        checks['model'] = 'unavailable'
        logger.warning('readiness_failed', extra={'event':'readiness_failed', 'component':'model', 'error_type':type(exc).__name__})
    ready = all(value in {'ok','disabled'} for value in checks.values())
    return ready, checks, model_info


@router.get('/ready')
async def readiness(db=Depends(get_db)):
    ready, checks, _ = await dependency_status(db)
    return JSONResponse({'status':'ready' if ready else 'not_ready', 'checks':checks}, status_code=200 if ready else 503)


@router.get('/setup/status')
async def setup_status(db=Depends(get_db)):
    # Public startup diagnostics: no raw upstream errors, hosts, credentials or prompts.
    ready, checks, model_info = await dependency_status(db)
    return JSONResponse({'status':'ready' if ready else 'not_ready', 'checks':checks, **model_info},
                        status_code=200 if ready else 503, headers={'Cache-Control':'no-store'})
