"""Sub-agent delegation records: grant, acting role, handed-over context, report and trace."""
from sqlalchemy import MetaData, Table, Column, Integer, String, Text
metadata = MetaData()
runs = Table('sub_agent_runs', metadata,
    Column('id', Integer, primary_key=True),
    Column('owner_id', Integer, nullable=False, index=True),
    Column('parent_id', Integer, nullable=True),
    Column('tree_id', String, nullable=False, index=True),
    Column('depth', Integer, nullable=False),
    Column('role', String, nullable=False),
    Column('task', Text, nullable=False),
    Column('requested_tools_json', Text, nullable=False),
    Column('granted_tools_json', Text, nullable=False),
    Column('acting_role', String, nullable=False),
    Column('context_json', Text, nullable=False),
    Column('status', String, nullable=False, server_default='active'),
    Column('report_json', Text, nullable=True),
    Column('trace_json', Text, nullable=True),
    Column('llm_calls', Integer, nullable=False, server_default='0'))

def upgrade(connection):
    runs.create(connection, checkfirst=True)
