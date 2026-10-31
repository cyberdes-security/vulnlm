from sqlalchemy import Column, Integer, String, Text, Numeric, ForeignKey, DateTime, func
from sqlalchemy.orm import deferred
from database import Base

class User(Base):
    __tablename__ = 'users'
    id = Column(Integer, primary_key=True)
    email = Column(String, unique=True)
    name = Column(String)
    # Credentials remain plaintext for the lab, but normal entity reads do not
    # need to return them. Login compares the column in SQL, not in Python.
    password = deferred(Column(String), raiseload=True)
    phone = Column(String, default='555-0100')
    address = Column(String, default='Synthetic Lab Street')
    national_id = Column(String)
    role = Column(String, default='user')
    balance = Column(Numeric(14, 2), default=1000)

class Transaction(Base):
    __tablename__ = 'transactions'
    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey('users.id'))
    amount = Column(Numeric(14, 2))
    currency = Column(String, default='USD')
    to_iban = Column(String)
    from_iban = Column(String)
    description = Column(String)

class HRRecord(Base):
    __tablename__ = 'hr_records'
    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey('users.id'))
    position = Column(String)
    salary = Column(Numeric(14, 2))
    performance_notes = Column(Text)

class Document(Base):
    __tablename__ = 'documents'
    id = Column(Integer, primary_key=True)
    title = Column(String)
    content = Column(Text)
    source = Column(String)
    owner_id = Column(Integer)

class AuditLog(Base):
    __tablename__ = 'audit_logs'
    id = Column(Integer, primary_key=True)
    timestamp = Column(DateTime, default=func.now())
    user_message = Column(Text)
    model_prompt = Column(Text)
    model_response = Column(Text)
    topic = Column(String)
    tools_used = Column(Text)

class Memory(Base):
    __tablename__ = 'memories'
    id = Column(Integer, primary_key=True)
    owner_id = Column(Integer)
    content = Column(Text)

class SessionRecord(Base):
    __tablename__ = 'sessions'
    token = Column(String, primary_key=True)
    user_id = Column(Integer)

class RegisteredTool(Base):
    __tablename__ = 'registered_tools'
    name = Column(String, primary_key=True)
    description = Column(Text)
    target = Column(String)
    defaults_json = Column(Text, default='{}')
    revision = Column(Integer, default=1)
    approved_revision = Column(Integer, nullable=True)

class SavedReport(Base):
    __tablename__ = 'saved_reports'
    id = Column(Integer, primary_key=True)
    owner_id = Column(Integer)
    name_filter = Column(String)

class ChatTurn(Base):
    __tablename__ = 'chat_turns'
    id = Column(Integer, primary_key=True)
    conversation_id = Column(String,index=True)
    owner_id = Column(Integer)
    role = Column(String)
    content = Column(Text)


class ToolResultFixture(Base):
    __tablename__ = 'tool_result_fixtures'
    id = Column(Integer, primary_key=True)
    owner_id = Column(Integer)
    content = Column(Text)

class PaymentApproval(Base):
    __tablename__ = 'payment_approvals'
    id = Column(Integer, primary_key=True)
    owner_id = Column(Integer)
    proposed_json = Column(Text)
    approved_json = Column(Text, nullable=True)
    executed_json = Column(Text, nullable=True)

class AgentEnvelopeRecord(Base):
    __tablename__ = 'agent_envelopes'
    id = Column(Integer, primary_key=True)
    actor_id = Column(Integer)
    claimed_sender = Column(String)
    payload_json = Column(Text)
    result_json = Column(Text)


class SessionPolicy(Base):
    __tablename__ = 'session_policies'
    token = Column(String, primary_key=True)
    user_id = Column(Integer)
    expires_at = Column(Numeric(20, 4))


class TransferRequest(Base):
    __tablename__ = 'transfer_requests'
    key = Column(String, primary_key=True)
    fingerprint = Column(Text)
    result_json = Column(Text)


class AuditOwner(Base):
    __tablename__ = 'audit_owners'
    audit_id = Column(Integer, primary_key=True)
    owner_id = Column(Integer, index=True)


class ToolApproval(Base):
    __tablename__ = 'tool_approvals'
    id = Column(Integer, primary_key=True)
    owner_id = Column(Integer)
    tool = Column(String)
    arguments_json = Column(Text)
    executed_json = Column(Text, nullable=True)


class ConversationOwnership(Base):
    __tablename__ = 'conversation_ownership'
    id = Column(String, primary_key=True)
    owner_id = Column(Integer)


class DocumentTrust(Base):
    __tablename__ = 'document_trust'
    document_id = Column(Integer, ForeignKey('documents.id'), primary_key=True)
    trusted = Column(Integer, nullable=False, default=0)
    approved_by = Column(Integer, nullable=True)
    updated_at = Column(DateTime, default=func.now(), onupdate=func.now(), nullable=False)
