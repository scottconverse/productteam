"""Self-test: run the full pipeline with a ScriptedProvider.

Used by ``productteam doctor --deep`` to verify the pipeline works
end-to-end without any API key or network access. Completes in
under a second.
"""

from __future__ import annotations

import tempfile
from pathlib import Path
from typing import Any


# ---------------------------------------------------------------------------
# Usage stub (mirrors test conftest)
# ---------------------------------------------------------------------------

_USAGE: dict[str, int] = {
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


# ---------------------------------------------------------------------------
# ScriptedProvider (production copy -- must not import from tests/)
# ---------------------------------------------------------------------------

class ScriptedProvider:
    """Deterministic fake LLM for self-test. No network, no API key."""

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


# ---------------------------------------------------------------------------
# Self-test runner
# ---------------------------------------------------------------------------

async def run_self_test() -> bool:
    """Run the full pipeline with ScriptedProvider in a temp directory.

    Returns True if the pipeline completes, False otherwise.
    No API key needed -- takes under a second.
    """
    from productteam.models import ProductTeamConfig
    from productteam.supervisor import Supervisor

    tmp = tempfile.mkdtemp(prefix="productteam-selftest-")
    project_dir = Path(tmp)

    try:
        # Set up project structure
        (project_dir / ".productteam" / "sprints").mkdir(parents=True)
        (project_dir / ".productteam" / "evaluations").mkdir(parents=True)
        (project_dir / ".productteam" / "prds").mkdir(parents=True)
        (project_dir / ".productteam" / "docs").mkdir(parents=True)

        for skill in ("prd-writer", "planner", "builder", "evaluator",
                       "doc-writer", "evaluator-design"):
            d = project_dir / ".claude" / "skills" / skill
            d.mkdir(parents=True, exist_ok=True)
            (d / "SKILL.md").write_text(f"# {skill}\nYou are a {skill}.")

        # Config with all gates off, short timeouts
        config = ProductTeamConfig.model_validate({
            "project": {"name": "self-test", "version": "1.0.0"},
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
        })

        provider = ScriptedProvider()
        sup = Supervisor(
            project_dir=project_dir,
            config=config,
            provider=provider,
            auto_approve=True,
        )

        result = await sup.run(concept="A CLI that prints hello")
        return result.status == "complete"

    except Exception:
        return False

    finally:
        import shutil
        shutil.rmtree(tmp, ignore_errors=True)
