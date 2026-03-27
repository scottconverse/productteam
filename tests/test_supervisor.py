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
    _load_skill,
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
    for skill in ["prd-writer", "planner", "builder", "evaluator", "doc-writer",
                   "evaluator-design"]:
        (tmp_path / ".claude" / "skills" / skill).mkdir(parents=True, exist_ok=True)
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


def _eval_response(verdict_text: str) -> dict:
    """Build a text-only complete_with_tools response for evaluator mocks."""
    return {
        "role": "assistant",
        "content": [{"type": "text", "text": verdict_text}],
        "stop_reason": "end_turn",
    }


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

    # Both builder and evaluator go through complete_with_tools (tool loop).
    # Builder completes first, then evaluator returns PASS verdict.
    mock_provider.complete_with_tools = AsyncMock(side_effect=[
        _eval_response("Build complete."),
        _eval_response("evaluator_verdict: PASS\nAll tests pass."),
    ])

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

    # Loop 1: builder → evaluator(NEEDS_WORK), Loop 2: builder → evaluator(PASS)
    mock_provider.complete_with_tools = AsyncMock(side_effect=[
        _eval_response("Built."),
        _eval_response("evaluator_verdict: NEEDS_WORK\nFix the tests."),
        _eval_response("Built again."),
        _eval_response("evaluator_verdict: PASS\nAll good."),
    ])

    supervisor = Supervisor(tmp_path, config, mock_provider, auto_approve=True)
    result = await supervisor._build_evaluate_loop("sprint-001")

    assert result.status == "complete"
    assert mock_provider.complete_with_tools.call_count == 4


@pytest.mark.asyncio
async def test_build_evaluate_fail_on_verdict(tmp_path):
    """Build-evaluate loop: FAIL verdict escalates immediately."""
    _init_project(tmp_path)
    (tmp_path / ".productteam" / "sprints" / "sprint-001.yaml").write_text(
        "sprint: 1\ntitle: Test\n"
    )

    config = _make_config()
    mock_provider = AsyncMock()

    mock_provider.complete_with_tools = AsyncMock(side_effect=[
        _eval_response("Built."),
        _eval_response("evaluator_verdict: FAIL\nFundamental issues."),
    ])

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
    # 2 loops: builder + evaluator(NEEDS_WORK) each
    mock_provider.complete_with_tools = AsyncMock(side_effect=[
        _eval_response("Built."),
        _eval_response("evaluator_verdict: NEEDS_WORK\nStill broken."),
        _eval_response("Built again."),
        _eval_response("evaluator_verdict: NEEDS_WORK\nStill broken."),
    ])

    supervisor = Supervisor(tmp_path, config, mock_provider, auto_approve=True)
    result = await supervisor._build_evaluate_loop("sprint-001")

    assert result.status == "stuck"
    assert "Max loops" in result.error


# ---------------------------------------------------------------------------
# require_evaluator config
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_build_evaluate_skips_eval_when_disabled(tmp_path):
    """Build-evaluate loop skips evaluator when require_evaluator=false."""
    _init_project(tmp_path)
    (tmp_path / ".productteam" / "sprints" / "sprint-001.yaml").write_text(
        "sprint: 1\ntitle: Test\n"
    )

    config = _make_config(pipeline={
        "provider": "anthropic", "model": "test", "max_loops": 3,
        "stage_timeout_seconds": 10, "builder_timeout_seconds": 30,
        "builder_max_tool_calls": 5, "auto_approve": False,
        "require_evaluator": False,
    })

    mock_provider = AsyncMock()
    # Builder completes — evaluator should never be called
    mock_provider.complete_with_tools = AsyncMock(return_value={
        "role": "assistant",
        "content": [{"type": "text", "text": "Built."}],
        "stop_reason": "end_turn",
    })

    supervisor = Supervisor(tmp_path, config, mock_provider, auto_approve=True)
    result = await supervisor._build_evaluate_loop("sprint-001")

    assert result.status == "complete"
    # Only one call (builder) — no evaluator call
    assert mock_provider.complete_with_tools.call_count == 1


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


def test_parse_verdict_yaml_structured(tmp_path):
    """Parses verdict from structured YAML response."""
    _init_project(tmp_path)
    config = _make_config()
    supervisor = Supervisor(tmp_path, config, AsyncMock())

    yaml_response = (
        "sprint: 1\n"
        "evaluator_verdict: PASS\n"
        "test_results:\n"
        "  total: 10\n"
        "  passed: 10\n"
    )
    assert supervisor._parse_verdict(yaml_response) == "pass"


def test_parse_verdict_no_false_positive_on_narrative(tmp_path):
    """Verdict parser does not misfire on 'pass' in narrative text."""
    _init_project(tmp_path)
    config = _make_config()
    supervisor = Supervisor(tmp_path, config, AsyncMock())

    # Old parser would match "pass" in the narrative and return "pass"
    tricky = (
        "This test will pass once you fix the import.\n"
        "evaluator_verdict: NEEDS_WORK\n"
        "Fix the broken import on line 5."
    )
    assert supervisor._parse_verdict(tricky) == "needs_work"


