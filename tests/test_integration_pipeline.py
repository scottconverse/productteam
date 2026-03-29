"""Integration test: full pipeline with a scripted mock provider.

This is the "drive it off the line" test. Marked @pytest.mark.final
so it runs LAST, after every unit test has passed. Exercises the real
Supervisor, real tool_loop, real file I/O, and real state management.
The only fake is the LLM (ScriptedProvider from conftest).

If this test fails, the pipeline is broken regardless of what unit
tests say.

Fixtures used (auto-injected from conftest.py):
  - integration_project: tmp_path with all skill files set up
  - scripted_provider:   deterministic LLM that always completes
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from productteam.models import ProductTeamConfig
from productteam.supervisor import Supervisor, _load_state


# ---------------------------------------------------------------------------
# Config helper (local to this file — keeps conftest lean)
# ---------------------------------------------------------------------------

def _config(**pipeline_overrides) -> ProductTeamConfig:
    """Config tuned for fast integration tests — all gates off, short timeouts."""
    pipeline = {
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
    }
    pipeline.update(pipeline_overrides)
    return ProductTeamConfig.model_validate({
        "project": {"name": "integration-test", "version": "1.0.0"},
        "pipeline": pipeline,
        "gates": {"prd_approval": False, "sprint_approval": False, "ship_approval": False},
        "forge": {},
    })


_PRD_MD = """\
# PRD: Hello World CLI

## Overview
A minimal CLI that prints hello.

## Requirements
- R1: Print "hello" to stdout.
"""


# ---------------------------------------------------------------------------
# The final smoke test — runs last
# ---------------------------------------------------------------------------

@pytest.mark.final
@pytest.mark.asyncio
async def test_full_pipeline_smoke(integration_project, scripted_provider):
    """Full pipeline: concept in, 'shipping' out. The one test that matters."""
    sup = Supervisor(
        project_dir=integration_project,
        config=_config(),
        provider=scripted_provider,
        auto_approve=True,
    )

    result = await sup.run(concept="A CLI that prints hello")

    # Pipeline must complete
    assert result.status == "complete", (
        f"Pipeline did not complete: '{result.status}'. "
        f"Stages: {[(s.stage.value, s.status, s.error) for s in result.stages]}"
    )

    # State must reflect shipping
    state = _load_state(integration_project)
    assert state["pipeline_phase"] == "shipping"
    assert state["stages"]["prd"]["status"] == "complete"
    assert state["stages"]["plan"]["status"] == "complete"
    assert state["stages"]["build:sprint-001"]["status"] == "passed"

    # Real files must exist on disk
    assert (integration_project / ".productteam" / "prds" / "prd-v1.md").exists()
    assert (integration_project / ".productteam" / "sprints" / "sprint-001.yaml").exists()
    assert (integration_project / "src" / "main.py").exists()
    assert (integration_project / "README.md").exists()


# ---------------------------------------------------------------------------
# Supporting integration tests — also run last
# ---------------------------------------------------------------------------

@pytest.mark.final
@pytest.mark.asyncio
async def test_pipeline_with_design_review(integration_project, scripted_provider):
    """Pipeline completes with the design review gate enabled."""
    sup = Supervisor(
        project_dir=integration_project,
        config=_config(require_design_review=True),
        provider=scripted_provider,
        auto_approve=True,
    )

    result = await sup.run(concept="A CLI that prints hello")

    assert result.status == "complete", (
        f"Design review path failed: '{result.status}'. "
        f"Stages: {[(s.stage.value, s.status, s.error) for s in result.stages]}"
    )


@pytest.mark.final
@pytest.mark.asyncio
async def test_pipeline_resume(integration_project, scripted_provider):
    """Pipeline resumes from saved state, skipping completed stages."""
    # Pre-populate PRD as already complete
    prd_path = integration_project / ".productteam" / "prds" / "prd-v1.md"
    prd_path.write_text(_PRD_MD)
    state = {
        "schema_version": 1,
        "concept": "A CLI that prints hello",
        "pipeline_phase": "prd",
        "stages": {
            "prd": {"status": "complete", "artifact": ".productteam/prds/prd-v1.md"},
        },
    }
    (integration_project / ".productteam" / "state.json").write_text(json.dumps(state))

    sup = Supervisor(
        project_dir=integration_project,
        config=_config(),
        provider=scripted_provider,
        auto_approve=True,
    )

    result = await sup.run()  # No concept — resuming from saved state

    assert result.status == "complete", (
        f"Resume failed: '{result.status}'. "
        f"Stages: {[(s.stage.value, s.status, s.error) for s in result.stages]}"
    )
    # PRD should be skipped since it was already done
    stage_names = [s.stage.value for s in result.stages]
    assert "prd" not in stage_names, "PRD should have been skipped on resume"


@pytest.mark.final
@pytest.mark.asyncio
async def test_pipeline_token_accounting(integration_project, scripted_provider):
    """Every stage reports token usage — cost tracker isn't silently broken."""
    sup = Supervisor(
        project_dir=integration_project,
        config=_config(),
        provider=scripted_provider,
        auto_approve=True,
    )

    result = await sup.run(concept="A CLI that prints hello")

    total_input = sum(s.input_tokens for s in result.stages)
    total_output = sum(s.output_tokens for s in result.stages)
    assert total_input > 0, "No input tokens recorded across pipeline"
    assert total_output > 0, "No output tokens recorded across pipeline"
    for s in result.stages:
        assert s.input_tokens > 0, f"Stage {s.stage.value} reported 0 input tokens"
        assert s.output_tokens > 0, f"Stage {s.stage.value} reported 0 output tokens"


