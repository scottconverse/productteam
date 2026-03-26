"""Multi-provider LLM abstraction layer for ProductTeam."""

from productteam.providers.base import LLMProvider
from productteam.providers.factory import get_provider

__all__ = ["LLMProvider", "get_provider"]