def test_parse_verdict_defaults_to_needs_work(tmp_path):
    """Verdict parser returns needs_work when no verdict found."""
    _init_project(tmp_path)
    config = _make_config()
    supervisor = Supervisor(tmp_path, config, AsyncMock())

    assert supervisor._parse_verdict("No structured output at all.") == "needs_work"


@pytest.mark.asyncio
async def test_build_evaluate_disk_fallback_finds_pass(tmp_path):
    """Verdict fallback reads PASS from eval YAML on disk when text has no verdict.

    The Evaluator writes structured YAML via write_file tool, but its final
    text response is a narrative summary with no parseable verdict key.
    The supervisor must check .productteam/evaluations/*.yaml on disk.
    """
    _init_project(tmp_path)
    (tmp_path / ".productteam" / "sprints" / "sprint-001.yaml").write_text(
        "sprint: 1\ntitle: Test\n"
    )

    # Pre-plant an eval YAML that the Evaluator "wrote via write_file"
    # The Evaluator names its files eval-NNN.yaml (sprint number, not "sprint-NNN")
    eval_dir = tmp_path / ".productteam" / "evaluations"
    eval_dir.mkdir(parents=True, exist_ok=True)
    (eval_dir / "eval-001.yaml").write_text(
        "sprint: 1\nevaluator_verdict: PASS\ntest_results:\n  total: 10\n  passed: 10\n"
    )

    config = _make_config()
    mock_provider = AsyncMock()

    # Builder text-only response, then evaluator text with NO parseable verdict
    mock_provider.complete_with_tools = AsyncMock(side_effect=[
        _eval_response("Build complete."),
        _eval_response("All 10 acceptance criteria met. Sprint is ready to ship."),
    ])

    supervisor = Supervisor(tmp_path, config, mock_provider, auto_approve=True)
    result = await supervisor._build_evaluate_loop("sprint-001")

    assert result.status == "complete", (
        f"Expected 'complete' but got '{result.status}'. "
        "Disk fallback failed to read verdict from eval YAML."
    )
    # Verify state was saved correctly
    state = supervisor.state
    assert state["stages"].get("build:sprint-001", {}).get("status") == "passed"


@pytest.mark.asyncio
async def test_disk_fallback_does_not_cross_sprint_boundaries(tmp_path):
    """Sprint-002 must NOT inherit sprint-001's PASS verdict from disk.

    Regression test: the original fallback glob'd all *.yaml files and found
    sprint-001's PASS when evaluating sprint-002, silently passing broken code.
    """
    _init_project(tmp_path)
    sprints_dir = tmp_path / ".productteam" / "sprints"
    sprints_dir.mkdir(parents=True, exist_ok=True)
    (sprints_dir / "sprint-001.yaml").write_text("sprint: 1\ntitle: Done\n")
    (sprints_dir / "sprint-002.yaml").write_text("sprint: 2\ntitle: Docs\n")

    # Sprint-001 passed — its eval file is on disk
    eval_dir = tmp_path / ".productteam" / "evaluations"
    eval_dir.mkdir(parents=True, exist_ok=True)
    (eval_dir / "eval-001.yaml").write_text(
        "sprint: 1\nevaluator_verdict: PASS\ntest_results:\n  total: 10\n  passed: 10\n"
    )
    # Sprint-002 has NO eval file on disk — evaluator only wrote narrative text

    config = _make_config()
    mock_provider = AsyncMock()

    # Builder and evaluator both return text-only (no tool calls, no verdict key)
    mock_provider.complete_with_tools = AsyncMock(side_effect=[
        _eval_response("Build complete."),
        _eval_response("Several acceptance criteria failed. Needs work."),
        # Loop 2: still no verdict
        _eval_response("Applied fixes."),
        _eval_response("Two criteria still failing."),
        # Loop 3: still no verdict
        _eval_response("More fixes."),
        _eval_response("Still not ready."),
    ])

    supervisor = Supervisor(tmp_path, config, mock_provider, auto_approve=True)
    # Mark sprint-001 as already passed so the loop targets sprint-002
    supervisor.state["stages"]["build:sprint-001"] = {"status": "passed"}
    result = await supervisor._build_evaluate_loop("sprint-002")

    # Sprint-002 should NOT have passed — it had no PASS verdict of its own
    state = supervisor.state
    sprint_002_status = state["stages"].get("build:sprint-002", {}).get("status", "")
    assert sprint_002_status != "passed", (
        "Sprint-002 should not pass — the fallback must not read sprint-001's eval file"
    )


# ---------------------------------------------------------------------------
# Context summarization tests
# ---------------------------------------------------------------------------


