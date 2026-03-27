"""Anthropic provider using the official SDK."""

from __future__ import annotations

import os

import anthropic

from productteam.errors import ProductTeamConfigError
from productteam.providers.base import LLMProvider


class AnthropicProvider(LLMProvider):
    """Anthropic Claude API provider."""

    def __init__(self, model: str = "claude-sonnet-4-6", api_key: str | None = None):
        self._model = model
        self._api_key = api_key or os.environ.get("ANTHROPIC_API_KEY", "")
        if not self._api_key:
            raise ProductTeamConfigError(
                "Anthropic API key not found. "
                "Set the ANTHROPIC_API_KEY environment variable."
            )
        self._client = anthropic.AsyncAnthropic(api_key=self._api_key)

    async def complete(
        self,
        system: str,
        messages: list[dict],
        max_tokens: int = 8192,
    ) -> tuple[str, dict]:
        response = await self._client.messages.create(
            model=self._model,
            max_tokens=max_tokens,
            system=system,
            messages=messages,
        )
        parts = [block.text for block in response.content if hasattr(block, "text")]
        usage = {
            "input_tokens": response.usage.input_tokens,
            "output_tokens": response.usage.output_tokens,
        }
        return "\n".join(parts), usage

    async def complete_with_tools(
        self,
        system: str,
        messages: list[dict],
        tools: list[dict],
        max_tokens: int = 8192,
    ) -> dict:
        response = await self._client.messages.create(
            model=self._model,
            max_tokens=max_tokens,
            system=system,
            messages=messages,
            tools=tools,
        )
        # Convert to our standard format
        content = []
        for block in response.content:
            if block.type == "text":
                content.append({"type": "text", "text": block.text})
            elif block.type == "tool_use":
                content.append({
                    "type": "tool_use",
                    "id": block.id,
                    "name": block.name,
                    "input": block.input,
                })
        return {
            "role": "assistant",
            "content": content,
            "stop_reason": response.stop_reason,
            "usage": {
                "input_tokens": response.usage.input_tokens,
                "output_tokens": response.usage.output_tokens,
            },
        }

    def name(self) -> str:
        return "anthropic"

    def model_id(self) -> str:
        return self._model


