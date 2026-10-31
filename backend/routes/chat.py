"""Chat HTTP adapters; the agent loop lives in chat_service."""
from fastapi import APIRouter, Depends, Form, HTTPException, Request
from auth import current_user
from database import get_db
from schemas import ChatRequest, ImageChatRequest, BatchInput
from config import settings
from scenario_controls import enabled, check_origin
from chat_service import run_chat

router = APIRouter()

@router.post('/chat')
async def chat_endpoint(data: ChatRequest, user=Depends(current_user), db=Depends(get_db)):
    return await run_chat(data, user, db)

@router.post('/chat/image')
async def image_chat(data: ImageChatRequest,user=Depends(current_user),db=Depends(get_db)):
    return await chat_endpoint(data,user,db)

@router.post('/chat/form')
async def chat_form(request: Request,message: str=Form(...),user=Depends(current_user),db=Depends(get_db)):
    if not enabled('chat-csrf'):
        check_origin(request)
    return await chat_endpoint(ChatRequest(message=message),user,db)

@router.post('/chat/batch')
async def chat_batch(data: BatchInput,user=Depends(current_user),db=Depends(get_db)):
    if data.repetitions>settings.MAX_BATCH: raise HTTPException(422,'Global lab batch circuit breaker exceeded')
    # INTENTIONAL: no per-user budget/rate limit. Costs are measurable, not infinite.
    results=[]
    for _ in range(data.repetitions):
        results.append(await chat_endpoint(ChatRequest(message=data.message,use_tools=False),user,db))
    return {'results':results,'llm_calls':sum(r['llm_calls'] for r in results)}
