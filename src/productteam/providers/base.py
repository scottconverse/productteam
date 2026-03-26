"""Abstract base class for LLM providers."""

from __future__ import annotations

from abc import ABC, abstractmethod


class LLMProvider(ABC):
    """Base class all LLM providers must implement."""

    @abstractmethod
    async def complete(
        self,
        system: str,
        messages: list[dict],
        max_tokens: int = 8192,
    ) -> str:
        """Return the assistant's text response."""
        ...

    @abstractmethod
    async def complete_with_tools(
        self,
        system: str,
        messages: list[dict],
        tools: list[dict],
        max_tokens: int = 8192,
    ) -> dict:
        """Return the full response including any tool_use blocks.

        Returns a dict with:
          - "role": "assistant"
          - "content": list of content blocks (text and/or tool_use)
          - "stop_reason": str
        """
        ...

    @abstractmethod
    def name(self) -> str:
        """Return the provider name (e.g. 'anthropic', 'openai')."""
        ...

    @abstractmethod
    def model_id(self) -> str:
        """Return the model identifier being used."""
        ...