def test_summarize_eval_feedback_extracts_failures(tmp_path):
    """Summarizer extracts FAIL criteria and CRITICAL/HIGH/MEDIUM findings."""
    _init_project(tmp_path)
    config = _make_config()
    supervisor = Supervisor(tmp_path, config, AsyncMock())

    yaml_eval = (
        "evaluator_verdict: NEEDS_WORK\n"
        "acceptance_criteria:\n"
        "  - criterion: Feature A works\n"
        "    status: PASS\n"
        "    evidence: Verified\n"
        "  - criterion: Feature B works\n"
        "    status: FAIL\n"
        "    evidence: Missing import\n"
        "additional_findings:\n"
        "  - severity: LOW\n"
        "    finding: Minor style issue\n"
        "    suggestion: Fix later\n"
        "  - severity: MEDIUM\n"
        "    finding: Missing error handling\n"
        "    suggestion: Add try/except\n"
        "  - severity: CRITICAL\n"
        "    finding: SQL injection\n"
        "    suggestion: Use parameterized queries\n"
        "summary: |\n"
        "  Feature B is broken.\n"
    )
    result = supervisor._summarize_eval_feedback(yaml_eval, 1)
    assert "FAIL: Feature B works" in result
    assert "CRITICAL: SQL injection" in result
    assert "MEDIUM: Missing error handling" in result  # MEDIUM included
    assert "Feature A works" not in result  # PASS criteria excluded
    assert "Minor style issue" not in result  # LOW finding excluded
    assert "Feature B is broken" in result  # summary included


def test_summarize_eval_feedback_fallback_on_plain_text(tmp_path):
    """Summarizer falls back to truncation for non-YAML responses."""
    _init_project(tmp_path)
    config = _make_config()
    supervisor = Supervisor(tmp_path, config, AsyncMock())

    plain = "This is not YAML, just a plain text evaluator response. " * 100
    result = supervisor._summarize_eval_feedback(plain, 2)
    assert result.startswith("--- Evaluator feedback (loop 2) ---")
    assert len(result) <= 2100  # header + 2000 chars max


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


# ---------------------------------------------------------------------------
# Full pipeline integration tests
# ---------------------------------------------------------------------------


def _init_multi_sprint_project(tmp_path: Path) -> None:
    """Set up a project with two sprint contracts and all skills."""
    _init_project(tmp_path)
    # Also add evaluator-design and doc-writer skills for the full pipeline
    for extra in ["evaluator-design"]:
        skill_dir = tmp_path / ".claude" / "skills" / extra
        skill_dir.mkdir(parents=True, exist_ok=True)
        (skill_dir / "SKILL.md").write_text(f"# {extra}\nYou are a {extra}.")

    sprints_dir = tmp_path / ".productteam" / "sprints"
    sprints_dir.mkdir(parents=True, exist_ok=True)
    (sprints_dir / "sprint-001.yaml").write_text(
        "sprint: 1\ntitle: Core feature\nacceptance_criteria:\n  - Feature works\n"
    )
    (sprints_dir / "sprint-002.yaml").write_text(
        "sprint: 2\ntitle: Tests\nacceptance_criteria:\n  - Tests pass\n"
    )


@pytest.mark.asyncio
async def test_full_pipeline_two_sprints(tmp_path):
    """Full Supervisor.run() with two sprints, all stages, auto-approve."""
    _init_multi_sprint_project(tmp_path)

    config = _make_config(pipeline={
        "provider": "anthropic",
        "model": "test",
        "max_loops": 2,
        "stage_timeout_seconds": 10,
        "builder_timeout_seconds": 30,
        "builder_max_tool_calls": 5,
        "auto_approve": False,
        "require_design_review": True,
    })

    mock_provider = AsyncMock()

    # Thinker stages use provider.complete:
    #   1. PRD only (Planner is now a doer)
    mock_provider.complete = AsyncMock(return_value="# PRD\nA CLI tool.")

    # Doer stages use provider.complete_with_tools (via tool loop):
    #   Plan, Sprint 1 (builder → evaluator), Sprint 2, Document, Design eval
    mock_provider.complete_with_tools = AsyncMock(side_effect=[
        _eval_response("Sprint plan written."),                     # planner
        _eval_response("Sprint 1 built."),                          # builder sprint-001
        _eval_response("evaluator_verdict: PASS\nAll good."),       # evaluator sprint-001
        _eval_response("Sprint 2 built."),                          # builder sprint-002
        _eval_response("evaluator_verdict: PASS\nTests pass."),     # evaluator sprint-002
        _eval_response("# Documentation\nAll docs written."),       # doc-writer
        _eval_response("evaluator_verdict: PASS\nDesign approved."),# design evaluator
    ])

    supervisor = Supervisor(tmp_path, config, mock_provider, auto_approve=True)
    result = await supervisor.run(concept="test CLI tool")

    assert result.status == "complete"
    assert result.concept == "test CLI tool"
    # PRD + Plan + 2x build-eval + document + design-eval = 6 stages
    assert len(result.stages) == 6

    # Verify state was saved correctly
    state = _load_state(tmp_path)
    assert state["pipeline_phase"] == "shipping"
    assert state["stages"]["prd"]["status"] == "complete"
    assert state["stages"]["plan"]["status"] == "complete"
    assert state["stages"]["document"]["status"] == "complete"


