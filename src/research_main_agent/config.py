"""Local configuration and secret redaction without GPT Researcher imports."""

import json
import os
from dataclasses import dataclass, field
from pathlib import Path

from dotenv import dotenv_values

PROJECT_ROOT = Path(__file__).resolve().parents[2]


class AgentError(Exception):
    """A safe, user-facing error that never includes provider response bodies."""


class Redactor:
    def __init__(self, secrets: list[str] | None = None):
        self.secrets = sorted(set(value for value in (secrets or []) if value), key=len, reverse=True)

    def text(self, value: str) -> str:
        for secret in self.secrets:
            value = value.replace(secret, "[REDACTED]")
        return value

    def data(self, value):
        if isinstance(value, str):
            return self.text(value)
        if isinstance(value, list):
            return [self.data(item) for item in value]
        if isinstance(value, dict):
            return {self.text(str(key)): self.data(item) for key, item in value.items()}
        return value


@dataclass
class Settings:
    api_key: str = field(repr=False)
    base_url: str
    model: str = "glm-4.7-flash"
    timeout: float = 60
    extra_body: dict = field(default_factory=dict)
    redactor: Redactor = field(default_factory=Redactor, repr=False)

    @classmethod
    def load(cls, env_path: Path) -> "Settings":
        local = dict(dotenv_values(env_path)) if env_path.exists() else {}

        def get(name: str, default: str = "") -> str:
            return os.environ.get(name, local.get(name) or default)

        key = get("OPENAI_API_KEY")
        if not key.strip():
            raise AgentError("未配置 OPENAI_API_KEY，请检查项目 .env 或环境变量。")
        model = get("MODEL_NAME", "glm-4.7-flash")
        raw_extra = get("LLM_EXTRA_BODY")
        try:
            extra = json.loads(raw_extra) if raw_extra else (
                {"thinking": {"type": "disabled"}} if "glm-4.7-flash" in model.lower() else {}
            )
            timeout = float(get("REQUEST_TIMEOUT", "60"))
            if not isinstance(extra, dict) or timeout <= 0:
                raise ValueError
        except (ValueError, TypeError):
            raise AgentError("REQUEST_TIMEOUT 必须为正数，LLM_EXTRA_BODY 必须为 JSON 对象。") from None
        combined = {**local, **os.environ}
        secrets = [value for name, value in combined.items() if value and (
            name.endswith(("_API_KEY", "_TOKEN", "_SECRET", "_PASSWORD"))
        )]
        secrets.append(key)
        return cls(key, get("OPENAI_BASE_URL", "https://api.openai.com/v1"), model,
                   timeout, extra, Redactor(secrets))
