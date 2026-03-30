"""Ollama native API provider."""

from __future__ import annotations

import asyncio
import logging
import os

import httpx

from productteam.errors import ProductTeamConfigError
from productteam.providers.base import LLMProvider

logger = logging.getLogger(__name__)

# Retry config for transient Ollama errors (500s, timeouts, connection resets)
_MAX_RETRIES = 6
_RETRY_BACKOFF_BASE = 3.0  # seconds — doubles each retry (3, 6, 12, 24, 48, 96)

# All httpx exceptions we treat as transient (Ollama can drop connections
# during long inferences, especially on large models)
_TRANSIENT_EXCEPTIONS = (
    httpx.HTTPStatusError,
    httpx.ReadTimeout,
    httpx.ConnectTimeout,
    httpx.ConnectError,
    httpx.RemoteProtocolError,
    httpx.ReadError,
)


class OllamaProvider(LLMProvider):
    """Ollama local LLM provider."""

    def __init__(
        self,
        model: str = "llama3",
        host: str = "",
    ):
        self._model = model
        self._host = (
            host
            or os.environ.get("OLLAMA_HOST", "")
            or "http://localhost:11434"
        ).rstrip("/")

    async def _post_with_retry(
        self, client: httpx.AsyncClient, payload: dict
    ) -> dict:
        """POST to Ollama /api/chat with retry on transient errors.

        Local models on consumer hardware can drop connections, time out,
        or return 500s during long inferences.  We retry aggressively
        because the cost is zero and the alternative is a failed pipeline.
        """
        last_exc: Exception | None = None
        for attempt in range(_MAX_RETRIES):
            try:
                resp = await client.post(
                    f"{self._host}/api/chat",
                    json=payload,
                )
                resp.raise_for_status()
                return resp.json()
            except _TRANSIENT_EXCEPTIONS as exc:
                last_exc = exc
                # For HTTPStatusError, only retry on 5xx
                if (
                    isinstance(exc, httpx.HTTPStatusError)
                    and exc.response.status_code < 500
                ):
                    raise
                wait = _RETRY_BACKOFF_BASE * (2 ** attempt)
                exc_type = type(exc).__name__
                exc_msg = str(exc) or "(no details)"
                logger.warning(
                    "Ollama transient error (attempt %d/%d): %s: %s — retrying in %.0fs",
                    attempt + 1, _MAX_RETRIES, exc_type, exc_msg, wait,
                )
                print(
                    f"Ollama transient error (attempt {attempt + 1}/{_MAX_RETRIES}): "
                    f"{exc_type}: {exc_msg} — retrying in {wait:.0f}s"
                )
                await asyncio.sleep(wait)
                continue
        raise last_exc  # type: ignore[misc]

    async def complete(
        self,
        system: str,
        messages: list[dict],
        max_tokens: int = 8192,
    ) -> str:
        msgs = [{"role": "system", "content": system}] + messages
        payload = {
            "model": self._model,
            "messages": msgs,
            "stream": False,
            "options": {"num_predict": max_tokens},
        }
        async with httpx.AsyncClient(timeout=1800.0) as client:
            data = await self._post_with_retry(client, payload)
        msg = data["message"]
        text = msg.get("content", "")
        # Thinking models (Qwen3, DeepSeek-R1) may put reasoning in a
        # "thinking" field and leave "content" empty if num_predict is
        # exhausted by the thinking tokens.  Fall back to thinking text.
        if not text.strip() and msg.get("thinking"):
            text = msg["thinking"]
        usage = {"input_tokens": 0, "output_tokens": 0}
        return text, usage

    @staticmethod
    def _convert_messages(messages: list[dict]) -> list[dict]:
        """Convert Anthropic-format messages to Ollama-format.

        Anthropic uses:
          assistant: {"content": [{"type": "tool_use", "id": ..., "name": ..., "input": ...}]}
          user:      {"content": [{"type": "tool_result", "tool_use_id": ..., "content": ...}]}

        Ollama expects:
          assistant: {"content": "", "tool_calls": [{"function": {"name": ..., "arguments": ...}}]}
          tool:      {"role": "tool", "content": "..."}
        """
        converted = []
        for msg in messages:
            content = msg.get("content")
            role = msg.get("role", "")

            # Plain string content — pass through
            if isinstance(content, str):
                converted.append(msg)
                continue

            # List content — check for tool_use / tool_result blocks
            if isinstance(content, list):
                # Assistant message with tool_use blocks
                if role == "assistant":
                    text_parts = []
                    tool_calls = []
                    for block in content:
                        if block.get("type") == "tool_use":
                            tool_calls.append({
                                "function": {
                                    "name": block["name"],
                                    "arguments": block.get("input", {}),
                                },
                            })
                        elif block.get("type") == "text":
                            text_parts.append(block.get("text", ""))
                    out = {"role": "assistant", "content": "\n".join(text_parts)}
                    if tool_calls:
                        out["tool_calls"] = tool_calls
                    converted.append(out)
                    continue

                # User message with tool_result blocks
                if role == "user":
                    for block in content:
                        if block.get("type") == "tool_result":
                            converted.append({
                                "role": "tool",
                                "content": block.get("content", ""),
                            })
                    continue

            # Fallback — pass through
            converted.append(msg)
        return converted

    async def complete_with_tools(
        self,
        system: str,
        messages: list[dict],
        tools: list[dict],
        max_tokens: int = 8192,
    ) -> dict:
        converted = self._convert_messages(messages)
        msgs = [{"role": "system", "content": system}] + converted
        # Ollama supports tool calling for compatible models
        ollama_tools = []
        for tool in tools:
            ollama_tools.append({
                "type": "function",
                "function": {
                    "name": tool["name"],
                    "description": tool.get("description", ""),
                    "parameters": tool.get("input_schema", {}),
                },
            })

        payload = {
            "model": self._model,
            "messages": msgs,
            "stream": False,
            "tools": ollama_tools,
            "options": {"num_predict": max_tokens},
        }
        async with httpx.AsyncClient(timeout=1800.0) as client:
            data = await self._post_with_retry(client, payload)

        msg = data["message"]
        content = []

        text = msg.get("content", "")
        # Thinking models: fall back to thinking text if content is empty
        if not text.strip() and msg.get("thinking"):
            text = msg["thinking"]
        if text:
            content.append({"type": "text", "text": text})

        for tc in msg.get("tool_calls", []):
            import uuid
            content.append({
                "type": "tool_use",
                "id": f"toolu_{uuid.uuid4().hex[:24]}",
                "name": tc["function"]["name"],
                "input": tc["function"]["arguments"],
            })

        stop_reason = "tool_use" if msg.get("tool_calls") else "end_turn"
        return {
            "role": "assistant",
            "content": content,
            "stop_reason": stop_reason,
            "usage": {"input_tokens": 0, "output_tokens": 0},
        }

    def name(self) -> str:
        return "ollama"

    def model_id(self) -> str:
        return self._model