# ---------------------------------------------------------------------------
# Failure-path integration tests
# ---------------------------------------------------------------------------

@pytest.mark.final
@pytest.mark.asyncio
async def test_pipeline_needs_work_then_passes(integration_project, needs_work_provider):
    """Evaluator returns needs_work on loop 1, then pass on loop 2.

    The build-evaluate retry loop should re-run the builder with feedback
    and eventually complete.
    """
    sup = Supervisor(
        project_dir=integration_project,
        config=_config(max_loops=3),
        provider=needs_work_provider,
        auto_approve=True,
    )

    result = await sup.run(concept="A CLI that prints hello")

    assert result.status == "complete", (
        f"Pipeline should complete after needs_work then pass: '{result.status}'. "
        f"Stages: {[(s.stage.value, s.status, s.error) for s in result.stages]}"
    )


@pytest.mark.final
@pytest.mark.asyncio
async def test_pipeline_evaluator_fail(integration_project, fail_provider):
    """Evaluator always returns fail. Pipeline should return 'failed' not crash."""
    sup = Supervisor(
        project_dir=integration_project,
        config=_config(),
        provider=fail_provider,
        auto_approve=True,
    )

    result = await sup.run(concept="A CLI that prints hello")

    # The pipeline should not crash -- it should report a failure status
    assert result.status in ("failed", "stuck"), (
        f"Expected 'failed' or 'stuck' but got '{result.status}'. "
        f"Stages: {[(s.stage.value, s.status, s.error) for s in result.stages]}"
    )


@pytest.mark.final
@pytest.mark.asyncio
async def test_pipeline_handles_timeout(integration_project, timeout_provider):
    """Provider raises TimeoutError. Pipeline should return 'stuck' not crash."""
    sup = Supervisor(
        project_dir=integration_project,
        config=_config(),
        provider=timeout_provider,
        auto_approve=True,
    )

    result = await sup.run(concept="A CLI that prints hello")

    # The pipeline should not crash -- it should report stuck
    assert result.status in ("stuck", "failed"), (
        f"Expected 'stuck' or 'failed' but got '{result.status}'. "
        f"Stages: {[(s.stage.value, s.status, s.error) for s in result.stages]}"
    )
