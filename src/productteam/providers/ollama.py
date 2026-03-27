"""Ollama native API provider."""

from __future__ import annotations

import os

import httpx

from productteam.errors import ProductTeamConfigError
from productteam.providers.base import LLMProvider


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
        async with httpx.AsyncClient(timeout=300.0) as client:
            resp = await client.post(
                f"{self._host}/api/chat",
                json=payload,
            )
            resp.raise_for_status()
            data = resp.json()
        return data["message"]["content"]

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
        async with httpx.AsyncClient(timeout=300.0) as client:
            resp = await client.post(
                f"{self._host}/api/chat",
                json=payload,
            )
            resp.raise_for_status()
            data = resp.json()

        msg = data["message"]
        content = []

        if msg.get("content"):
            content.append({"type": "text", "text": msg["content"]})

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
        }

    def name(self) -> str:
        return "ollama"

    def model_id(self) -> str:
        return self._model


