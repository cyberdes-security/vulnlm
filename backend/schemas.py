from decimal import Decimal
from typing import Any
from pydantic import BaseModel, Field, ConfigDict, StrictBool

class ChatRequest(BaseModel):
    message: str = Field(min_length=1)
    conversation_id: str | None = None
    pii_filter: bool = False
    use_tools: bool = True
class DocumentUpload(BaseModel):
    title: str
    content: str
    source: str = 'uploaded'
    user_id: int = 1
class SQLToolInput(BaseModel):
    query: str
class ShellToolInput(BaseModel):
    command: str
class HTTPToolInput(BaseModel):
    method: str = 'GET'
    url: str
    body: Any = None
class BusinessTransferInput(BaseModel):
    from_user_id: int
    to_user_id: int
    amount: Decimal  # INTENTIONAL: no gt=0 or balance constraint.
class BusinessRoleInput(BaseModel):
    user_id: int
    new_role: str
class BusinessDeleteHRInput(BaseModel):
    record_id: int
class ToolCall(BaseModel):
    name: str
    arguments: dict[str, Any] = Field(default_factory=dict)
class RegisterTool(BaseModel):
    name: str = Field(pattern=r'^[a-zA-Z][a-zA-Z0-9_]{0,63}$')
    description: str
    target: str
    defaults: dict[str, Any] = Field(default_factory=dict)
class Login(BaseModel):
    email: str
    password: str
class UserUpdate(BaseModel):
    model_config = ConfigDict(extra='forbid')
    name: str | None = None
    role: str | None = None  # INTENTIONAL mass assignment of a privileged field.
class MemoryInput(BaseModel):
    content: str
    owner_id: int = 1
class ReportInput(BaseModel):
    name_filter: str
class BatchInput(BaseModel):
    message: str
    repetitions: int = Field(ge=1)


class ToolResultInput(BaseModel):
    content: str = Field(min_length=1, max_length=32000)

class PaymentProposal(BaseModel):
    to_user_id: int
    amount: Decimal = Field(gt=0, max_digits=14, decimal_places=2)

class AgentEnvelope(BaseModel):
    sender: str = Field(pattern=r'^(researcher|supervisor)$')
    recipient: str = Field(default='executor', pattern=r'^executor$')
    tool: str = Field(pattern=r'^(remember|change_role|transfer_funds)$')
    arguments: dict[str, Any] = Field(default_factory=dict)

class AgentResearchInput(BaseModel):
    content: str = Field(min_length=1, max_length=32000)

class SubAgentSpawn(BaseModel):
    model_config = ConfigDict(extra='forbid')
    role: str = Field(pattern=r'^(researcher|analyst|operator)$')
    task: str = Field(min_length=1, max_length=8000)
    tools: list[str] | None = Field(default=None, max_length=16)

class SubAgentAction(BaseModel):
    model_config = ConfigDict(extra='forbid')
    tool: str = Field(min_length=1, max_length=64)
    arguments: dict[str, Any] = Field(default_factory=dict)

class SubAgentReport(BaseModel):
    model_config = ConfigDict(extra='forbid')
    summary: str = Field(max_length=32000)
    actions: list[SubAgentAction] = Field(default_factory=list, max_length=4)

class AgentRelay(BaseModel):
    model_config = ConfigDict(extra='forbid')
    sender: str = Field(pattern=r'^(A|B)$')
    recipient: str = Field(pattern=r'^(A|B)$')
    content: str = Field(min_length=1, max_length=4000)

class CovertExfiltrate(BaseModel):
    model_config = ConfigDict(extra='forbid')
    secret: str | None = Field(default=None, max_length=256)
    sender: str = Field(default='A', pattern=r'^(A|B)$')
    receiver: str = Field(default='B', pattern=r'^(A|B)$')

class CovertAgent(BaseModel):
    model_config = ConfigDict(extra='forbid')
    agent: str = Field(default='B', pattern=r'^(A|B)$')

class CovertSend(BaseModel):
    model_config = ConfigDict(extra='forbid')
    agent: str = Field(default='A', pattern=r'^(A|B)$')
    byte: int = Field(ge=0, le=255)

class ImageChatRequest(ChatRequest):
    image_data_url: str = Field(min_length=1, max_length=1400000)


class ScenarioSettingsUpdate(BaseModel):
    model_config = ConfigDict(extra='forbid')
    revision: int = Field(ge=0, strict=True)
    vulnerabilities: dict[str, StrictBool]

class ModelSelection(BaseModel):
    model_config = ConfigDict(extra='forbid')
    model: str = Field(min_length=1, max_length=100)

class ModelThinking(ModelSelection):
    enabled: StrictBool

class SystemReset(BaseModel):
    model_config = ConfigDict(extra='forbid')
    include_settings: StrictBool = True


class DocumentTrustUpdate(BaseModel):
    model_config = ConfigDict(extra='forbid')
    trusted: StrictBool
