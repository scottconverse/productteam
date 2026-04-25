"""Tests for productteam.preflight - model capability checker.

Mocks OllamaProvider so no live Ollama is needed. Covers PreflightResult
construction, the three-stage check_model flow (basic / tool_calling /
multi_turn), error/timeout branches, format_result rendering, and
check_all_models aggregation.
"""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, patch

import pytest

from productteam.preflight import (
    PreflightResult,
    check_all_models,
    check_model,
    format_result,
)


# ---------------------------------------------------------------------------
# PreflightResult dataclass
# ---------------------------------------------------------------------------


def test_preflight_result_defaults():
    r = PreflightResult(model="qwen3:8b")
    assert r.model == "qwen3:8b"
    assert r.basic_response is False
    assert r.tool_calling is False
    assert r.multi_turn is False
    assert r.basic_response_time == 0.0
    assert r.basic_response_error == ""
    assert r.pipeline_ready is False


def test_pipeline_ready_all_true():
    r = PreflightResult(
        model="m",
        basic_response=True,
        tool_calling=True,
        multi_turn=True,
    )
    assert r.pipeline_ready is True


def test_pipeline_ready_partial_false():
    r = PreflightResult(model="m", basic_response=True, tool_calling=True)
    assert r.pipeline_ready is False


# ---------------------------------------------------------------------------
# format_result
# ---------------------------------------------------------------------------


def test_format_result_all_pass():
    r = PreflightResult(
        model="qwen3:8b",
        basic_response=True,
        basic_response_time=1.2,
        tool_calling=True,
        tool_calling_time=2.3,
        multi_turn=True,
        multi_turn_time=3.4,
    )
    out = format_result(r)
    assert "qwen3:8b" in out
    assert "PASS" in out
    assert "Pipeline ready:  YES" in out
    assert "Basic response" in out
    assert "Tool calling" in out
    assert "Multi-turn" in out


def test_format_result_with_errors():
    r = PreflightResult(
        model="bad-model",
        basic_response=False,
        basic_response_time=0.5,
        basic_response_error="connection refused",
    )
    out = format_result(r)
    assert "bad-model" in out
    assert "FAIL" in out
    assert "connection refused" in out
    assert "Pipeline ready:  NO" in out


# ---------------------------------------------------------------------------
# check_model — happy path
# ---------------------------------------------------------------------------


def _make_provider_mock(complete_return=None, tools_returns=None):
    """Build a mock OllamaProvider class.

    complete_return: tuple (text, usage) for provider.complete.
    tools_returns: list of dict responses for sequential complete_with_tools calls.
    """
    if complete_return is None:
        complete_return = ("hello there", {})
    if tools_returns is None:
        tools_returns = []

    instance = AsyncMock()
    instance.complete = AsyncMock(return_value=complete_return)
    instance.complete_with_tools = AsyncMock(side_effect=tools_returns)
    return instance


@pytest.mark.asyncio
async def test_check_model_all_three_pass():
    tool_use_resp = {
        "content": [
            {"type": "tool_use", "id": "tu_1", "name": "write_file",
             "input": {"path": "hello.txt", "content": "Hello World"}}
        ]
    }
    multi_turn_resp = {
        "content": [
            {"type": "tool_use", "id": "tu_2", "name": "read_file",
             "input": {"path": "hello.txt"}}
        ]
    }
    instance = _make_provider_mock(
        complete_return=("Hi!", {}),
        tools_returns=[tool_use_resp, multi_turn_resp],
    )
    with patch("productteam.preflight.OllamaProvider", return_value=instance):
        r = await check_model("qwen3:8b", timeout=5.0)
    assert r.basic_response is True
    assert r.tool_calling is True
    assert r.multi_turn is True
    assert r.pipeline_ready is True
    assert r.basic_response_error == ""


# ---------------------------------------------------------------------------
# check_model — basic response failures
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_check_model_empty_response_short_circuits():
    instance = _make_provider_mock(complete_return=("", {}))
    with patch("productteam.preflight.OllamaProvider", return_value=instance):
        r = await check_model("m", timeout=5.0)
    assert r.basic_response is False
    assert r.basic_response_error == "Empty response"
    assert r.tool_calling is False
    # Tool calling should not have been attempted
    instance.complete_with_tools.assert_not_called()


@pytest.mark.asyncio
async def test_check_model_basic_whitespace_only_treated_as_empty():
    instance = _make_provider_mock(complete_return=("   \n  ", {}))
    with patch("productteam.preflight.OllamaProvider", return_value=instance):
        r = await check_model("m", timeout=5.0)
    assert r.basic_response is False
    assert r.basic_response_error == "Empty response"


@pytest.mark.asyncio
async def test_check_model_basic_timeout():
    instance = AsyncMock()

    async def slow(*a, **kw):
        await asyncio.sleep(10)
        return ("never", {})

    instance.complete = AsyncMock(side_effect=slow)
    instance.complete_with_tools = AsyncMock()
    with patch("productteam.preflight.OllamaProvider", return_value=instance):
        r = await check_model("m", timeout=0.05)
    assert r.basic_response is False
    assert "Timed out" in r.basic_response_error
    instance.complete_with_tools.assert_not_called()


