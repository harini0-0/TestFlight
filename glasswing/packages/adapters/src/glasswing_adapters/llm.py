"""OpenAI-compatible chat client for the configured DeepSeek deployment."""

from __future__ import annotations

import os
from pathlib import Path

import httpx

MODEL_ID = "/deployments/506a9a37/deepseek-ai/DeepSeek-V4.1-Flash"


class LlmError(Exception):
    def __init__(self, detail: str) -> None:
        super().__init__(detail)
        self.detail = detail


class ChatClient:
    def __init__(
        self,
        *,
        api_key: str,
        base_url: str,
        transport: httpx.BaseTransport | None = None,
        timeout: float = 120,
    ) -> None:
        self.api_key = api_key
        self.base_url = base_url.rstrip("/")
        self.model_id = MODEL_ID
        self._transport = transport
        self._timeout = timeout

    def complete(self, system: str, user: str) -> str:
        payload = {
            "model": self.model_id,
            "temperature": 0,
            "response_format": {"type": "json_object"},
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
        }
        headers = {"Authorization": f"Bearer {self.api_key}"}
        client_kwargs: dict = {"timeout": self._timeout}
        if self._transport is not None:
            client_kwargs["transport"] = self._transport
        try:
            with httpx.Client(**client_kwargs) as client:
                response = client.post(chat_completions_url(self.base_url), json=payload, headers=headers)
        except httpx.HTTPError as exc:
            raise LlmError("the model request failed") from exc
        if response.status_code == 401:
            raise LlmError("the model rejected the API key")
        if response.status_code >= 400:
            raise LlmError(f"the model request failed ({response.status_code})")
        try:
            message = response.json()["choices"][0]["message"]
            content = message.get("content")
        except (KeyError, IndexError, TypeError, ValueError) as exc:
            raise LlmError("the model returned an empty response") from exc
        if isinstance(content, list):
            content = "".join(str(part.get("text", "")) for part in content if isinstance(part, dict))
        if not isinstance(content, str) or not content.strip():
            raise LlmError("the model returned an empty response")
        return content


def chat_completions_url(base_url: str) -> str:
    """Join a base such as https://api.sciforium.com/v1 without dropping /v1."""
    return base_url.rstrip("/") + "/chat/completions"


def load_env_file(path: Path | None = None) -> None:
    file = path or Path(".env")
    if not file.is_file():
        return
    for raw in file.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


def llm_enabled() -> bool:
    if os.environ.get("GLASSWING_LLM", "").strip().lower() == "recording":
        return False
    return bool(os.environ.get("GLASSWING_LLM_API_KEY", "").strip())


def chat_client_from_env() -> ChatClient:
    key = os.environ.get("GLASSWING_LLM_API_KEY", "").strip()
    base = os.environ.get("GLASSWING_LLM_BASE_URL", "").strip()
    if not key:
        raise LlmError("GLASSWING_LLM_API_KEY is not set")
    if not base:
        raise LlmError("GLASSWING_LLM_BASE_URL is not set")
    return ChatClient(api_key=key, base_url=base)
