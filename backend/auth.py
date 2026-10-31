"""Cookie and JWT authentication with configurable lab verification controls."""
import base64
import hashlib
import hmac
import json
import time
from sqlalchemy import select
from fastapi import Request, HTTPException, Depends
from database import get_db
from models import SessionRecord, SessionPolicy, User
from scenario_controls import enabled
from config import settings

def b64(data):
    return base64.urlsafe_b64encode(data).rstrip(b'=').decode()
def unb64(data):
    return base64.urlsafe_b64decode(data + '=' * (-len(data) % 4))
def sign_token(user, session_token=None):
    header=b64(json.dumps({'alg':'HS256','typ':'JWT'}).encode())
    payload=b64(json.dumps({'sub':user.id,'role':user.role,'exp':int(time.time())+3600,'sid':session_token}).encode())
    body=f'{header}.{payload}'
    key=(settings.DATA_DIR/'private/jwt.key').read_bytes()
    signature=b64(hmac.new(key,body.encode(),hashlib.sha256).digest())
    return f'{body}.{signature}'
def decode_token(token):
    try:
        header,payload,signature=token.split('.')
        alg=json.loads(unb64(header)).get('alg')
        claims=json.loads(unb64(payload))
        if alg == 'HS256':
            key=(settings.DATA_DIR/'private/jwt.key').read_bytes()
            expected=b64(hmac.new(key,f'{header}.{payload}'.encode(),hashlib.sha256).digest())
            if not hmac.compare_digest(signature,expected): raise ValueError('Bad signature')
        elif alg == 'none' and enabled('jwt-none'):
            pass  # INTENTIONAL: attacker-controlled algorithm disables verification.
        else:
            raise ValueError('Unsupported algorithm')
        if claims.get('exp',0) < time.time(): raise ValueError('Expired')
        if not isinstance(claims.get('sub'),int): raise ValueError('Bad subject')
        return claims
    except (ValueError,TypeError,KeyError,AttributeError):
        raise HTTPException(401,'Invalid token')

async def current_user(request: Request, db=Depends(get_db)):
    authorization=request.headers.get('authorization','')
    if authorization.startswith('Bearer '):
        claims=decode_token(authorization[7:])
        user=await db.get(User,claims['sub'])
        if not user: raise HTTPException(401,'Unknown user')
        # INTENTIONAL: a correctly signed JWT keeps stale roles after demotion.
        await validate_session_claims(claims, db)
        role=claims.get('role','user') if enabled('stale-jwt-role') else user.role
        return {'id':user.id,'role':role}
    token=request.cookies.get('lab_session')
    user_id=await db.scalar(select(SessionRecord.user_id).where(SessionRecord.token==token)) if token else None
    user=await db.get(User,user_id) if user_id is not None else None
    if not user: raise HTTPException(401,'Log in with a synthetic lab account')
    if not enabled('session-lifecycle'):
        policy=await db.get(SessionPolicy,token)
        if not policy or float(policy.expires_at) <= time.time():
            raise HTTPException(401,'Session expired; log in again')
    return {'id':user.id,'role':user.role}
async def admin_user(user=Depends(current_user)):
    if user['role']!='admin': raise HTTPException(403,'Admin role required')
    return user


async def validate_session_claims(claims, db):
    if not enabled('session-lifecycle'):
        sid=claims.get('sid')
        session=await db.get(SessionRecord,sid) if isinstance(sid,str) else None
        policy=await db.get(SessionPolicy,sid) if session else None
        if not session or session.user_id != claims['sub'] or not policy or float(policy.expires_at) <= time.time():
            raise HTTPException(401,'Session revoked or expired; log in again')


async def settings_operator(request: Request, db=Depends(get_db)):
    # Lab JWT and role-escalation exercises cannot grant settings write access.
    token=request.cookies.get('lab_session')
    session=await db.get(SessionRecord,token) if token else None
    user=await db.get(User,session.user_id) if session else None
    policy=await db.get(SessionPolicy,token) if session else None
    if not user or user.id != 3 or user.email != 'admin@lab.local' or user.role != 'admin':
        raise HTTPException(403,'Sign in with the Admin demo account to manage lab settings')
    if not policy or float(policy.expires_at) <= time.time():
        raise HTTPException(401,'Log in again to manage lab settings')
    return {'id':user.id,'role':user.role}