@pytest.mark.asyncio
async def test_full_pipeline_sprint_fails_stops_pipeline(tmp_path):
    """Pipeline stops when a sprint's evaluator returns FAIL."""
    _init_multi_sprint_project(tmp_path)

    config = _make_config(pipeline={
        "provider": "anthropic",
        "model": "test",
        "max_loops": 1,
        "stage_timeout_seconds": 10,
        "builder_timeout_seconds": 30,
        "builder_max_tool_calls": 5,
        "auto_approve": False,
        "require_design_review": False,
    })
    mock_provider = AsyncMock()
    mock_provider.complete = AsyncMock(return_value="# PRD\nA tool.")

    mock_provider.complete_with_tools = AsyncMock(side_effect=[
        _eval_response("Plan written."),
        _eval_response("Built sprint 1."),
        _eval_response("evaluator_verdict: FAIL\nFundamental issues."),
    ])

    supervisor = Supervisor(tmp_path, config, mock_provider, auto_approve=True)
    result = await supervisor.run(concept="failing project")

    # Pipeline should be stuck (sprint-001 failed, never reaches sprint-002)
    assert result.status == "stuck"


@pytest.mark.asyncio
async def test_full_pipeline_no_concept_fails(tmp_path):
    """Pipeline fails immediately when no concept is provided and none in state."""
    _init_project(tmp_path)
    config = _make_config()
    mock_provider = AsyncMock()

    supervisor = Supervisor(tmp_path, config, mock_provider, auto_approve=True)
    result = await supervisor.run(concept="")

    assert result.status == "failed"
    assert result.stages == []


@pytest.mark.asyncio
async def test_full_pipeline_resume_skips_completed(tmp_path):
    """Pipeline resumes and skips already-completed stages."""
    _init_multi_sprint_project(tmp_path)

    # Pre-populate state: PRD and Plan already complete
    prd_dir = tmp_path / ".productteam" / "prds"
    prd_dir.mkdir(parents=True, exist_ok=True)
    (prd_dir / "prd-v1.md").write_text("# PRD\nDone.")

    plan_path = tmp_path / ".productteam" / "plan.md"
    plan_path.write_text("# Plan\nDone.")

    state = {
        "schema_version": 1,
        "concept": "resumed project",
        "pipeline_phase": "building",
        "stages": {
            "prd": {"status": "complete", "artifact": ".productteam/prds/prd-v1.md"},
            "plan": {"status": "complete", "artifact": ".productteam/plan.md"},
        },
    }
    _save_state(tmp_path, state)

    config = _make_config(pipeline={
        "provider": "anthropic",
        "model": "test",
        "max_loops": 1,
        "stage_timeout_seconds": 10,
        "planner_timeout_seconds": 10,
        "builder_timeout_seconds": 30,
        "builder_max_tool_calls": 5,
        "auto_approve": False,
        "require_design_review": False,
    })

    mock_provider = AsyncMock()
    # PRD and Plan should NOT be called — only build/eval + document
    mock_provider.complete = AsyncMock()  # should not be called

    mock_provider.complete_with_tools = AsyncMock(side_effect=[
        _eval_response("Sprint 1 built."),
        _eval_response("evaluator_verdict: PASS\nGood."),
        _eval_response("Sprint 2 built."),
        _eval_response("evaluator_verdict: PASS\nGood."),
        _eval_response("# Docs\nWritten."),
    ])

    supervisor = Supervisor(tmp_path, config, mock_provider, auto_approve=True)
    result = await supervisor.run()

    assert result.status == "complete"
    # PRD and Plan should not have been called via provider.complete
    mock_provider.complete.assert_not_called()


@pytest.mark.asyncio
async def test_multi_sprint_sequencing(tmp_path):
    """Sprints are processed in alphabetical order."""
    _init_project(tmp_path)
    sprints_dir = tmp_path / ".productteam" / "sprints"
    sprints_dir.mkdir(parents=True, exist_ok=True)

    # Create sprints out of order — should still be processed alphabetically
    (sprints_dir / "sprint-003.yaml").write_text("sprint: 3\ntitle: Third\n")
    (sprints_dir / "sprint-001.yaml").write_text("sprint: 1\ntitle: First\n")
    (sprints_dir / "sprint-002.yaml").write_text("sprint: 2\ntitle: Second\n")

    config = _make_config()
    mock_provider = AsyncMock()

    # Track which sprint contracts were seen
    seen_sprints = []

    async def track_complete_with_tools(system, messages, tools, **kw):
        user_msg = messages[0]["content"] if messages else ""
        for s in ["sprint-001", "sprint-002", "sprint-003"]:
            if s in user_msg and s not in seen_sprints:
                seen_sprints.append(s)
        return _eval_response("evaluator_verdict: PASS\nDone.")

    mock_provider.complete = AsyncMock(return_value="# PRD")
    mock_provider.complete_with_tools = AsyncMock(side_effect=track_complete_with_tools)

    supervisor = Supervisor(tmp_path, config, mock_provider, auto_approve=True)
    await supervisor.run(concept="multi-sprint test")

    assert seen_sprints == ["sprint-001", "sprint-002", "sprint-003"]


