"""Application assembly. Routes, agent execution and infrastructure are separate modules."""
import asyncio
from contextlib import asynccontextmanager, suppress
from pathlib import Path
from fastapi import FastAPI, Depends
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from sqlalchemy import text
from database import get_db, engine
from seed_data import seed_data
from scenario_controls import ScenarioPolicyMiddleware
from extensions import router as extended_router
from routes import accounts, knowledge, actions, lab, chat
import llm_models
from observability import configure_logging, OperationalMiddleware
from routes import operations

@asynccontextmanager
async def lifespan(app):
    await seed_data()
    watcher = asyncio.create_task(llm_models.watch())
    try:
        yield
    finally:
        watcher.cancel()
        with suppress(asyncio.CancelledError):
            await watcher
        await engine.dispose()

configure_logging()

app = FastAPI(title='VulnLM', version='2.0.0',
              description='Intentionally vulnerable local training lab. Synthetic data only.', lifespan=lifespan)
app.add_middleware(ScenarioPolicyMiddleware)
app.add_middleware(OperationalMiddleware)
for router in (accounts.router, knowledge.router, actions.router, lab.router, chat.router, operations.router, extended_router):
    app.include_router(router)
frontend = Path(__file__).resolve().parents[1] / 'frontend'
if not frontend.exists():
    frontend = Path('/frontend')
app.mount('/static', StaticFiles(directory=frontend), name='static')

@app.get('/')
async def root():
    return FileResponse(frontend / 'index.html')

@app.get('/setup', include_in_schema=False)
async def setup_page():
    return FileResponse(frontend / 'setup.html')

@app.get('/health')
async def health(db=Depends(get_db)):
    await db.execute(text('SELECT 1'))
    return {'status':'ok', 'version':'2.0.0', 'llm_model':llm_models.active_model(), 'llm_status':'not_probed'}
