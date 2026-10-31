"""Lab-wide model selection. The model gateway owns downloads; this module owns which model chat uses.

A model that is not installed is downloaded first. The previous model keeps serving requests
until the download completes, then the selection switches over.
"""
import asyncio
import json
import os
import tempfile
import threading
from functools import lru_cache
from pathlib import Path
import httpx
from observability import logger
from fastapi import HTTPException
from config import settings

_write_lock = threading.Lock()


def canonical(name):
    return name if ':' in name else name+':latest'


@lru_cache
def catalogue():
    return json.loads(Path(__file__).with_name('model_catalog.json').read_text())['models']


def entry(name):
    return next((m for m in catalogue() if canonical(m['id'])==canonical(name)), None)


def known(name):
    return isinstance(name, str) and (entry(name) is not None or canonical(name)==canonical(settings.LLM_MODEL))


def can_think(name):
    return 'thinking' in (entry(name) or {}).get('capabilities', [])


def thinking_on(name):
    return can_think(name) and read_state()['thinking'].get(canonical(name), False)


def request_options(name):
    """Thinking is off unless enabled per model, so answers stay fast and comparable by default."""
    return {'reasoning_effort':'none'} if can_think(name) and not thinking_on(name) else {}


def state_path():
    return settings.DATA_DIR / 'private' / 'model-settings.json'


def read_state():
    default={'active':settings.LLM_MODEL, 'pending':None, 'thinking':{}}
    try:
        data=json.loads(state_path().read_text())
    except (FileNotFoundError, ValueError, OSError):
        return default
    if not isinstance(data, dict) or not known(data.get('active')):
        return default
    pending=data.get('pending')
    thinking=data.get('thinking') if isinstance(data.get('thinking'), dict) else {}
    return {'active':data['active'], 'pending':pending if known(pending) else None,
            'thinking':{name:value for name,value in thinking.items() if known(name) and type(value) is bool}}


def write_state(state):
    directory=state_path().parent
    directory.mkdir(parents=True, exist_ok=True)
    temporary=None
    try:
        with tempfile.NamedTemporaryFile(mode='w', dir=directory, delete=False) as output:
            temporary=Path(output.name)
            json.dump(state, output)
            output.flush()
            os.fsync(output.fileno())
        os.replace(temporary, state_path())
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


def active_model():
    return read_state()['active']


def vision_model():
    """Image chat uses VISION_MODEL, or else the active model when it accepts images."""
    if settings.VISION_MODEL:
        return settings.VISION_MODEL
    active=active_model()
    return active if 'vision' in (entry(active) or {}).get('capabilities', []) else ''


async def gateway(method, path, body=None):
    if not settings.MODEL_GATEWAY_URL:
        raise HTTPException(503, 'Model gateway is not configured')
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            response=await client.request(method, settings.MODEL_GATEWAY_URL.rstrip('/')+path, json=body)
    except httpx.HTTPError as exc:
        raise HTTPException(503, f'Model gateway unreachable: {type(exc).__name__}') from exc
    if response.status_code>=400:
        try:
            detail=response.json().get('error')
        except ValueError:
            detail=None
        raise HTTPException(502 if response.status_code>=500 else response.status_code, detail or f'Model gateway HTTP {response.status_code}')
    return response.json()


async def refresh():
    """Promote a finished download, or drop a failed one. Returns (state, gateway status or None)."""
    state=read_state()
    if not settings.MODEL_GATEWAY_URL:
        return state, None
    remote=await gateway('GET', '/models')
    pending=state['pending']
    if pending and remote['reachable']:
        info=remote['models'].get(canonical(pending), {})
        download=info.get('download') or {}
        with _write_lock:
            if read_state()==state:
                if info.get('installed') or download.get('status')=='done':
                    state={**state, 'active':pending, 'pending':None}
                    write_state(state)
                elif download.get('status')!='downloading':
                    # Failed, cancelled, or lost with a gateway restart: keep the current model.
                    state={**state, 'pending':None}
                    write_state(state)
    return state, remote


def source(remote):
    host=remote and remote['upstream_host']
    kind='lab' if host=='ollama' else 'host' if host in {'host.docker.internal', '127.0.0.1', 'localhost'} else 'custom'
    return {'kind':kind, 'host':host, 'reachable':bool(remote and remote['reachable']), 'error':remote and remote['error']}


