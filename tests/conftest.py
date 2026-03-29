"""Shared fixtures for ProductTeam tests."""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from typing import Any

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


# ---------------------------------------------------------------------------
# Scripted provider — deterministic LLM for integration tests
# ---------------------------------------------------------------------------

_USAGE = {
    "input_tokens": 100,
    "output_tokens": 50,
    "cache_creation_input_tokens": 0,
    "cache_read_input_tokens": 0,
}

_SPRINT_YAML = """\
name: sprint-001
description: "Core hello-world CLI"
deliverables:
  - src/main.py with entry point
acceptance_criteria:
  - "Running python src/main.py prints hello"
"""

_PRD_MD = """\
# PRD: Hello World CLI

## Overview
A minimal CLI that prints hello.

## Requirements
- R1: Print "hello" to stdout.
"""

_HELLO_PY = 'print("hello")\n'


class ScriptedProvider:
    """Fake LLM that returns pre-scripted responses per stage.

    Detects which stage is calling by inspecting the system prompt
    (which contains the SKILL.md content with the skill name).
    For tool-loop stages, it uses a call counter to script the
    sequence: tool calls first, then a text-only finish response.

    Implements the LLMProvider interface without inheriting from it
    so the import stays lightweight for non-integration tests.
    """

    def __init__(self) -> None:
        self._call_count: dict[str, int] = {}

    def name(self) -> str:
        return "scripted"

    def model_id(self) -> str:
        return "scripted-test-v1"

    async def complete(
        self,
        system: str,
        messages: list[dict],
        max_tokens: int = 8192,
    ) -> tuple[str, dict]:
        if "prd-writer" in system.lower():
            return _PRD_MD, _USAGE
        return "Stage complete.", _USAGE

    async def complete_with_tools(
        self,
        system: str,
        messages: list[dict],
        tools: list[dict],
        max_tokens: int = 8192,
    ) -> dict:
        stage = self._detect_stage(system)
        n = self._call_count.get(stage, 0)
        self._call_count[stage] = n + 1

        if stage == "planner":
            return self._planner(n)
        elif stage == "builder":
            return self._builder(n)
        elif stage == "evaluator":
            return self._evaluator(n)
        elif stage == "doc-writer":
            return self._doc_writer(n)
        elif stage == "evaluator-design":
            return self._design_eval(n)
        return self._text("Done.")

    def _planner(self, n: int) -> dict:
        if n == 0:
            return self._tool("write_file", {
                "path": ".productteam/sprints/sprint-001.yaml",
                "content": _SPRINT_YAML,
            })
        return self._text("Planned 1 sprint.")

    def _builder(self, n: int) -> dict:
        if n == 0:
            return self._tool("write_file", {
                "path": "src/main.py", "content": _HELLO_PY,
            })
        return self._text("Built src/main.py. Ready for review.")

    def _evaluator(self, n: int) -> dict:
        if n == 0:
            return self._tool("read_file", {"path": "src/main.py"})
        return self._text(
            "evaluator_verdict: pass\n\n"
            "All acceptance criteria met."
        )

    def _doc_writer(self, n: int) -> dict:
        if n == 0:
            return self._tool("write_file", {
                "path": "README.md",
                "content": "# Hello World CLI\n\nRun `python src/main.py`.\n",
            })
        return self._text("Documentation complete.")

    def _design_eval(self, n: int) -> dict:
        return self._text("verdict: pass\n\nDesign looks good.")

    @staticmethod
    def _detect_stage(system: str) -> str:
        s = system.lower()
        for name in ("evaluator-design", "evaluator", "builder",
                      "planner", "doc-writer"):
            if name in s:
                return name
        return "unknown"

    @staticmethod
    def _text(text: str) -> dict:
        return {
            "role": "assistant",
            "content": [{"type": "text", "text": text}],
            "stop_reason": "end_turn",
            "usage": _USAGE,
        }

    @staticmethod
    def _tool(tool_name: str, tool_input: dict) -> dict:
        return {
            "role": "assistant",
            "content": [
                {"type": "text", "text": f"Calling {tool_name}..."},
                {
                    "type": "tool_use",
                    "id": f"tooluse_{tool_name}",
                    "name": tool_name,
                    "input": tool_input,
                },
            ],
            "stop_reason": "tool_use",
            "usage": _USAGE,
        }


@pytest.fixture
def scripted_provider() -> ScriptedProvider:
    """Deterministic mock LLM provider for integration tests."""
    return ScriptedProvider()


# ---------------------------------------------------------------------------
# Failure-path ScriptedProvider variants
# ---------------------------------------------------------------------------

