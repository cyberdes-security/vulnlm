"""Accounts HTTP endpoints."""
import secrets
import time
from decimal import Decimal
from fastapi import Depends, HTTPException, Request, Response
from sqlalchemy import select, delete
from database import get_db
from models import User, SessionRecord, SessionPolicy
from schemas import Login, UserUpdate
from auth import current_user, admin_user, sign_token, decode_token, validate_session_claims
from scenario_controls import enabled
from fastapi import APIRouter

router = APIRouter()

@router.post('/auth/login')
async def login(data: Login,response: Response,db=Depends(get_db)):
    user=await db.scalar(select(User).where(User.email==data.email,User.password==data.password))
    if not user: raise HTTPException(401,'Invalid lab credentials')
    token=secrets.token_urlsafe(32)
    db.add(SessionRecord(token=token,user_id=user.id))
    db.add(SessionPolicy(token=token,user_id=user.id,expires_at=Decimal(str(time.time()+3600))))
    await db.commit()
    response.set_cookie('lab_session',token,httponly=True,samesite='lax')
    return {'id':user.id,'role':user.role,'access_token':sign_token(user,token)}

@router.post('/auth/logout')
async def logout(request: Request,response: Response,db=Depends(get_db)):
    # INTENTIONAL: logout revokes this cookie session only, not bearer JWTs.
    token=request.cookies.get('lab_session')
    if token:
        await db.execute(delete(SessionRecord).where(SessionRecord.token==token))
        await db.execute(delete(SessionPolicy).where(SessionPolicy.token==token))
        await db.commit()
    response.delete_cookie('lab_session')
    return {'status':'logged_out'}

@router.post('/auth/validate')
async def validate_token(request: Request,db=Depends(get_db)):
    claims=decode_token((await request.json()).get('token',''))
    await validate_session_claims(claims,db)
    return {'claims':claims}

@router.get('/me')
async def me(user=Depends(current_user),db=Depends(get_db)):
    row=await db.get(User,user['id'])
    return {'id':row.id,'name':row.name,'role':user['role'],'balance':str(row.balance)}

@router.get('/admin/users')
async def admin_users(user=Depends(admin_user),db=Depends(get_db)):
    return [{'id':u.id,'name':u.name,'role':u.role} for u in (await db.scalars(select(User))).all()]

@router.put('/user/update')
async def update_user(data: UserUpdate,user=Depends(current_user),db=Depends(get_db)):
    row=await db.get(User,user['id'])
    if data.role is not None and not enabled('mass-assignment'):
        raise HTTPException(403,'Profile updates cannot change roles')
    for key,value in data.model_dump(exclude_none=True).items(): setattr(row,key,value)
    await db.commit()
    return {'id':row.id,'name':row.name,'role':row.role}