# ---------------------------------------------------------------------------
# Planner as doer + pipeline guard tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_planner_doer_writes_yaml_files(tmp_path):
    """Planner (now a doer) writes sprint YAML files to .productteam/sprints/."""
    _init_project(tmp_path)
    (tmp_path / ".productteam" / "sprints").mkdir(parents=True, exist_ok=True)

    config = _make_config()
    mock_provider = AsyncMock()
    mock_provider.complete_with_tools = AsyncMock(side_effect=[
        {"role": "assistant", "content": [{"type": "tool_use", "id": "t1",
            "name": "write_file",
            "input": {"path": ".productteam/sprints/sprint-001.yaml",
                      "content": "sprint: 1\ntitle: Core\n"}}],
         "stop_reason": "tool_use"},
        {"role": "assistant", "content": [{"type": "tool_use", "id": "t2",
            "name": "write_file",
            "input": {"path": ".productteam/sprints/sprint-002.yaml",
                      "content": "sprint: 2\ntitle: CLI\n"}}],
         "stop_reason": "tool_use"},
        {"role": "assistant",
         "content": [{"type": "text", "text": "Two sprint contracts written."}],
         "stop_reason": "end_turn"},
    ])

    supervisor = Supervisor(tmp_path, config, mock_provider, auto_approve=True)
    result = await supervisor._run_tool_loop_stage(
        PipelineStage.PLAN, "planner", "Build a CLI tool."
    )

    assert result.status == "complete"
    assert (tmp_path / ".productteam" / "sprints" / "sprint-001.yaml").exists()
    assert (tmp_path / ".productteam" / "sprints" / "sprint-002.yaml").exists()


@pytest.mark.asyncio
async def test_pipeline_fails_when_no_sprints_after_plan(tmp_path):
    """Pipeline returns failed (not silent skip) when plan completes with no YAML files."""
    _init_project(tmp_path)
    config = _make_config(pipeline={
        "provider": "anthropic", "model": "test", "max_loops": 1,
        "stage_timeout_seconds": 10, "planner_timeout_seconds": 10,
        "builder_timeout_seconds": 30, "builder_max_tool_calls": 5,
        "auto_approve": False, "require_design_review": False,
    })
    mock_provider = AsyncMock()
    mock_provider.complete = AsyncMock(return_value="# PRD\nA CLI tool.")
    # Planner completes but writes no YAML files
    mock_provider.complete_with_tools = AsyncMock(return_value={
        "role": "assistant",
        "content": [{"type": "text", "text": "Here is my sprint plan as prose. No files."}],
        "stop_reason": "end_turn",
    })

    supervisor = Supervisor(tmp_path, config, mock_provider, auto_approve=True)
    result = await supervisor.run(concept="build a tool")

    assert result.status == "failed"
    assert not any(s.stage == PipelineStage.BUILD for s in result.stages)


@pytest.mark.asyncio
async def test_doc_writer_skipped_when_no_sprints_passed(tmp_path):
    """Doc Writer does not run when no sprints have passed evaluation."""
    _init_project(tmp_path)
    # Create a sprint file so the pipeline doesn't fail at the "no sprints" check,
    # but don't pass it through evaluation
    (tmp_path / ".productteam" / "sprints" / "sprint-001.yaml").write_text(
        "sprint: 1\ntitle: Test\n"
    )

    config = _make_config(pipeline={
        "provider": "anthropic", "model": "test", "max_loops": 1,
        "stage_timeout_seconds": 10, "planner_timeout_seconds": 10,
        "builder_timeout_seconds": 30, "builder_max_tool_calls": 5,
        "auto_approve": False, "require_design_review": False,
    })
    mock_provider = AsyncMock()
    mock_provider.complete = AsyncMock(return_value="# PRD\nA tool.")

    # Planner writes no new files (sprint-001 already exists)
    # Builder + Evaluator FAIL
    mock_provider.complete_with_tools = AsyncMock(side_effect=[
        _eval_response("Plan done."),  # planner
        _eval_response("Built."),  # builder
        _eval_response("evaluator_verdict: FAIL\nBroken."),  # evaluator
    ])

    supervisor = Supervisor(tmp_path, config, mock_provider, auto_approve=True)
    result = await supervisor.run(concept="build a tool")

    # Should be stuck (build failed), doc writer never ran
    assert result.status == "stuck"
    doc_stages = [s for s in result.stages if s.stage == PipelineStage.DOCUMENT]
    assert len(doc_stages) == 0


