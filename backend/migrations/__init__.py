"""Ordered, transactional schema upgrades for SQLite and PostgreSQL.

The initial schema is frozen in v001; future changes belong in new revisions.
Existing unversioned databases are adopted only after baseline column validation.
"""
import logging
from sqlalchemy import MetaData, Table, Column, Integer, DateTime, func, inspect, select
from . import v001_initial, v002_document_trust, v003_external_site

logger = logging.getLogger('vulnlm.operations')
metadata = MetaData()
revisions = Table('schema_migrations', metadata,
    Column('revision', Integer, primary_key=True),
    Column('applied_at', DateTime, nullable=False, server_default=func.now()))
MIGRATIONS = ((1, v001_initial), (2, v002_document_trust), (3, v003_external_site))
HEAD = MIGRATIONS[-1][0]

def upgrade(connection):
    # Serialize startup upgrades across workers. Explicit BEGIN also makes SQLite DDL transactional.
    if connection.dialect.name == 'postgresql':
        connection.exec_driver_sql('SELECT pg_advisory_xact_lock(864920137)')
    elif connection.dialect.name == 'sqlite':
        connection.exec_driver_sql('BEGIN IMMEDIATE')
    inspector = inspect(connection)
    if inspector.has_table('schema_migrations'):
        applied = list(connection.execute(select(revisions.c.revision).order_by(revisions.c.revision)).scalars())
    else:
        applied = []
    if applied != list(range(1, len(applied) + 1)) or (applied and applied[-1] > HEAD):
        raise RuntimeError('Unsupported database revision; upgrade the application before starting. Existing data was preserved.')
    if not applied:
        for table in v001_initial.Base.metadata.sorted_tables:
            if inspector.has_table(table.name):
                existing = {c['name'] for c in inspector.get_columns(table.name)}
                if not set(table.columns.keys()) <= existing:
                    raise RuntimeError('Incompatible database schema detected. Restore a compatible backup or use a separate lab database. Existing data was preserved.')
    metadata.create_all(connection)
    for revision, migration in MIGRATIONS:
        if revision not in applied:
            migration.upgrade(connection)
            connection.execute(revisions.insert().values(revision=revision))
            logger.info('schema_upgrade', extra={'event':'schema_upgrade', 'revision':revision})
    # Fail early if an externally edited/versioned database is missing application columns.
    inspector = inspect(connection)
    for table in [*v001_initial.Base.metadata.sorted_tables, v002_document_trust.trust]:
        if table.name in v003_external_site.DROPPED:
            continue
        if not inspector.has_table(table.name) or not set(table.columns.keys()) <= {c['name'] for c in inspector.get_columns(table.name)}:
            raise RuntimeError('Database schema differs from its recorded revision; restore a compatible backup.')
    return HEAD

def clear_revision(connection):
    """Only called by the explicitly destructive lab reset, after application tables are dropped."""
    revisions.drop(connection, checkfirst=True)

async def migrate():
    from database import engine
    async with engine.begin() as connection:
        await connection.run_sync(upgrade)

if __name__ == '__main__':
    import asyncio
    asyncio.run(migrate())
