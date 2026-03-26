"""Tests for the tool-use loop (Builder/UI Builder stages)."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import AsyncMock

import pytest

from productteam.tool_loop import (
    BUILDER_TOOLS,
    _execute_tool,
    _validate_command,
    _validate_path,
    run_tool_loop,
)


# ---------------------------------------------------------------------------
# Path validation tests
# ---------------------------------------------------------------------------


def test_validate_path_relative_ok(tmp_path):
    """Valid relative path returns a resolved Path."""
    result = _validate_path("src/main.py", tmp_path)
    assert isinstance(result, Path)


def test_validate_path_traversal_rejected(tmp_path):
    """Path with .. is rejected."""
    result = _validate_path("../../../etc/passwd", tmp_path)
    assert isinstance(result, str)
    assert "traversal" in result.lower()


def test_validate_path_absolute_rejected(tmp_path):
    """Absolute path is rejected."""
    result = _validate_path("/etc/passwd", tmp_path)
    assert isinstance(result, str)
    # Error message varies by platform (Absolute or escapes)
    assert "not allowed" in result.lower() or "escapes" in result.lower()


def test_validate_path_within_project(tmp_path):
    """Path that resolves within project is accepted."""
    (tmp_path / "src").mkdir()
    result = _validate_path("src", tmp_path)
    assert isinstance(result, Path)


# ---------------------------------------------------------------------------
# Command validation tests
# ---------------------------------------------------------------------------


def test_validate_command_normal():
    """Normal command passes validation."""
    assert _validate_command("pytest tests/ -v") is None


def test_validate_command_ssh_blocked():
    """Command accessing .ssh is blocked."""
    result = _validate_command("cat ~/.ssh/id_rsa")
    assert result is not None
    assert ".ssh" in result


def test_validate_command_aws_blocked():
    """Command accessing .aws is blocked."""
    result = _validate_command("cat ~/.aws/credentials")
    assert result is not None
    assert ".aws" in result


def test_validate_command_bashrc_blocked():
    """Command accessing .bashrc is blocked."""
    result = _validate_command("source ~/.bashrc")
    assert result is not None


def test_validate_command_env_cred_blocked():
    """Command reading credential env vars is blocked."""
    result = _validate_command("printenv ANTHROPIC_API_KEY")
    assert result is not None


def test_validate_command_env_pipe_blocked():
    """env | grep pattern is blocked."""
    assert _validate_command("env | grep KEY") is not None
    assert _validate_command("env|grep SECRET") is not None


def test_validate_command_proc_environ_blocked():
    """Reading /proc/self/environ is blocked."""
    result = _validate_command("cat /proc/self/environ")
    assert result is not None


def test_validate_command_export_dump_blocked():
    """export | grep pattern is blocked."""
    assert _validate_command("export | grep TOKEN") is not None


def test_validate_command_cred_keyword_in_test_file_allowed():
    """File names containing 'api_key' are allowed (e.g. test_api_key.py)."""
    # Normal file operation — no env-reading command
    assert _validate_command("python test_api_key.py") is None


def test_validate_command_poetry_env_allowed():
    """poetry env use is a legitimate command and should not be blocked."""
    assert _validate_command("poetry env use python3.11") is None


def test_validate_command_echo_env_var_blocked():
    """echo $API_KEY is blocked."""
    result = _validate_command("echo $API_KEY")
    assert result is not None


# ---------------------------------------------------------------------------
# Tool execution tests
# ---------------------------------------------------------------------------


def test_execute_read_file(tmp_path):
    """read_file returns file content."""
    (tmp_path / "test.txt").write_text("hello world")
    result = _execute_tool("read_file", {"path": "test.txt"}, tmp_path)
    assert result == "hello world"


def test_execute_read_file_not_found(tmp_path):
    """read_file returns error for missing file."""
    result = _execute_tool("read_file", {"path": "nonexistent.txt"}, tmp_path)
    data = json.loads(result)
    assert "error" in data


def test_execute_read_file_large_file_truncated(tmp_path):
    """read_file truncates files larger than 100KB."""
    large_content = "x" * (200 * 1024)  # 200KB
    (tmp_path / "big.txt").write_text(large_content)
    result = _execute_tool("read_file", {"path": "big.txt"}, tmp_path)
    assert "[TRUNCATED:" in result
    assert "200KB" not in result  # should not contain the full file
    # Should contain approximately 100KB of content
    assert len(result) < 110 * 1024


def test_execute_read_file_traversal_blocked(tmp_path):
    """read_file rejects path traversal."""
    result = _execute_tool("read_file", {"path": "../../etc/passwd"}, tmp_path)
    data = json.loads(result)
    assert "error" in data


def test_execute_write_file(tmp_path):
    """write_file creates file with content."""
    result = _execute_tool(
        "write_file",
        {"path": "output.txt", "content": "test content"},
        tmp_path,
    )
    data = json.loads(result)
    assert data.get("success") is True
    assert (tmp_path / "output.txt").read_text() == "test content"


def test_execute_write_file_creates_dirs(tmp_path):
    """write_file creates parent directories."""
    _execute_tool(
        "write_file",
        {"path": "deep/nested/file.py", "content": "# code"},
        tmp_path,
    )
    assert (tmp_path / "deep" / "nested" / "file.py").exists()


def test_execute_write_file_traversal_blocked(tmp_path):
    """write_file rejects path traversal."""
    result = _execute_tool(
        "write_file",
        {"path": "../escape.txt", "content": "bad"},
        tmp_path,
    )
    data = json.loads(result)
    assert "error" in data


def test_execute_run_bash(tmp_path):
    """run_bash executes command and returns output."""
    result = _execute_tool("run_bash", {"command": "echo hello"}, tmp_path)
    data = json.loads(result)
    assert "hello" in data.get("stdout", "")
    assert data.get("exit_code") == 0


def test_execute_run_bash_timeout(tmp_path):
    """run_bash returns timeout error for long commands."""
    result = _execute_tool(
        "run_bash",
        {"command": "sleep 10", "timeout_seconds": 1},
        tmp_path,
    )
    data = json.loads(result)
    assert "timed out" in data.get("error", "").lower()


def test_execute_run_bash_forbidden_path(tmp_path):
    """run_bash blocks commands accessing forbidden paths."""
    result = _execute_tool(
        "run_bash",
        {"command": "cat ~/.ssh/id_rsa"},
        tmp_path,
    )
    data = json.loads(result)
    assert "error" in data


def test_execute_list_dir(tmp_path):
    """list_dir returns directory contents."""
    (tmp_path / "file1.txt").write_text("a")
    (tmp_path / "subdir").mkdir()
    result = _execute_tool("list_dir", {"path": "."}, tmp_path)
    assert "[FILE] file1.txt" in result
    assert "[DIR] subdir" in result


def test_execute_list_dir_not_found(tmp_path):
    """list_dir returns error for missing directory."""
    result = _execute_tool("list_dir", {"path": "nonexistent"}, tmp_path)
    data = json.loads(result)
    assert "error" in data


def test_execute_unknown_tool(tmp_path):
    """Unknown tool returns error."""
    result = _execute_tool("unknown_tool", {}, tmp_path)
    data = json.loads(result)
    assert "error" in data


# ---------------------------------------------------------------------------
# Tool loop tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_tool_loop_text_only_response(tmp_path):
    """Loop terminates on text-only response (no tool calls)."""
    mock_provider = AsyncMock()
    mock_provider.complete_with_tools = AsyncMock(return_value={
        "role": "assistant",
        "content": [{"type": "text", "text": "Build complete. Ready for review."}],
        "stop_reason": "end_turn",
    })

    result = await run_tool_loop(
        provider=mock_provider,
        system_prompt="You are a builder.",
        initial_user_message="Build something.",
        project_dir=tmp_path,
    )

    assert result.status == "complete"
    assert "Ready for review" in result.final_text
    assert result.tool_call_count == 0


@pytest.mark.asyncio
async def test_tool_loop_one_tool_call(tmp_path):
    """Loop executes one tool call then completes."""
    (tmp_path / "existing.txt").write_text("file content")

    # First call: tool_use, second call: text-only
    mock_provider = AsyncMock()
    mock_provider.complete_with_tools = AsyncMock(side_effect=[
        {
            "role": "assistant",
            "content": [{
                "type": "tool_use",
                "id": "toolu_001",
                "name": "read_file",
                "input": {"path": "existing.txt"},
            }],
            "stop_reason": "tool_use",
        },
        {
            "role": "assistant",
            "content": [{"type": "text", "text": "Done."}],
            "stop_reason": "end_turn",
        },
    ])

    result = await run_tool_loop(
        provider=mock_provider,
        system_prompt="Builder",
        initial_user_message="Read the file.",
        project_dir=tmp_path,
    )

    assert result.status == "complete"
    assert result.tool_call_count == 1


@pytest.mark.asyncio
async def test_tool_loop_write_file(tmp_path):
    """Loop writes a file via write_file tool."""
    mock_provider = AsyncMock()
    mock_provider.complete_with_tools = AsyncMock(side_effect=[
        {
            "role": "assistant",
            "content": [{
                "type": "tool_use",
                "id": "toolu_001",
                "name": "write_file",
                "input": {"path": "hello.py", "content": "print('hello')"},
            }],
            "stop_reason": "tool_use",
        },
        {
            "role": "assistant",
            "content": [{"type": "text", "text": "File written."}],
            "stop_reason": "end_turn",
        },
    ])

    result = await run_tool_loop(
        provider=mock_provider,
        system_prompt="Builder",
        initial_user_message="Write a file.",
        project_dir=tmp_path,
    )

    assert result.status == "complete"
    assert (tmp_path / "hello.py").read_text() == "print('hello')"


@pytest.mark.asyncio
async def test_tool_loop_max_calls_exceeded(tmp_path):
    """Loop returns max_calls when limit is exceeded."""
    mock_provider = AsyncMock()
    # Always return a tool call
    mock_provider.complete_with_tools = AsyncMock(return_value={
        "role": "assistant",
        "content": [{
            "type": "tool_use",
            "id": "toolu_001",
            "name": "list_dir",
            "input": {"path": "."},
        }],
        "stop_reason": "tool_use",
    })

    result = await run_tool_loop(
        provider=mock_provider,
        system_prompt="Builder",
        initial_user_message="Keep going.",
        project_dir=tmp_path,
        max_tool_calls=3,
    )

    # Should hit either max_calls or stuck (loop detection)
    assert result.status in ("max_calls", "stuck")
    assert result.tool_call_count >= 3


@pytest.mark.asyncio
async def test_tool_loop_infinite_loop_detection(tmp_path):
    """Loop detects identical tool calls 3 times in a row."""
    call_count = 0

    async def mock_complete_with_tools(*args, **kwargs):
        nonlocal call_count
        call_count += 1
        return {
            "role": "assistant",
            "content": [{
                "type": "tool_use",
                "id": f"toolu_{call_count:03d}",
                "name": "read_file",
                "input": {"path": "same_file.txt"},
            }],
            "stop_reason": "tool_use",
        }

    mock_provider = AsyncMock()
    mock_provider.complete_with_tools = mock_complete_with_tools

    # Create the file so read doesn't error
    (tmp_path / "same_file.txt").write_text("content")

    result = await run_tool_loop(
        provider=mock_provider,
        system_prompt="Builder",
        initial_user_message="Read the same file over and over.",
        project_dir=tmp_path,
        max_tool_calls=50,
    )

    assert result.status == "stuck"
    assert "Loop detected" in result.final_text


def test_builder_tools_count():
    """Exactly 4 builder tools defined."""
    assert len(BUILDER_TOOLS) == 4
    names = {t["name"] for t in BUILDER_TOOLS}
    assert names == {"read_file", "write_file", "run_bash", "list_dir"}
