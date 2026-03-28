"""OpenAI-compatible provider (covers OpenAI, Azure, local servers like LM Studio)."""

from __future__ import annotations

import os

import httpx

from productteam.errors import ProductTeamConfigError
from productteam.providers.base import LLMProvider


class OpenAIProvider(LLMProvider):
    """OpenAI-compatible API provider."""

    def __init__(
        self,
        model: str = "gpt-4o",
        api_key: str | None = None,
        api_base: str = "",
    ):
        self._model = model
        self._api_key = api_key or os.environ.get("OPENAI_API_KEY", "")
        self._api_base = api_base
        if not self._api_key and not self._api_base:
            raise ProductTeamConfigError(
                "OpenAI API key not found. "
                "Set the OPENAI_API_KEY environment variable, "
                "or set api_base in productteam.toml for a local server."
            )
        base = self._api_base.rstrip("/") if self._api_base else "https://api.openai.com/v1"
        self._base_url = base

    async def complete(
        self,
        system: str,
        messages: list[dict],
        max_tokens: int = 8192,
    ) -> tuple[str, dict]:
        msgs = [{"role": "system", "content": system}] + messages
        payload = {
            "model": self._model,
            "messages": msgs,
            "max_tokens": max_tokens,
        }
        headers = {"Content-Type": "application/json"}
        if self._api_key:
            headers["Authorization"] = f"Bearer {self._api_key}"

        async with httpx.AsyncClient(timeout=120.0) as client:
            resp = await client.post(
                f"{self._base_url}/chat/completions",
                json=payload,
                headers=headers,
            )
            resp.raise_for_status()
            data = resp.json()
        usage_data = data.get("usage", {})
        usage = {
            "input_tokens": usage_data.get("prompt_tokens", 0),
            "output_tokens": usage_data.get("completion_tokens", 0),
        }
        return data["choices"][0]["message"]["content"], usage

    async def complete_with_tools(
        self,
        system: str,
        messages: list[dict],
        tools: list[dict],
        max_tokens: int = 8192,
    ) -> dict:
        msgs = [{"role": "system", "content": system}] + messages
        # Convert our tool format to OpenAI format
        openai_tools = []
        for tool in tools:
            openai_tools.append({
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
            "max_tokens": max_tokens,
            "tools": openai_tools,
        }
        headers = {"Content-Type": "application/json"}
        if self._api_key:
            headers["Authorization"] = f"Bearer {self._api_key}"

        async with httpx.AsyncClient(timeout=120.0) as client:
            resp = await client.post(
                f"{self._base_url}/chat/completions",
                json=payload,
                headers=headers,
            )
            resp.raise_for_status()
            data = resp.json()

        choice = data["choices"][0]
        msg = choice["message"]
        content = []

        if msg.get("content"):
            content.append({"type": "text", "text": msg["content"]})

        for tc in msg.get("tool_calls", []):
            import json
            args = tc["function"].get("arguments", {})
            if isinstance(args, str):
                try:
                    parsed_args = json.loads(args)
                except (json.JSONDecodeError, ValueError):
                    parsed_args = {"_raw_arguments": args}
            elif isinstance(args, dict):
                parsed_args = args
            else:
                parsed_args = {}
            content.append({
                "type": "tool_use",
                "id": tc["id"],
                "name": tc["function"]["name"],
                "input": parsed_args,
            })

        stop_reason = "tool_use" if msg.get("tool_calls") else "end_turn"
        usage_data = data.get("usage", {})
        return {
            "role": "assistant",
            "content": content,
            "stop_reason": stop_reason,
            "usage": {
                "input_tokens": usage_data.get("prompt_tokens", 0),
                "output_tokens": usage_data.get("completion_tokens", 0),
            },
        }

    def name(self) -> str:
        return "openai"

    def model_id(self) -> str:
        return self._model