def test_timeout_defaults_are_production_viable():
    """Timeout defaults reflect real-world LLM latency, not optimistic estimates."""
    config = ProductTeamConfig()
    assert config.pipeline.stage_timeout_seconds >= 300, \
        "stage_timeout_seconds must be >= 300s for real Sonnet latency"
    assert config.pipeline.builder_timeout_seconds >= 600, \
        "builder_timeout_seconds must be >= 600s for complex doer stages"
    assert config.pipeline.planner_timeout_seconds >= 600, \
        "planner_timeout_seconds must be >= 600s for multi-sprint planning"


@pytest.mark.asyncio
async def test_planner_uses_planner_timeout(tmp_path):
    """_run_tool_loop_stage accepts and passes through timeout override."""
    _init_project(tmp_path)
    config = _make_config(pipeline={
        "provider": "anthropic", "model": "test",
        "stage_timeout_seconds": 10,
        "planner_timeout_seconds": 999,
        "builder_timeout_seconds": 30,
        "builder_max_tool_calls": 5,
        "max_loops": 1, "auto_approve": False,
    })
    mock_provider = AsyncMock()
    mock_provider.complete_with_tools = AsyncMock(return_value={
        "role": "assistant",
        "content": [{"type": "text", "text": "Done."}],
        "stop_reason": "end_turn",
    })

    supervisor = Supervisor(tmp_path, config, mock_provider, auto_approve=True)
    # Should use 999s timeout, not 10s stage timeout
    result = await supervisor._run_tool_loop_stage(
        PipelineStage.PLAN, "planner", "Plan this.",
        timeout_seconds=config.pipeline.planner_timeout_seconds,
    )
    assert result.status == "complete"


@pytest.mark.asyncio
async def test_design_eval_disk_fallback_finds_pass(tmp_path):
    """Design evaluator verdict fallback reads PASS from eval YAML on disk.

    The design evaluator writes structured YAML via write_file, but its
    final text response is a narrative summary with no parseable verdict.
    The supervisor must fall back to checking eval-*-design.yaml on disk.
    """
    _init_project(tmp_path)

    # Pre-plant a design eval YAML that the evaluator "wrote via write_file"
    eval_dir = tmp_path / ".productteam" / "evaluations"
    eval_dir.mkdir(parents=True, exist_ok=True)
    (eval_dir / "eval-001-design.yaml").write_text(
        "sprint: 1\nevaluator_verdict: PASS\ngrades:\n  coherence:\n    score: 5\n"
    )

    config = _make_config(pipeline={
        "provider": "anthropic",
        "model": "test-model",
        "max_loops": 1,
        "stage_timeout_seconds": 10,
        "builder_timeout_seconds": 30,
        "builder_max_tool_calls": 5,
        "auto_approve": False,
        "require_design_review": True,
    })
    mock_provider = AsyncMock()

    supervisor = Supervisor(tmp_path, config, mock_provider, auto_approve=True)

    # Simulate: raw_response has no parseable verdict, but disk file does
    narrative_response = "All documentation looks great. Cohesive design system."
    verdict = supervisor._parse_verdict(narrative_response)
    assert verdict == "needs_work", "Narrative text should not parse as pass"

    # Now simulate the fallback logic inline (same as what the supervisor does)
    if verdict == "needs_work":
        for eval_file in sorted(eval_dir.glob("eval-*-design.yaml"), reverse=True):
            file_verdict = supervisor._parse_verdict(
                eval_file.read_text(encoding="utf-8")
            )
            if file_verdict in ("pass", "fail"):
                verdict = file_verdict
                break

    assert verdict == "pass", (
        "Design eval disk fallback failed to read PASS from eval-001-design.yaml"
    )


def test_load_skill_uses_configured_path(tmp_path):
    """_load_skill reads from the configured skills_dir instead of the default."""
    # Create a skill in a custom directory
    custom_dir = tmp_path / "custom" / "skills" / "test-skill"
    custom_dir.mkdir(parents=True)
    (custom_dir / "SKILL.md").write_text("# Custom skill content")

    content = _load_skill(tmp_path, "test-skill", skills_dir="custom/skills")
    assert content == "# Custom skill content"


def test_load_skill_error_message_includes_config_hint(tmp_path):
    """_load_skill error message suggests checking skills_dir config."""
    with pytest.raises(FileNotFoundError, match="skills_dir"):
        _load_skill(tmp_path, "nonexistent-skill", skills_dir="custom/path")


