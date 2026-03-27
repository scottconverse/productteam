"""Live integration tests — make real API calls.

Run with: productteam test --live
Or: pytest -m live tests/test_live.py

These tests use the cheapest model available (Haiku by default) and
small prompts to minimize cost. Each test should complete in under 30s.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from productteam.models import ProductTeamConfig
from productteam.providers.base import LLMProvider

pytestmark = pytest.mark.live


# ---------------------------------------------------------------------------
# Provider smoke tests — verify the API key works
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_live_provider_complete(live_provider: LLMProvider):
    """Provider can make a basic completion call."""
    text, usage = await live_provider.complete(
        system="You are a helpful assistant. Reply in one sentence.",
        messages=[{"role": "user", "content": "Say hello."}],
        max_tokens=64,
    )
    assert isinstance(text, str)
    assert len(text) > 0
    assert isinstance(usage, dict)
    assert "input_tokens" in usage


@pytest.mark.asyncio
async def test_live_provider_complete_with_tools(live_provider: LLMProvider):
    """Provider can make a tool-use completion call."""
    tools = [
        {
            "name": "read_file",
            "description": "Read a file.",
            "input_schema": {
                "type": "object",
                "properties": {
                    "path": {"type": "string", "description": "File path"},
                },
                "required": ["path"],
            },
        },
    ]
    result = await live_provider.complete_with_tools(
        system="You are a builder. Use the read_file tool to read README.md.",
        messages=[{"role": "user", "content": "Read README.md"}],
        tools=tools,
        max_tokens=256,
    )
    assert result["role"] == "assistant"
    assert isinstance(result["content"], list)
    assert len(result["content"]) > 0


# ---------------------------------------------------------------------------
# Thinker stage — single LLM call produces structured output
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_live_thinker_stage(live_provider: LLMProvider, live_project: Path):
    """Thinker stage produces a real artifact from a concept."""
    from productteam.supervisor import PipelineStage, Supervisor

    config = ProductTeamConfig.model_validate({
        "pipeline": {
            "provider": live_provider.name(),
            "model": live_provider.model_id(),
            "stage_timeout_seconds": 60,
            "builder_timeout_seconds": 60,
            "builder_max_tool_calls": 5,
        },
    })

    supervisor = Supervisor(live_project, config, live_provider, auto_approve=True)
    result = await supervisor._run_thinker_stage(
        PipelineStage.PRD,
        "prd-writer",
        "A CLI tool that converts Markdown to HTML",
    )

    assert result.status == "complete"
    assert result.artifact_path
    artifact = (live_project / result.artifact_path).read_text()
    assert len(artifact) > 50  # non-trivial output


# ---------------------------------------------------------------------------
# Tool loop — agent uses tools to read/write files
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_live_tool_loop_reads_file(live_provider: LLMProvider, live_project: Path):
    """Tool loop agent can read a file from the project."""
    from productteam.tool_loop import run_tool_loop

    # Create a file for the agent to read
    (live_project / "hello.txt").write_text("Hello from the test harness!")

    result = await run_tool_loop(
        provider=live_provider,
        system_prompt=(
            "You are a test agent. Read hello.txt using the read_file tool, "
            "then respond with the file's content."
        ),
        initial_user_message="Read hello.txt and tell me what it says.",
        project_dir=live_project,
        max_tool_calls=5,
        timeout_seconds=60,
    )

    assert result.status == "complete"
    assert result.tool_call_count >= 1
    assert "Hello from the test harness" in result.final_text


@pytest.mark.asyncio
async def test_live_tool_loop_writes_file(live_provider: LLMProvider, live_project: Path):
    """Tool loop agent can write a file to the project."""
    from productteam.tool_loop import run_tool_loop

    result = await run_tool_loop(
        provider=live_provider,
        system_prompt=(
            "You are a test agent. Use write_file to create a file called "
            "output.txt with the content 'test passed'. Then confirm you wrote it."
        ),
        initial_user_message="Write 'test passed' to output.txt.",
        project_dir=live_project,
        max_tool_calls=5,
        timeout_seconds=60,
    )

    assert result.status == "complete"
    assert result.tool_call_count >= 1
    output = live_project / "output.txt"
    assert output.exists()
    assert "test passed" in output.read_text()


# ---------------------------------------------------------------------------
# Build-evaluate loop — builder + evaluator round-trip
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_live_build_evaluate_loop(live_provider: LLMProvider, live_project: Path):
    """Full build-evaluate loop with a trivial sprint contract."""
    from productteam.supervisor import Supervisor

    # Write a minimal sprint contract
    sprint_dir = live_project / ".productteam" / "sprints"
    sprint_dir.mkdir(parents=True, exist_ok=True)
    (sprint_dir / "sprint-001.yaml").write_text(
        "sprint: 1\n"
        "title: Hello World\n"
        "acceptance_criteria:\n"
        "  - Create a file called hello.py that prints 'Hello, World!'\n"
    )

    config = ProductTeamConfig.model_validate({
        "pipeline": {
            "provider": live_provider.name(),
            "model": live_provider.model_id(),
            "max_loops": 2,
            "stage_timeout_seconds": 90,
            "builder_timeout_seconds": 90,
            "builder_max_tool_calls": 15,
        },
    })

    supervisor = Supervisor(live_project, config, live_provider, auto_approve=True)
    result = await supervisor._build_evaluate_loop("sprint-001")

    # Either passes or needs_work is acceptable — we're testing the round-trip
    assert result.status in ("complete", "stuck", "failed")
    # Builder should have created at least the build artifact
    assert (live_project / ".productteam" / "sprints" / "sprint-001" / "build-artifact.md").exists()