class ScriptedProviderNeedsWork(ScriptedProvider):
    """Evaluator returns 'needs_work' on loop 1, then 'pass' on loop 2.

    Tests that the build-evaluate retry loop actually works.
    """

    def __init__(self) -> None:
        super().__init__()
        self._eval_calls = 0

    def _evaluator(self, n: int) -> dict:
        if n == 0:
            return self._tool("read_file", {"path": "src/main.py"})
        # Track how many times we've produced a final verdict
        self._eval_calls += 1
        if self._eval_calls <= 1:
            return self._text(
                "evaluator_verdict: needs_work\n\n"
                "Missing error handling. Add try/except."
            )
        return self._text(
            "evaluator_verdict: pass\n\n"
            "All acceptance criteria met."
        )


class ScriptedProviderFail(ScriptedProvider):
    """Evaluator always returns 'fail'.

    Tests that the pipeline handles hard failures correctly.
    """

    def _evaluator(self, n: int) -> dict:
        if n == 0:
            return self._tool("read_file", {"path": "src/main.py"})
        return self._text(
            "evaluator_verdict: fail\n\n"
            "Fundamental design flaw. Cannot proceed."
        )


class ScriptedProviderTimeout(ScriptedProvider):
    """complete_with_tools raises asyncio.TimeoutError after first call.

    Tests that timeout handling works.
    """

    def __init__(self) -> None:
        super().__init__()
        self._total_calls = 0

    async def complete_with_tools(
        self,
        system: str,
        messages: list[dict],
        tools: list[dict],
        max_tokens: int = 8192,
    ) -> dict:
        import asyncio

        self._total_calls += 1
        if self._total_calls > 1:
            raise asyncio.TimeoutError("Simulated timeout")
        return await super().complete_with_tools(system, messages, tools, max_tokens)


@pytest.fixture
def needs_work_provider() -> ScriptedProviderNeedsWork:
    """Provider where evaluator needs_work on loop 1, pass on loop 2."""
    return ScriptedProviderNeedsWork()


@pytest.fixture
def fail_provider() -> ScriptedProviderFail:
    """Provider where evaluator always returns fail."""
    return ScriptedProviderFail()


@pytest.fixture
def timeout_provider() -> ScriptedProviderTimeout:
    """Provider that raises TimeoutError after first call."""
    return ScriptedProviderTimeout()


@pytest.fixture
def integration_project(tmp_path) -> Path:
    """Minimal project directory with all skill files for integration tests."""
    (tmp_path / ".productteam" / "sprints").mkdir(parents=True)
    (tmp_path / ".productteam" / "evaluations").mkdir(parents=True)
    (tmp_path / ".productteam" / "prds").mkdir(parents=True)
    (tmp_path / ".productteam" / "docs").mkdir(parents=True)
    for skill in ("prd-writer", "planner", "builder", "evaluator",
                   "doc-writer", "evaluator-design"):
        d = tmp_path / ".claude" / "skills" / skill
        d.mkdir(parents=True, exist_ok=True)
        (d / "SKILL.md").write_text(f"# {skill}\nYou are a {skill}.")
    return tmp_path


def _make_integration_config(**overrides) -> "ProductTeamConfig":
    """Config tuned for fast integration tests — all gates off, short timeouts."""
    from productteam.models import ProductTeamConfig

    data: dict[str, Any] = {
        "project": {"name": "integration-test", "version": "1.0.0"},
        "pipeline": {
            "provider": "anthropic",
            "model": "scripted-test-v1",
            "max_loops": 3,
            "max_sprints": 2,
            "stage_timeout_seconds": 30,
            "builder_timeout_seconds": 30,
            "planner_timeout_seconds": 30,
            "builder_max_tool_calls": 10,
            "evaluator_max_tool_calls": 10,
            "doc_writer_max_tool_calls": 10,
            "auto_approve": True,
            "require_design_review": False,
            "require_evaluator": True,
            "budget_usd": 100.0,
            "auto_install_deps": False,
        },
        "gates": {
            "prd_approval": False,
            "sprint_approval": False,
            "ship_approval": False,
        },
        "forge": {},
    }
    if overrides:
        for k, v in overrides.items():
            if isinstance(v, dict) and k in data:
                data[k].update(v)
            else:
                data[k] = v
    return ProductTeamConfig.model_validate(data)


# ---------------------------------------------------------------------------
# Run @pytest.mark.final tests last — the "drive it off the line" smoke test
# ---------------------------------------------------------------------------

def pytest_collection_modifyitems(config, items):
    """Reorder tests so @pytest.mark.final items run after everything else."""
    final_tests = []
    other_tests = []
    for item in items:
        if item.get_closest_marker("final"):
            final_tests.append(item)
        else:
            other_tests.append(item)
    items[:] = other_tests + final_tests