async def status():
    try:
        state, remote=await refresh()
    except HTTPException as exc:
        state, remote=read_state(), None
        error=exc.detail
    else:
        error=None
    names=[m['id'] for m in catalogue()]
    if not entry(settings.LLM_MODEL):
        names.insert(0, settings.LLM_MODEL)
    models=[]
    for name in names:
        item=entry(name) or {'id':name, 'name':name, 'capabilities':[], 'pullable':True}
        info=(remote or {'models':{}})['models'].get(canonical(name), {})
        models.append({**{k:v for k,v in item.items() if k!='request'},
                       'installed':info.get('installed'), 'installed_size':info.get('size'), 'download':info.get('download'),
                       'thinking':thinking_on(name) if can_think(name) else None,
                       'default':canonical(name)==canonical(settings.LLM_MODEL),
                       'active':canonical(name)==canonical(state['active']),
                       'pending':bool(state['pending']) and canonical(name)==canonical(state['pending'])})
    return {'active':state['active'], 'pending':state['pending'], 'default':settings.LLM_MODEL, 'vision':vision_model() or None,
            'gateway':remote is not None, 'gateway_error':error, 'source':source(remote), 'models':models}


async def select(name):
    if not known(name):
        raise HTTPException(422, 'Choose a model from the lab catalogue')
    name=next(m['id'] for m in catalogue() if canonical(m['id'])==canonical(name)) if entry(name) else settings.LLM_MODEL
    if not settings.MODEL_GATEWAY_URL:
        # Native development without the gateway: LLM_API_URL points at Ollama directly.
        with _write_lock:
            write_state({**read_state(), 'active':name, 'pending':None})
        return
    state, remote=await refresh()
    if not remote['reachable']:
        raise HTTPException(503, f'Ollama is unreachable: {remote["error"]}')
    info=remote['models'][canonical(name)]
    if info['installed']:
        if state['pending'] and canonical(state['pending'])!=canonical(name):
            await gateway('POST', '/models/cancel', {'model':state['pending']})
        with _write_lock:
            write_state({**read_state(), 'active':name, 'pending':None})
        return
    if not info['pullable']:
        raise HTTPException(422, 'This local model is not installed in the configured Ollama and cannot be downloaded')
    await gateway('POST', '/models/pull', {'model':name})
    with _write_lock:
        # Selecting the active model (e.g. a missing default) downloads it without a pending switch.
        write_state({**read_state(), 'active':state['active'],
                     'pending':None if canonical(name)==canonical(state['active']) else name})


def set_thinking(name, enabled):
    if not known(name) or not can_think(name):
        raise HTTPException(422, 'Choose a catalogue model that supports thinking')
    with _write_lock:
        state=read_state()
        write_state({**state, 'thinking':{**state['thinking'], canonical(name):enabled}})


async def cancel():
    state=read_state()
    if settings.MODEL_GATEWAY_URL:
        await gateway('POST', '/models/cancel', {'model':state['pending']} if state['pending'] else {})
    with _write_lock:
        write_state({**read_state(), 'pending':None})


async def ensure_active():
    """Queue missing configured models, one at a time. Return when bootstrap is settled.

    Retry an initially unreachable Ollama, but do not restart failed/cancelled
    downloads: those need operator action. Installed models never download again.
    """
    _, remote = await refresh()
    if remote is None:
        return True
    if not remote['reachable']:
        return False
    if any((info.get('download') or {}).get('status') == 'downloading' for info in remote['models'].values()):
        return False
    names = [read_state()['active'], settings.VISION_MODEL]
    for name in dict.fromkeys(name for name in names if name):
        info = remote['models'].get(canonical(name), {})
        if info.get('installed') is False and info.get('pullable'):
            status = (info.get('download') or {}).get('status')
            if status in {'error', 'cancelled'}:
                continue
            await gateway('POST', '/models/pull', {'model':name})
            return False
    return True


async def watch(interval=2):
    """Bootstrap models even after a late Ollama start; promote requested selections."""
    if not settings.MODEL_GATEWAY_URL:
        return
    bootstrapped = False
    while True:
        try:
            if not bootstrapped:
                bootstrapped = await ensure_active()
            elif read_state()['pending']:
                await refresh()
        except Exception as exc:
            logger.warning('model_watch_refresh_failed', extra={'event':'model_watch_refresh_failed', 'error_type':type(exc).__name__})
        await asyncio.sleep(interval)
