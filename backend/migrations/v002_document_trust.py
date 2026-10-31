"""Operator-managed document provenance, separate from caller-supplied source labels."""
from sqlalchemy import MetaData, Table, Column, Integer, DateTime, ForeignKey, func
metadata = MetaData()
Table('documents', metadata, Column('id', Integer, primary_key=True))
trust = Table('document_trust', metadata,
    Column('document_id', Integer, ForeignKey('documents.id'), primary_key=True),
    Column('trusted', Integer, nullable=False, server_default='0'),
    Column('approved_by', Integer, nullable=True),
    Column('updated_at', DateTime, nullable=False, server_default=func.now()))

def upgrade(connection):
    trust.create(connection, checkfirst=True)
