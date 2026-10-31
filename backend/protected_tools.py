"""Constrained tool implementations that preserve legitimate lab operations."""
import asyncio
import ipaddress
import json
import shlex
import socket
import sqlite3
from urllib.parse import urlsplit, urlunsplit
import httpx
from fastapi import HTTPException
from sqlalchemy import select
from config import settings
from models import User, Document, Memory, Transaction


def public_path(value):
    base=(settings.DATA_DIR/'public').resolve()
    result=(base/value).resolve()
    if not result.is_relative_to(base):
        raise HTTPException(403,'Files must remain in the public workspace')
    return result


async def shell(command, process):
    try:
        args=shlex.split(command)
    except ValueError as exc:
        raise HTTPException(422,'Invalid command syntax') from exc
    if not args:
        raise HTTPException(422,'Provide a command')
    output=None; append=False
    if '>' in args or '>>' in args:
        marker='>>' if '>>' in args else '>'
        i=args.index(marker)
        if i != len(args)-2:
            raise HTTPException(422,'Use a single output file')
        output=public_path(args[-1]);append=marker=='>>';args=args[:i]
    if not args or args[0] not in {'echo','printf','pwd','id','ls','cat','head','wc'}:
        raise HTTPException(403,'Protected shell supports echo, printf, pwd, id, ls, cat, head, and wc')
    if any(token in {'|','||','&&',';','&','<','>','>>'} or '\n' in token for token in args):
        raise HTTPException(403,'Shell operators are not supported')
    name=args[0]
    if name in {'pwd','id'} and len(args)>1:
        raise HTTPException(422,'This command takes no arguments')
    if name in {'ls','cat','head','wc'}:
        allowed={'ls':{'-l','-a','-h','-la','-al'},'cat':{'-n'},'head':{'-n'},'wc':{'-l','-w','-c'}}[name]
        need_number=False
        for i,arg in enumerate(args[1:],1):
            if need_number:
                if not arg.isdigit() or not 1<=int(arg)<=1000:
                    raise HTTPException(422,'Line count must be between 1 and 1000')
                need_number=False;continue
            if arg.startswith('-'):
                if arg not in allowed:raise HTTPException(403,'Unsupported command option')
                need_number=name=='head' and arg=='-n'
            else:
                args[i]=str(public_path(arg))
        if need_number:raise HTTPException(422,'Missing line count')
    result=await process(*args,cwd=settings.DATA_DIR/'public')
    if output is not None and result['exit_code']==0:
        with output.open('a' if append else 'w') as target:
            target.write(result['stdout'])
        result={**result,'stdout':''}
    return result


async def sql_snapshot(db, query, actor):
    """Execute SELECT queries against actual user-visible data in an isolated SQLite snapshot."""
    if actor is None:raise HTTPException(401,'Authentication required for protected SQL')
    admin=actor.get('role')=='admin'
    tables={}
    users=select(User.id,User.name,User.email,User.role,User.balance)
    if not admin:users=users.where(User.id==actor['id'])
    docs=select(Document.id,Document.owner_id,Document.title,Document.content,Document.source)
    memories=select(Memory.id,Memory.owner_id,Memory.content)
    transactions=select(Transaction.id,Transaction.user_id,Transaction.amount,Transaction.to_iban)
    if not admin:
        docs=docs.where(Document.owner_id==actor['id'])
        memories=memories.where(Memory.owner_id==actor['id'])
        transactions=transactions.where(Transaction.user_id==actor['id'])
    for name,statement in [('users',users),('documents',docs),('memories',memories),('transactions',transactions)]:
        result=await db.execute(statement.limit(1000))
        tables[name]=(list(result.keys()),[tuple(str(value) if value is not None else None for value in row) for row in result])
    def run():
        connection=sqlite3.connect(':memory:')
        try:
            for name,(columns,rows) in tables.items():
                connection.execute(f'CREATE TABLE {name} ({",".join(columns)})')
                connection.executemany(f'INSERT INTO {name} VALUES ({",".join("?" for _ in columns)})',rows)
            allowed={sqlite3.SQLITE_SELECT,sqlite3.SQLITE_READ,sqlite3.SQLITE_FUNCTION}
            connection.set_authorizer(lambda action,*args:sqlite3.SQLITE_OK if action in allowed and not (action==sqlite3.SQLITE_FUNCTION and str(args[1]).lower()=='load_extension') else sqlite3.SQLITE_DENY)
            ticks=0
            def progress():
                nonlocal ticks
                ticks+=1
                return ticks>1000
            connection.set_progress_handler(progress,1000)
            cursor=connection.execute(query)
            if not cursor.description:raise ValueError('Use a SELECT query')
            names=[col[0] for col in cursor.description]
            return [dict(zip(names,row)) for row in cursor.fetchmany(1000)]
        except (sqlite3.Error,ValueError) as exc:
            raise HTTPException(422,'Protected SQL accepts read-only queries over users, documents, memories, and transactions') from exc
        finally:
            connection.close()
    return await asyncio.to_thread(run)


async def http_request(args):
    raw=args['url']
    try:
        url=urlsplit(raw)
        if url.scheme not in {'http','https'} or not url.hostname or url.username or url.password or url.fragment:
            raise ValueError('Use an HTTP(S) URL without credentials or fragments')
        port=url.port or (443 if url.scheme=='https' else 80)
        explicitly_allowed=raw in settings.SAFE_HTTP_URLS
        target=raw
        extensions={};headers={}
        if not explicitly_allowed:
            answers=await asyncio.to_thread(socket.getaddrinfo,url.hostname,port,type=socket.SOCK_STREAM)
            addresses={item[4][0] for item in answers}
            if not addresses or any(not ipaddress.ip_address(ip).is_global for ip in addresses):
                raise HTTPException(403,'Private, local, and reserved HTTP destinations are not allowed')
            # Pin the validated destination; a second DNS lookup must not change it.
            ip=sorted(addresses)[0];host=f'[{ip}]' if ':' in ip else ip
            target=urlunsplit((url.scheme,f'{host}:{port}',url.path or '/',url.query,''))
            headers={'Host':url.netloc}
            extensions={'sni_hostname':url.hostname.encode('ascii')}
        async with httpx.AsyncClient(timeout=5,trust_env=False,follow_redirects=False) as client:
            async with client.stream(args.get('method','GET'),target,json=args.get('body'),headers=headers,extensions=extensions) as response:
                if 300 <= response.status_code < 400:
                    raise HTTPException(403,'HTTP redirects are not followed in protected mode')
                body=bytearray()
                async for chunk in response.aiter_bytes():
                    body.extend(chunk[:max(0,65536-len(body))])
                    if len(body)>=65536:break
                return {'status':response.status_code,'body':body.decode(errors='replace')}
    except httpx.HTTPError as exc:
        raise HTTPException(502,'HTTP destination could not be reached') from exc
    except (ValueError,UnicodeError,socket.gaierror) as exc:
        raise HTTPException(422,'Invalid or unresolved HTTP destination') from exc