@pytest.mark.asyncio
async def test_check_model_basic_exception():
    instance = AsyncMock()
    instance.complete = AsyncMock(side_effect=RuntimeError("boom"))
    instance.complete_with_tools = AsyncMock()
    with patch("productteam.preflight.OllamaProvider", return_value=instance):
        r = await check_model("m", timeout=5.0)
    assert r.basic_response is False
    assert "boom" in r.basic_response_error
    assert r.tool_calling is False


# ---------------------------------------------------------------------------
# check_model — tool calling failures
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_check_model_tool_call_returns_text_only():
    text_only = {
        "content": [
            {"type": "text", "text": "I would write the file but I won't."}
        ]
    }
    instance = _make_provider_mock(
        complete_return=("ok", {}),
        tools_returns=[text_only],
    )
    with patch("productteam.preflight.OllamaProvider", return_value=instance):
        r = await check_model("m", timeout=5.0)
    assert r.basic_response is True
    assert r.tool_calling is False
    assert "No tool call" in r.tool_calling_error
    assert r.multi_turn is False


@pytest.mark.asyncio
async def test_check_model_tool_call_wrong_tool_name():
    wrong = {
        "content": [
            {"type": "tool_use", "id": "x", "name": "delete_everything", "input": {}}
        ]
    }
    instance = _make_provider_mock(
        complete_return=("ok", {}),
        tools_returns=[wrong],
    )
    with patch("productteam.preflight.OllamaProvider", return_value=instance):
        r = await check_model("m", timeout=5.0)
    assert r.tool_calling is False
    assert "Called wrong tool" in r.tool_calling_error
    assert "delete_everything" in r.tool_calling_error


@pytest.mark.asyncio
async def test_check_model_tool_call_timeout():
    instance = AsyncMock()
    instance.complete = AsyncMock(return_value=("ok", {}))

    async def slow(*a, **kw):
        await asyncio.sleep(10)
        return {}

    instance.complete_with_tools = AsyncMock(side_effect=slow)
    with patch("productteam.preflight.OllamaProvider", return_value=instance):
        r = await check_model("m", timeout=0.05)
    assert r.basic_response is True
    assert r.tool_calling is False
    assert "Timed out" in r.tool_calling_error


@pytest.mark.asyncio
async def test_check_model_tool_call_exception():
    instance = AsyncMock()
    instance.complete = AsyncMock(return_value=("ok", {}))
    instance.complete_with_tools = AsyncMock(side_effect=ValueError("kapow"))
    with patch("productteam.preflight.OllamaProvider", return_value=instance):
        r = await check_model("m", timeout=5.0)
    assert r.tool_calling is False
    assert "kapow" in r.tool_calling_error


# ---------------------------------------------------------------------------
# check_model — multi-turn branch
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_check_model_multi_turn_text_only_response():
    tool_use_resp = {
        "content": [
            {"type": "tool_use", "id": "tu_1", "name": "write_file", "input": {}}
        ]
    }
    multi_text = {
        "content": [
            {"type": "text", "text": "I already wrote it, no need to read."}
        ]
    }
    instance = _make_provider_mock(
        complete_return=("ok", {}),
        tools_returns=[tool_use_resp, multi_text],
    )
    with patch("productteam.preflight.OllamaProvider", return_value=instance):
        r = await check_model("m", timeout=5.0)
    assert r.tool_calling is True
    assert r.multi_turn is False
    assert "No tool call in turn 2" in r.multi_turn_error


@pytest.mark.asyncio
async def test_check_model_multi_turn_timeout():
    tool_use_resp = {
        "content": [
            {"type": "tool_use", "id": "tu_1", "name": "write_file", "input": {}}
        ]
    }

    instance = AsyncMock()
    instance.complete = AsyncMock(return_value=("ok", {}))

    call_count = {"n": 0}

    async def tools_side_effect(*a, **kw):
        call_count["n"] += 1
        if call_count["n"] == 1:
            return tool_use_resp
        await asyncio.sleep(10)
        return {}

    instance.complete_with_tools = AsyncMock(side_effect=tools_side_effect)
    with patch("productteam.preflight.OllamaProvider", return_value=instance):
        r = await check_model("m", timeout=0.05)
    # First call returned fast; second timed out
    assert r.tool_calling is True
    assert r.multi_turn is False
    assert "Timed out" in r.multi_turn_error


@pytest.mark.asyncio
async def test_check_model_multi_turn_exception():
    tool_use_resp = {
        "content": [
            {"type": "tool_use", "id": "tu_1", "name": "write_file", "input": {}}
        ]
    }
    instance = _make_provider_mock(
        complete_return=("ok", {}),
        tools_returns=[tool_use_resp, RuntimeError("turn 2 broke")],
    )
    with patch("productteam.preflight.OllamaProvider", return_value=instance):
        r = await check_model("m", timeout=5.0)
    assert r.tool_calling is True
    assert r.multi_turn is False
    assert "turn 2 broke" in r.multi_turn_error


# ---------------------------------------------------------------------------
# check_all_models
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_check_all_models_runs_each_sequentially():
    instance = _make_provider_mock(complete_return=("", {}))
    with patch("productteam.preflight.OllamaProvider", return_value=instance):
        results = await check_all_models(["a", "b", "c"], timeout=1.0)
    assert len(results) == 3
    assert [r.model for r in results] == ["a", "b", "c"]
    # All should have failed at basic_response (empty)
    assert all(r.basic_response is False for r in results)


@pytest.mark.asyncio
async def test_check_all_models_empty_list():
    results = await check_all_models([], timeout=1.0)
    assert results == []