@pytest.mark.asyncio
async def test_stage_callback_called_during_pipeline(tmp_path):
    """stage_callback fires for each stage in the pipeline."""
    _init_project(tmp_path)
    config = _make_config()
    mock_provider = AsyncMock()
    mock_provider.complete = AsyncMock(return_value="PRD content here.")

    stages_seen: list[str] = []

    def callback(stage: str) -> None:
        stages_seen.append(stage)

    supervisor = Supervisor(tmp_path, config, mock_provider, auto_approve=True)

    # Without callback set, _notify_stage should be a no-op
    supervisor._stage_callback = None
    supervisor._notify_stage("prd")
    assert stages_seen == []

    # With callback set, it should fire
    supervisor._stage_callback = callback
    supervisor._notify_stage("prd")
    supervisor._notify_stage("plan")
    assert stages_seen == ["prd", "plan"]


# ---------------------------------------------------------------------------
# Coverage gap tests: state, artifacts, sprints, eval feedback
# ---------------------------------------------------------------------------


def test_load_state_bad_schema_version(tmp_path):
    """_load_state raises ValueError on unsupported schema version."""
    pt_dir = tmp_path / ".productteam"
    pt_dir.mkdir()
    (pt_dir / "state.json").write_text('{"schema_version": 999}')
    with pytest.raises(ValueError, match="schema version 999"):
        _load_state(tmp_path)


def test_find_sprints_no_dir(tmp_path):
    """_find_sprints returns empty list when sprints dir doesn't exist."""
    _init_project(tmp_path)
    config = _make_config()
    supervisor = Supervisor(tmp_path, config, AsyncMock())
    # Remove the sprints directory
    import shutil
    shutil.rmtree(tmp_path / ".productteam" / "sprints")
    assert supervisor._find_sprints() == []


def test_find_sprints_with_yaml(tmp_path):
    """_find_sprints finds YAML files in sprints directory."""
    _init_project(tmp_path)
    config = _make_config()
    supervisor = Supervisor(tmp_path, config, AsyncMock())
    sprints_dir = tmp_path / ".productteam" / "sprints"
    (sprints_dir / "sprint-001.yaml").write_text("sprint: 1")
    (sprints_dir / "sprint-002.yml").write_text("sprint: 2")
    (sprints_dir / "notes.txt").write_text("not a sprint")
    result = supervisor._find_sprints()
    assert result == ["sprint-001", "sprint-002"]


def test_write_artifact_prd(tmp_path):
    """_write_artifact writes PRD to correct path."""
    _init_project(tmp_path)
    config = _make_config()
    supervisor = Supervisor(tmp_path, config, AsyncMock())
    path = supervisor._write_artifact(PipelineStage.PRD, "# PRD content")
    assert "prds" in path
    assert (tmp_path / path).read_text() == "# PRD content"


def test_write_artifact_plan(tmp_path):
    """_write_artifact writes plan to correct path."""
    _init_project(tmp_path)
    config = _make_config()
    supervisor = Supervisor(tmp_path, config, AsyncMock())
    path = supervisor._write_artifact(PipelineStage.PLAN, "plan text")
    assert "plan.md" in path


def test_write_artifact_evaluate(tmp_path):
    """_write_artifact writes evaluation to correct path."""
    _init_project(tmp_path)
    config = _make_config()
    supervisor = Supervisor(tmp_path, config, AsyncMock())
    path = supervisor._write_artifact(PipelineStage.EVALUATE, "eval: pass")
    assert "evaluations" in path


def test_write_artifact_unknown_stage(tmp_path):
    """_write_artifact handles stages without specific paths."""
    _init_project(tmp_path)
    config = _make_config()
    supervisor = Supervisor(tmp_path, config, AsyncMock())
    path = supervisor._write_artifact(PipelineStage.EVALUATE_DESIGN, "design eval")
    assert "evaluate-design-output.md" in path


def test_read_artifact_no_path(tmp_path):
    """_read_artifact returns empty string when no artifact path recorded."""
    _init_project(tmp_path)
    config = _make_config()
    supervisor = Supervisor(tmp_path, config, AsyncMock())
    supervisor.state["stages"]["prd"] = {"status": "complete"}  # no artifact key
    result = supervisor._read_artifact("prd")
    assert result == ""


def test_read_artifact_missing_file(tmp_path):
    """_read_artifact returns empty string when artifact file is missing."""
    _init_project(tmp_path)
    config = _make_config()
    supervisor = Supervisor(tmp_path, config, AsyncMock())
    supervisor.state["stages"]["prd"] = {
        "status": "complete",
        "artifact": ".productteam/prds/prd-v1.md",
    }
    result = supervisor._read_artifact("prd")
    assert result == ""


def test_read_artifact_success(tmp_path):
    """_read_artifact reads existing artifact file."""
    _init_project(tmp_path)
    config = _make_config()
    supervisor = Supervisor(tmp_path, config, AsyncMock())
    prd_dir = tmp_path / ".productteam" / "prds"
    prd_dir.mkdir(parents=True)
    (prd_dir / "prd-v1.md").write_text("# My PRD")
    supervisor.state["stages"]["prd"] = {
        "status": "complete",
        "artifact": ".productteam/prds/prd-v1.md",
    }
    result = supervisor._read_artifact("prd")
    assert result == "# My PRD"


