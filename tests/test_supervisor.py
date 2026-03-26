"""Tests for the Supervisor pipeline orchestrator."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from productteam.models import ProductTeamConfig
from productteam.supervisor import (
    PipelineStage,
    StageResult,
    Supervisor,
    _load_state,
    _save_state,
)


def _make_config(**overrides) -> ProductTeamConfig:
    """Create a config with optional overrides."""
    data = {
        "project": {"name": "test", "version": "1.0.0"},
        "pipeline": {
            "provider": "anthropic",
            "model": "test-model",
            "max_loops": 3,
            "stage_timeout_seconds": 10,
            "builder_timeout_seconds": 30,
            "builder_max_tool_calls": 5,
            "auto_approve": False,
        },
        "gates": {"prd_approval": True, "sprint_approval": True, "ship_approval": True},
        "forge": {},
    }
    data.update(overrides)
    return ProductTeamConfig.model_validate(data)


def _init_project(tmp_path: Path) -> None:
    """Set up minimal project structure."""
    (tmp_path / ".productteam" / "sprints").mkdir(parents=True)
    (tmp_path / ".productteam" / "evaluations").mkdir(parents=True)
    (tmp_path / ".claude" / "skills" / "prd-writer").mkdir(parents=True)
    (tmp_path / ".claude" / "skills" / "planner").mkdir(parents=True)
    (tmp_path / ".claude" / "skills" / "builder").mkdir(parents=True)
    (tmp_path / ".claude" / "skills" / "evaluator").mkdir(parents=True)
    (tmp_path / ".claude" / "skills" / "doc-writer").mkdir(parents=True)
    for skill in ["prd-writer", "planner", "builder", "evaluator", "doc-writer"]:
        (tmp_path / ".claude" / "skills" / skill / "SKILL.md").write_text(
            f"# {skill}\nYou are a {skill}."
        )


# ---------------------------------------------------------------------------
# State management tests
# ---------------------------------------------------------------------------


def test_load_state_default(tmp_path):
    """_load_state returns default when no state.json exists."""
    state = _load_state(tmp_path)
    assert state["schema_version"] == 1
    assert state["pipeline_phase"] == "planning"


def test_save_load_state_roundtrip(tmp_path):
    """_save_state and _load_state roundtrip."""
    (tmp_path / ".productteam").mkdir()
    state = {"schema_version": 1, "concept": "test app", "stages": {}}
    _save_state(tmp_path, state)
    loaded = _load_state(tmp_path)
    assert loaded["concept"] == "test app"
    assert loaded["updated_at"]  # timestamp was added


def test_save_state_creates_directory(tmp_path):
    """_save_state creates .productteam/ if needed."""
    state = {"schema_version": 1}
    _save_state(tmp_path, state)
    assert (tmp_path / ".productteam" / "state.json").exists()


# ---------------------------------------------------------------------------
# Supervisor dry run
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_supervisor_dry_run(tmp_path):
    """Dry run shows stages without calling LLM."""
    _init_project(tmp_path)
    config = _make_config()
    mock_provider = AsyncMock()

    supervisor = Supervisor(tmp_path, config, mock_provider, auto_approve=True)
    result = await supervisor.run(concept="test app", dry_run=True)

    assert result.status == "complete"
    mock_provider.complete.assert_not_called()


# ---------------------------------------------------------------------------
# Supervisor thinker stage
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_supervisor_prd_stage(tmp_path):
    """Supervisor runs PRD thinker stage and writes artifact."""
    _init_project(tmp_path)
    config = _make_config()

    mock_provider = AsyncMock()
    mock_provider.complete = AsyncMock(return_value="# PRD\n\nThis is the PRD.")
    mock_provider.complete_with_tools = AsyncMock()

    supervisor = Supervisor(tmp_path, config, mock_provider, auto_approve=True)
    result = await supervisor._run_thinker_stage(
        PipelineStage.PRD, "prd-writer", "build a test app"
    )

    assert result.status == "complete"
    assert result.artifact_path
    mock_provider.complete.assert_called_once()


@pytest.mark.asyncio
async def test_supervisor_thinker_timeout(tmp_path):
    """Supervisor marks stage stuck on timeout."""
    _init_project(tmp_path)
    config = _make_config(pipeline={
        "provider": "anthropic", "model": "test", "max_loops": 3,
        "stage_timeout_seconds": 0,  # instant timeout
        "builder_timeout_seconds": 30, "builder_max_tool_calls": 5,
        "auto_approve": False,
    })

    import asyncio

    async def slow_complete(*args, **kwargs):
        await asyncio.sleep(10)
        return "too slow"

    mock_provider = AsyncMock()
    mock_provider.complete = slow_complete

    supervisor = Supervisor(tmp_path, config, mock_provider, auto_approve=True)
    result = await supervisor._run_thinker_stage(
        PipelineStage.PRD, "prd-writer", "concept"
    )

    assert result.status == "stuck"


# ---------------------------------------------------------------------------
# Build-evaluate loop tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_build_evaluate_pass_loop1(tmp_path):
    """Build-evaluate loop passes on first iteration."""
    _init_project(tmp_path)

    # Write a sprint contract
    (tmp_path / ".productteam" / "sprints" / "sprint-001.yaml").write_text(
        "sprint: 1\ntitle: Test Sprint\n"
    )

    config = _make_config()
    mock_provider = AsyncMock()

    # Builder returns text-only (complete immediately)
    mock_provider.complete_with_tools = AsyncMock(return_value={
        "role": "assistant",
        "content": [{"type": "text", "text": "Build complete."}],
        "stop_reason": "end_turn",
    })

    # Evaluator returns PASS
    mock_provider.complete = AsyncMock(return_value="evaluator_verdict: PASS\nAll tests pass.")

    supervisor = Supervisor(tmp_path, config, mock_provider, auto_approve=True)
    result = await supervisor._build_evaluate_loop("sprint-001")

    assert result.status == "complete"


@pytest.mark.asyncio
async def test_build_evaluate_needs_work_then_pass(tmp_path):
    """Build-evaluate loop: NEEDS_WORK on loop 1, PASS on loop 2."""
    _init_project(tmp_path)
    (tmp_path / ".productteam" / "sprints" / "sprint-001.yaml").write_text(
        "sprint: 1\ntitle: Test\n"
    )

    config = _make_config()
    mock_provider = AsyncMock()

    # Builder always completes immediately
    mock_provider.complete_with_tools = AsyncMock(return_value={
        "role": "assistant",
        "content": [{"type": "text", "text": "Built."}],
        "stop_reason": "end_turn",
    })

    # Evaluator: NEEDS_WORK first, then PASS
    mock_provider.complete = AsyncMock(side_effect=[
        "evaluator_verdict: NEEDS_WORK\nFix the tests.",
        "evaluator_verdict: PASS\nAll good.",
    ])

    supervisor = Supervisor(tmp_path, config, mock_provider, auto_approve=True)
    result = await supervisor._build_evaluate_loop("sprint-001")

    assert result.status == "complete"
    assert mock_provider.complete.call_count == 2


@pytest.mark.asyncio
async def test_build_evaluate_fail_on_verdict(tmp_path):
    """Build-evaluate loop: FAIL verdict escalates immediately."""
    _init_project(tmp_path)
    (tmp_path / ".productteam" / "sprints" / "sprint-001.yaml").write_text(
        "sprint: 1\ntitle: Test\n"
    )

    config = _make_config()
    mock_provider = AsyncMock()

    mock_provider.complete_with_tools = AsyncMock(return_value={
        "role": "assistant",
        "content": [{"type": "text", "text": "Built."}],
        "stop_reason": "end_turn",
    })
    mock_provider.complete = AsyncMock(return_value="evaluator_verdict: FAIL\nFundamental issues.")

    supervisor = Supervisor(tmp_path, config, mock_provider, auto_approve=True)
    result = await supervisor._build_evaluate_loop("sprint-001")

    assert result.status == "failed"


@pytest.mark.asyncio
async def test_build_evaluate_max_loops_exhausted(tmp_path):
    """Build-evaluate loop exhausts max loops and reports stuck."""
    _init_project(tmp_path)
    (tmp_path / ".productteam" / "sprints" / "sprint-001.yaml").write_text(
        "sprint: 1\ntitle: Test\n"
    )

    config = _make_config(pipeline={
        "provider": "anthropic", "model": "test", "max_loops": 2,
        "stage_timeout_seconds": 10, "builder_timeout_seconds": 30,
        "builder_max_tool_calls": 5, "auto_approve": False,
    })

    mock_provider = AsyncMock()
    mock_provider.complete_with_tools = AsyncMock(return_value={
        "role": "assistant",
        "content": [{"type": "text", "text": "Built."}],
        "stop_reason": "end_turn",
    })
    mock_provider.complete = AsyncMock(return_value="evaluator_verdict: NEEDS_WORK\nStill broken.")

    supervisor = Supervisor(tmp_path, config, mock_provider, auto_approve=True)
    result = await supervisor._build_evaluate_loop("sprint-001")

    assert result.status == "stuck"
    assert "Max loops" in result.error


# ---------------------------------------------------------------------------
# Gate approval tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_gate_auto_approve(tmp_path):
    """Gate returns True immediately with auto_approve."""
    _init_project(tmp_path)
    config = _make_config()
    mock_provider = AsyncMock()

    supervisor = Supervisor(tmp_path, config, mock_provider, auto_approve=True)
    approved = await supervisor._gate("Test Gate", "")

    assert approved is True


# ---------------------------------------------------------------------------
# Verdict parsing tests
# ---------------------------------------------------------------------------


def test_parse_verdict_pass(tmp_path):
    """Parses PASS verdict correctly."""
    _init_project(tmp_path)
    config = _make_config()
    mock_provider = AsyncMock()
    supervisor = Supervisor(tmp_path, config, mock_provider)

    assert supervisor._parse_verdict("evaluator_verdict: PASS") == "pass"
    assert supervisor._parse_verdict("verdict: PASS\nAll good.") == "pass"


def test_parse_verdict_needs_work(tmp_path):
    """Parses NEEDS_WORK verdict correctly."""
    _init_project(tmp_path)
    config = _make_config()
    mock_provider = AsyncMock()
    supervisor = Supervisor(tmp_path, config, mock_provider)

    assert supervisor._parse_verdict("evaluator_verdict: NEEDS_WORK") == "needs_work"


def test_parse_verdict_fail(tmp_path):
    """Parses FAIL verdict correctly."""
    _init_project(tmp_path)
    config = _make_config()
    mock_provider = AsyncMock()
    supervisor = Supervisor(tmp_path, config, mock_provider)

    assert supervisor._parse_verdict("evaluator_verdict: FAIL") == "fail"


# ---------------------------------------------------------------------------
# Resume behavior
# ---------------------------------------------------------------------------


def test_resume_skips_completed_stages(tmp_path):
    """State with completed stage is recognized."""
    _init_project(tmp_path)
    state = {
        "schema_version": 1,
        "concept": "test",
        "stages": {"prd": {"status": "complete", "artifact": "prds/prd-v1.md"}},
    }
    _save_state(tmp_path, state)
    loaded = _load_state(tmp_path)
    assert loaded["stages"]["prd"]["status"] == "complete"
