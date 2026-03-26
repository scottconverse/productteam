"""Factory function for creating LLM provider instances."""

from __future__ import annotations

from productteam.errors import ProductTeamConfigError
from productteam.providers.base import LLMProvider


def get_provider(
    provider: str = "anthropic",
    model: str = "",
    api_base: str = "",
) -> LLMProvider:
    """Create an LLM provider instance from config values.

    Args:
        provider: Provider name ('anthropic', 'openai', 'ollama', 'gemini').
        model: Model identifier. Uses provider default if empty.
        api_base: Optional API base URL (for openai-compatible servers).

    Returns:
        An initialized LLMProvider instance.

    Raises:
        ProductTeamConfigError: If the provider is unknown or misconfigured.
    """
    provider = provider.lower().strip()

    if provider == "anthropic":
        from productteam.providers.anthropic import AnthropicProvider
        return AnthropicProvider(model=model or "claude-sonnet-4-6")

    elif provider == "openai":
        from productteam.providers.openai import OpenAIProvider
        return OpenAIProvider(model=model or "gpt-4o", api_base=api_base)

    elif provider == "ollama":
        from productteam.providers.ollama import OllamaProvider
        return OllamaProvider(model=model or "llama3", host=api_base)

    elif provider == "gemini":
        from productteam.providers.gemini import GeminiProvider
        return GeminiProvider(model=model or "gemini-2.0-flash")

    else:
        raise ProductTeamConfigError(
            f"Unknown provider: {provider!r}. "
            f"Supported providers: anthropic, openai, ollama, gemini"
        )
