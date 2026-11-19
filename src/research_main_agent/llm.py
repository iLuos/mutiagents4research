"""OpenAI-compatible JSON adapter with bounded SDK and validation retries."""

import json
from typing import Protocol, TypeVar

from langchain_openai import ChatOpenAI
from openai import APIError
from pydantic import BaseModel, ValidationError

from .config import AgentError, Settings

T = TypeVar("T", bound=BaseModel)


class StructuredModel(Protocol):
    def generate(self, schema: type[T], system: str, payload: dict) -> T: ...


class JsonChatModel:
    def __init__(self, settings: Settings, client=None):
        self.client = client if client is not None else ChatOpenAI(
            model=settings.model,
            api_key=settings.api_key,
            base_url=settings.base_url,
            temperature=0,
            timeout=settings.timeout,
            max_retries=1,
            max_tokens=6000,
            extra_body=settings.extra_body,
        )

    def generate(self, schema: type[T], system: str, payload: dict) -> T:
        schema_text = json.dumps(schema.model_json_schema(), ensure_ascii=False)
        messages = [
            {"role": "system", "content": system + "\nJSON Schema:\n" + schema_text},
            {"role": "user", "content": json.dumps(payload, ensure_ascii=False)},
        ]
        for attempt in range(2):
            try:
                response = self.client.invoke(messages)
            except (APIError, TimeoutError, ConnectionError):
                raise AgentError("模型请求失败或超时。已保留当前会话，可输入 /retry 重试或 /exit 退出。") from None
            content = getattr(response, "content", None)
            try:
                if not isinstance(content, str):
                    raise ValueError("Expected text JSON")
                result = json.loads(content)
                return schema.model_validate(result)
            except (ValueError, ValidationError, TypeError):
                if attempt == 0:
                    # Do not repeat invalid provider output in logs or repair messages.
                    messages.append({"role": "user", "content":
                        "上次响应不是符合 schema 的 JSON。请重新生成完整 JSON 对象，禁止 Markdown 代码围栏。"
                        "检查必填项、最多三个问题、四个子任务的顺序与前置依赖。"})
        raise AgentError("模型输出两次未通过结构校验。已保留当前会话，可输入 /retry 或 /exit。")
