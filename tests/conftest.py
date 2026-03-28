"""Shared fixtures for ProductTeam tests."""

from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest


# ---------------------------------------------------------------------------
# Dependency check — fail fast with a helpful message instead of cryptic
# ImportErrors scattered across 300+ tests.
# ---------------------------------------------------------------------------
_REQUIRED = ["tomli_w", "pydantic", "rich", "yaml", "httpx", "anthropic", "typer"]
_missing = []
for _mod in _REQUIRED:
    try:
        __import__(_mod)
    except ImportError:
        _missing.append(_mod)
if _missing:
    sys.exit(
        f"Missing dependencies: {', '.join(_missing)}\n"
        f"Install with:  pip install -e \".[dev]\"\n"
        f"  or:          pip install -r requirements-dev.txt"
    )


def _get_live_provider():
    """Resolve provider for live tests from env or default."""
    return os.environ.get("PRODUCTTEAM_TEST_PROVIDER", "anthropic")


def _get_live_model():
    """Resolve model for live tests from env or provider default."""
    model = os.environ.get("PRODUCTTEAM_TEST_MODEL", "")
    if model:
        return model
    defaults = {
        "anthropic": "claude-haiku-4-5-20251001",
        "openai": "gpt-4o-mini",
        "ollama": "llama3",
        "gemini": "gemini-2.0-flash",
    }
    return defaults.get(_get_live_provider(), "claude-haiku-4-5-20251001")


@pytest.fixture
def live_provider():
    """Create a real LLM provider for live tests.

    Uses the cheapest available model by default to minimize cost.
    Override with PRODUCTTEAM_TEST_PROVIDER and PRODUCTTEAM_TEST_MODEL.
    """
    from productteam.providers.factory import get_provider

    provider_name = _get_live_provider()
    model = _get_live_model()
    return get_provider(provider=provider_name, model=model)


@pytest.fixture
def live_project(tmp_path):
    """Create a minimal project directory for live tests."""
    from productteam.scaffold import init_project

    init_project(tmp_path)
    return tmp_path
