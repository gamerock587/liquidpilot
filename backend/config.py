from pathlib import Path
import json
import os
from pydantic import BaseModel, Field, field_validator

ROOT = Path(__file__).resolve().parents[1]

class Settings(BaseModel):
    port: int = 7870
    decision_url: str = 'http://127.0.0.1:8081'
    decision_key_file: str = '../runtime/local-api-key.txt'
    model_path: str = '../models/d1-3B-Q4_K_M.gguf'
    projector_path: str = '../models/mmproj-d1-3B-Q8_0.gguf'
    llama_path: str = '../runtime/llama/llama-server.exe'
    planner_url: str = ''
    planner_model: str = ''
    planner_adapter: str = 'openai'
    search_provider: str = 'duckduckgo'
    searxng_url: str = ''
    private_origins: list[str] = Field(default_factory=list)
    decision_min_probability: float = Field(default=.42, ge=0, le=1)
    headless: bool = True
    max_tabs: int = Field(default=3, ge=1, le=5)
    timeout_ms: int = Field(default=15000, ge=1000, le=60000)
    retention_days: int = Field(default=30, ge=1, le=365)
    workspace: str = 'workspace'

    @field_validator('decision_url', 'planner_url')
    @classmethod
    def local_models(cls, value):
        from urllib.parse import urlsplit
        if value and (urlsplit(value).scheme != 'http' or urlsplit(value).hostname not in {'127.0.0.1', 'localhost', '::1'}):
            raise ValueError('Model adapters must use a local HTTP server.')
        return value.rstrip('/')

    def path(self, value: str) -> Path:
        path = Path(value)
        return (ROOT / path).resolve() if not path.is_absolute() else path.resolve()

    @property
    def work(self):
        return self.path(self.workspace)

def load_settings():
    path = Path(os.environ.get('LIQUIDPILOT_CONFIG', ROOT / 'config/settings.json'))
    return Settings(**json.loads(path.read_text(encoding='utf-8-sig'))) if path.exists() else Settings()
