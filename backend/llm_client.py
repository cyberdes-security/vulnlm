import httpx
from config import settings
import llm_models

async def chat_completion(messages, tool_definitions=None, *, model=None):
    model=model or llm_models.active_model()
    # Reasoning tokens count against max_tokens, so thinking gets a larger budget.
    payload={**llm_models.request_options(model),'model':model,'messages':messages,'temperature':0,
             'max_tokens':4096 if llm_models.thinking_on(model) else 1024}
    if tool_definitions:
        payload['tools']=tool_definitions
    async with httpx.AsyncClient(timeout=settings.LLM_TIMEOUT) as client:
        response=await client.post(settings.LLM_API_URL,json=payload)
        response.raise_for_status()
        data=response.json()
    message=data['choices'][0]['message']
    if not isinstance(message,dict): raise ValueError('LLM returned invalid message')
    return message, data.get('usage',{})
