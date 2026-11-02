"""Deployment boundaries are separate from intentionally broken application controls."""
from pathlib import Path
from pydantic_settings import BaseSettings, SettingsConfigDict

class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file='.env', extra='ignore')
    DATA_DIR: Path = Path(__file__).resolve().parent / 'lab_data'
    DATABASE_URL: str = ''
    LLM_API_URL: str = 'http://localhost:11434/v1/chat/completions'
    LLM_MODEL: str = 'qwen2.5:3b'  # Default model; Advanced settings can select another catalogue model.
    MODEL_GATEWAY_URL: str = ''  # Empty: native development talks to LLM_API_URL with no download management.
    VISION_MODEL: str = ''  # Opt-in: configure a model that accepts image_url inputs.
    SAFE_HTTP_URLS: list[str] = ['http://internal-service:9000/public', 'http://cyberdes-vulnerable-cloud.example/status']
    LLM_TIMEOUT: float = 180  # 14B catalogue models can need a cold load plus a long tool-calling prompt.
    MAX_AGENT_STEPS: int = 4  # Lab circuit breaker, NOT per-user budgeting.
    MAX_BATCH: int = 8
    TOOL_TIMEOUT: int = 3
    SECRET_ADMIN_API_KEY: str = 'lab-only-not-a-real-api-key'
    INTERNAL_DB_DSN: str = 'synthetic://lab-only'
    LAB_RESET_TOKEN: str = ''  # CLI reset works without exposing a public reset endpoint.
    CHROMA_ENABLED: bool = True
    @property
    def database_url(self):
        return self.DATABASE_URL or f'sqlite+aiosqlite:///{self.DATA_DIR.resolve() / "lab.sqlite3"}'
settings = Settings()