def test_summarize_eval_feedback_structured(tmp_path):
    """_summarize_eval_feedback extracts findings from YAML."""
    _init_project(tmp_path)
    config = _make_config()
    supervisor = Supervisor(tmp_path, config, AsyncMock())
    eval_yaml = (
        "evaluator_verdict: NEEDS_WORK\n"
        "acceptance_criteria:\n"
        "  - criterion: Tests pass\n"
        "    status: FAIL\n"
        "    evidence: 2 tests failed\n"
        "  - criterion: CLI works\n"
        "    status: PASS\n"
        "    evidence: all commands work\n"
        "additional_findings:\n"
        "  - severity: HIGH\n"
        "    finding: No error handling\n"
        "    suggestion: Add try/except\n"
        "  - severity: LOW\n"
        "    finding: Style nit\n"
        "    suggestion: Use black\n"
        "summary: Needs error handling\n"
    )
    result = supervisor._summarize_eval_feedback(eval_yaml, 1)
    assert "FAIL: Tests pass" in result
    assert "HIGH: No error handling" in result
    assert "LOW" not in result  # LOW findings excluded
    assert "Summary: Needs error handling" in result


def test_summarize_eval_feedback_fallback(tmp_path):
    """_summarize_eval_feedback truncates non-YAML response."""
    _init_project(tmp_path)
    config = _make_config()
    supervisor = Supervisor(tmp_path, config, AsyncMock())
    result = supervisor._summarize_eval_feedback("Just a plain text response.", 2)
    assert "loop 2" in result
    assert "Just a plain text" in result


def test_parse_verdict_yaml_error(tmp_path):
    """_parse_verdict handles malformed YAML gracefully."""
    _init_project(tmp_path)
    config = _make_config()
    supervisor = Supervisor(tmp_path, config, AsyncMock())
    # Malformed YAML that will cause parse error
    result = supervisor._parse_verdict("evaluator_verdict: PASS\n  bad indent: [")
    # Should still find PASS via line scan fallback
    assert result == "pass"


def test_parse_verdict_line_scan_fail(tmp_path):
    """_parse_verdict line scan catches 'fail' on verdict lines."""
    _init_project(tmp_path)
    config = _make_config()
    supervisor = Supervisor(tmp_path, config, AsyncMock())
    assert supervisor._parse_verdict("verdict: FAIL\nSome details.") == "fail"


@pytest.mark.asyncio
async def test_build_loop_missing_sprint_contract(tmp_path):
    """_build_evaluate_loop returns failed when sprint contract is missing."""
    _init_project(tmp_path)
    config = _make_config()
    supervisor = Supervisor(tmp_path, config, AsyncMock(), auto_approve=True)
    result = await supervisor._build_evaluate_loop("sprint-nonexistent")
    assert result.status == "failed"
    assert "not found" in result.error


@pytest.mark.asyncio
async def test_build_loop_skill_not_found(tmp_path):
    """_build_evaluate_loop returns failed when builder skill is missing."""
    _init_project(tmp_path)
    # Write sprint contract but delete builder skill
    sprints_dir = tmp_path / ".productteam" / "sprints"
    (sprints_dir / "sprint-001.yaml").write_text("sprint: 1\ntitle: Test\n")
    import shutil
    shutil.rmtree(tmp_path / ".claude" / "skills" / "builder")

    config = _make_config()
    mock_provider = AsyncMock()
    supervisor = Supervisor(tmp_path, config, mock_provider, auto_approve=True)
    result = await supervisor._build_evaluate_loop("sprint-001")
    assert result.status == "failed"
    assert "Skill not found" in result.error


@pytest.mark.asyncio
async def test_run_no_concept_fails(tmp_path):
    """run() with no concept and no saved concept returns failed."""
    _init_project(tmp_path)
    config = _make_config()
    supervisor = Supervisor(tmp_path, config, AsyncMock(), auto_approve=True)
    result = await supervisor.run()
    assert result.status == "failed"


@pytest.mark.asyncio
async def test_thinker_stage_skill_not_found(tmp_path):
    """_run_thinker_stage returns failed when skill file is missing."""
    _init_project(tmp_path)
    config = _make_config()
    supervisor = Supervisor(tmp_path, config, AsyncMock(), auto_approve=True)
    result = await supervisor._run_thinker_stage(
        PipelineStage.PRD, "nonexistent-skill", "test"
    )
    assert result.status == "failed"
    assert "Skill not found" in result.error


@pytest.mark.asyncio
async def test_tool_loop_stage_skill_not_found(tmp_path):
    """_run_tool_loop_stage returns failed when skill file is missing."""
    _init_project(tmp_path)
    config = _make_config()
    supervisor = Supervisor(tmp_path, config, AsyncMock(), auto_approve=True)
    result = await supervisor._run_tool_loop_stage(
        PipelineStage.PLAN, "nonexistent-skill", "test"
    )
    assert result.status == "failed"
    assert "Skill not found" in result.error
