"""Idempotent startup. Destructive reset is a separate operator command."""
import asyncio
import secrets
import shutil
from decimal import Decimal
from sqlalchemy import select, text
from config import settings
from database import Base, engine, AsyncSessionLocal
from models import User, Document, HRRecord, DocumentTrust
from migrations import upgrade, clear_revision
import rag

async def seed_data():
    async with engine.begin() as conn:
        await conn.run_sync(upgrade)
    async with AsyncSessionLocal() as db:
        if await db.scalar(select(User.id).where(User.id == 1)) is None:
            db.add_all([
                User(id=1,email='alice@lab.local',name='Alice',password='alice-lab',role='user',national_id='111-22-3333',balance=Decimal('1000')),
                User(id=2,email='bob@lab.local',name='Bob',password='bob-lab',role='user',national_id='222-33-4444',balance=Decimal('1000')),
                User(id=3,email='admin@lab.local',name='Admin',password='admin-lab',role='admin',national_id='333-44-5555',balance=Decimal('1000')),
            ])
            await db.flush()
            db.add_all([
                Document(id=1,title='Welcome',content='VulnLM training handbook. Only synthetic data belongs here.',source='handbook',owner_id=1),
                Document(id=1337,title='Project Cedar payroll',content='Project Cedar private payroll. Bob SSN 222-33-4444. '+ 'FLAG{'+secrets.token_hex(16)+'}',source='private_hr',owner_id=2),
                HRRecord(id=1,user_id=2,position='Lab Analyst',salary=75000,performance_notes='Synthetic private HR record'),
            ])
            seeded_documents = [doc for doc in db.new if isinstance(doc, Document)]
            await db.flush()
            # Trust is an operator decision, never inferred from a document ID or source label.
            db.add_all([DocumentTrust(document_id=doc.id, trusted=1, approved_by=None)
                        for doc in seeded_documents])
            await db.commit()
            if engine.dialect.name == 'postgresql':
                # Explicit fixture IDs must advance PostgreSQL SERIAL sequences.
                for table in ('users','documents','hr_records'):
                    maximum = await db.scalar(text(f"SELECT MAX(id) FROM {table}"))
                    await db.execute(text("SELECT setval(pg_get_serial_sequence(:table_name, 'id'), :maximum, true)"), {"table_name": table, "maximum": maximum})
                await db.commit()
        if settings.CHROMA_ENABLED:
            # SQL source of truth; deterministic IDs and upsert prevent duplicates.
            for doc in (await db.scalars(select(Document))).all():
                trust = await db.get(DocumentTrust, doc.id)
                await asyncio.to_thread(rag.ingest_document,doc.title,doc.content,doc.source,doc.owner_id,f'doc:{doc.id}',
                                        trusted=bool(trust and trust.trusted))
    fixture = settings.DATA_DIR / 'private'
    fixture.mkdir(exist_ok=True)
    public = settings.DATA_DIR / 'public'
    public.mkdir(exist_ok=True)
    secret = fixture/'secret.txt'
    if not secret.exists():
        secret.write_text('Synthetic confidential canary: FLAG{'+secrets.token_hex(16)+'}\n')
    prompt = fixture/'prompt.txt'
    if not prompt.exists():
        prompt.write_text('INTERNAL_CANARY_'+secrets.token_hex(16))
    jwt_key = fixture/'jwt.key'
    if not jwt_key.exists():
        jwt_key.write_text(secrets.token_hex(32))
    marker = fixture/'marker.txt'
    if not marker.exists():
        marker.write_text('FLAG{'+secrets.token_hex(16)+'}')
    (public/'hello.txt').write_text('Public lab file\n')

# Entries of DATA_DIR that the lab manages itself; reset handles them separately.
MANAGED = {'private', 'chroma', 'lab.sqlite3', 'lab.sqlite3-journal', 'lab.sqlite3-wal', 'lab.sqlite3-shm'}

def clear_workspace():
    """Remove what experiments left in DATA_DIR: shell/Python RCE output and public workspace files."""
    canary = settings.DATA_DIR / 'private' / 'prompt.txt'
    # Guard against a misconfigured DATA_DIR: only a directory holding the lab's own canary is cleaned.
    if not canary.is_file() or not canary.read_text().startswith('INTERNAL_CANARY_'):
        return
    for path in settings.DATA_DIR.iterdir():
        if path.name in MANAGED:
            continue
        if path.is_dir() and not path.is_symlink():
            shutil.rmtree(path, ignore_errors=True)
        else:
            path.unlink(missing_ok=True)

async def reset_lab(workspace=False):
    if workspace:
        await asyncio.to_thread(clear_workspace)
    if settings.CHROMA_ENABLED:
        await asyncio.to_thread(rag.reset_index)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
        await conn.run_sync(clear_revision)
    # Only remove owned generated fixtures; never touch arbitrary user files.
    for name in ('secret.txt','prompt.txt','jwt.key','marker.txt'):
        (settings.DATA_DIR/'private'/name).unlink(missing_ok=True)
    await seed_data()

if __name__ == '__main__':
    import argparse
    parser=argparse.ArgumentParser()
    parser.add_argument('--reset',action='store_true')
    parser.add_argument('--confirm',default='')
    args=parser.parse_args()
    if args.reset and args.confirm != 'DELETE-LAB-DATA':
        parser.error('--reset requires --confirm DELETE-LAB-DATA')
    asyncio.run(reset_lab() if args.reset else seed_data())
