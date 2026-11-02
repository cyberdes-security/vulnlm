"""Attacker pages moved to the separate external-site service; drop the in-app HTTP fixture table."""
DROPPED = {'tool_result_fixtures'}

def upgrade(connection):
    connection.exec_driver_sql('DROP TABLE IF EXISTS tool_result_fixtures')
