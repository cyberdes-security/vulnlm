"""Covert-channel cache medium shared by two network-isolated lab agents."""
from sqlalchemy import MetaData, Table, Column, Integer, String, Text
metadata = MetaData()
media = Table('covert_cache_media', metadata,
    Column('owner_id', Integer, primary_key=True),
    Column('medium_key', String, primary_key=True),
    Column('state_json', Text, nullable=False, server_default='{}'))

def upgrade(connection):
    media.create(connection, checkfirst=True)
