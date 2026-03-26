"""Tool-use loop for doer stages (Builder, Evaluator, Doc Writer).

This module implements the agentic loop that lets doer agents
read files, write code, run commands, and react to results.
Four tools only: read_file, write_file, run_bash, list_dir.
"""

from __future__ import annotations

import asyncio
import json
import os
import subprocess
from pathlib import Path

from productteam.providers.base import LLMProvider


# ---------------------------------------------------------------------------
# Tool definitions (Anthropic-style schema, converted per-provider)
# ---------------------------------------------------------------------------

BUILDER_TOOLS = [
    {
        "name": "read_file",
        "description": "Read a file from the project directory.",
        "input_schema": {
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "Relative path from project root"}
            },
            "required": ["path"],
        },
    },
    {
        "name": "write_file",
        "description": "Write content to a file. Creates directories as needed.",
        "input_schema": {
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "Relative path from project root"},
                "content": {"type": "string", "description": "File content to write"},
            },
            "required": ["path", "content"],
        },
    },
    {
        "name": "run_bash",
        "description": "Run a shell command in the project directory. Returns stdout, stderr, and exit code.",
        "input_schema": {
            "type": "object",
            "properties": {
                "command": {"type": "string", "description": "Shell command to execute"},
                "timeout_seconds": {
                    "type": "integer",
                    "default": 30,
                    "description": "Command timeout in seconds",
                },
            },
            "required": ["command"],
        },
    },
    {
        "name": "list_dir",
        "description": "List files and directories at a path.",
        "input_schema": {
            "type": "object",
            "properties": {
                "path": {
                    "type": "string",
                    "default": ".",
                    "description": "Relative path from project root",
                }
            },
        },
    },
]


# Paths that must never be read or written
FORBIDDEN_PATHS = [
    ".ssh", ".aws", ".gnupg", ".config/gcloud",
    ".zshrc", ".bashrc", ".bash_profile", ".profile",
    ".netrc", ".npmrc", ".pypirc",
]


def _validate_path(path_str: str, project_dir: Path) -> Path | str:
    """Validate that a path is within the project directory.

    Returns the resolved Path if valid, or an error string if not.
    """
    if os.path.isabs(path_str):
        return f"Absolute paths are not allowed: {path_str}"

    if ".." in Path(path_str).parts:
        return f"Path traversal not allowed: {path_str}"

    resolved = (project_dir / path_str).resolve()
    if not str(resolved).startswith(str(project_dir.resolve())):
        return f"Path escapes project directory: {path_str}"

    return resolved


def _validate_command(command: str) -> str | None:
    """Check if a command tries to access credentials or forbidden paths.

    Returns an error string if the command is dangerous, None if OK.
    This is defense-in-depth — the sandbox boundary is path validation,
    not this denylist.
    """
    for forbidden in FORBIDDEN_PATHS:
        if forbidden in command:
            return f"Command accesses forbidden path: {forbidden}"

    # Block commands that dump environment variables (credential leakage)
    _lower = command.lower()
    _ENV_DUMP_PATTERNS = [
        "printenv", "/proc/self/environ", "/proc/environ",
        "env | ", "env|", "export | ", "export|",
        "set | grep", "set |grep",
    ]
    for pattern in _ENV_DUMP_PATTERNS:
        if pattern in _lower:
            return "Command attempts to read environment variables"

    # Block credential-adjacent keywords in env access
    _CRED_KEYWORDS = ["api_key", "token", "secret", "password", "credential"]
    if any(kw in _lower for kw in _CRED_KEYWORDS):
        # Allow if the keyword is in a file path within the project (e.g. test_api_key.py)
        # but block if combined with env-reading commands
        _ENV_CMDS = ["echo $", "echo ${", "printenv", "env", "export", "os.environ"]
        if any(cmd in _lower for cmd in _ENV_CMDS):
            return "Command attempts to read credential environment variables"

    return None


def _execute_tool(
    tool_name: str,
    tool_input: dict,
    project_dir: Path,
) -> str:
    """Execute a single tool call and return the result as a string."""
    MAX_READ_BYTES = 100 * 1024  # 100KB cap on file reads

    if tool_name == "read_file":
        path_str = tool_input.get("path", "")
        validated = _validate_path(path_str, project_dir)
        if isinstance(validated, str):
            return json.dumps({"error": validated})
        if not validated.exists():
            return json.dumps({"error": f"File not found: {path_str}"})
        if not validated.is_file():
            return json.dumps({"error": f"Not a file: {path_str}"})
        try:
            file_size = validated.stat().st_size
            if file_size > MAX_READ_BYTES:
                # Read only the first 100KB and warn
                content = validated.read_bytes()[:MAX_READ_BYTES].decode("utf-8", errors="replace")
                return (
                    content
                    + f"\n\n[TRUNCATED: file is {file_size:,} bytes, "
                    f"showing first {MAX_READ_BYTES // 1024}KB]"
                )
            content = validated.read_text(encoding="utf-8")
            return content
        except Exception as e:
            return json.dumps({"error": f"Failed to read file: {e}"})

    elif tool_name == "write_file":
        path_str = tool_input.get("path", "")
        content = tool_input.get("content", "")
        validated = _validate_path(path_str, project_dir)
        if isinstance(validated, str):
            return json.dumps({"error": validated})
        try:
            validated.parent.mkdir(parents=True, exist_ok=True)
            validated.write_text(content, encoding="utf-8")
            return json.dumps({"success": True, "path": path_str})
        except Exception as e:
            return json.dumps({"error": f"Failed to write file: {e}"})

    elif tool_name == "run_bash":
        command = tool_input.get("command", "")
        timeout = tool_input.get("timeout_seconds", 30)
        cmd_error = _validate_command(command)
        if cmd_error:
            return json.dumps({"error": cmd_error})
        try:
            result = subprocess.run(
                command,
                shell=True,
                cwd=str(project_dir),
                capture_output=True,
                text=True,
                timeout=timeout,
            )
            return json.dumps({
                "stdout": result.stdout[-4000:] if len(result.stdout) > 4000 else result.stdout,
                "stderr": result.stderr[-2000:] if len(result.stderr) > 2000 else result.stderr,
                "exit_code": result.returncode,
            })
        except subprocess.TimeoutExpired:
            return json.dumps({"error": f"Command timed out after {timeout} seconds"})
        except Exception as e:
            return json.dumps({"error": f"Command failed: {e}"})

    elif tool_name == "list_dir":
        path_str = tool_input.get("path", ".")
        validated = _validate_path(path_str, project_dir)
        if isinstance(validated, str):
            return json.dumps({"error": validated})
        if not validated.exists():
            return json.dumps({"error": f"Directory not found: {path_str}"})
        if not validated.is_dir():
            return json.dumps({"error": f"Not a directory: {path_str}"})
        try:
            entries = []
            for item in sorted(validated.iterdir()):
                prefix = "[DIR] " if item.is_dir() else "[FILE] "
                entries.append(prefix + item.name)
            return "\n".join(entries) if entries else "(empty directory)"
        except Exception as e:
            return json.dumps({"error": f"Failed to list directory: {e}"})

    else:
        return json.dumps({"error": f"Unknown tool: {tool_name}"})


class ToolLoopResult:
    """Result of a tool-use loop execution."""

    def __init__(
        self,
        final_text: str,
        tool_call_count: int,
        status: str,
        messages: list[dict],
    ):
        self.final_text = final_text
        self.tool_call_count = tool_call_count
        self.status = status  # "complete" | "stuck" | "max_calls"
        self.messages = messages


async def run_tool_loop(
    provider: LLMProvider,
    system_prompt: str,
    initial_user_message: str,
    project_dir: Path,
    max_tool_calls: int = 50,
    timeout_seconds: float | None = None,
) -> ToolLoopResult:
    """Run the builder tool-use loop.

    The loop:
    1. Call LLM with tools
    2. If response has tool_use blocks, execute them and continue
    3. If response is text-only, builder is done
    4. If max_tool_calls exceeded, mark as stuck

    Args:
        provider: LLM provider to use.
        system_prompt: SKILL.md content as system prompt.
        initial_user_message: The stage prompt with context.
        project_dir: Project directory for tool execution.
        max_tool_calls: Maximum tool calls before marking stuck.
        timeout_seconds: Wall-clock timeout for the entire loop. None = no limit.

    Returns:
        ToolLoopResult with final text, call count, and status.
    """
    if timeout_seconds is not None:
        try:
            return await asyncio.wait_for(
                _run_tool_loop_inner(
                    provider, system_prompt, initial_user_message,
                    project_dir, max_tool_calls,
                ),
                timeout=timeout_seconds,
            )
        except asyncio.TimeoutError:
            return ToolLoopResult(
                final_text=f"Builder timed out after {timeout_seconds}s",
                tool_call_count=0,
                status="stuck",
                messages=[],
            )
    return await _run_tool_loop_inner(
        provider, system_prompt, initial_user_message,
        project_dir, max_tool_calls,
    )


async def _run_tool_loop_inner(
    provider: LLMProvider,
    system_prompt: str,
    initial_user_message: str,
    project_dir: Path,
    max_tool_calls: int = 50,
) -> ToolLoopResult:
    """Inner tool loop implementation."""
    messages: list[dict] = [
        {"role": "user", "content": initial_user_message},
    ]
    total_tool_calls = 0
    last_tool_calls: list[tuple[str, str]] = []  # (name, args_hash) for loop detection

    while True:
        response = await provider.complete_with_tools(
            system=system_prompt,
            messages=messages,
            tools=BUILDER_TOOLS,
        )

        # Check if response has tool_use blocks
        content = response.get("content", [])
        tool_uses = [b for b in content if b.get("type") == "tool_use"]

        if not tool_uses:
            # Text-only response — builder is done
            text_parts = [b["text"] for b in content if b.get("type") == "text"]
            final_text = "\n".join(text_parts)
            return ToolLoopResult(
                final_text=final_text,
                tool_call_count=total_tool_calls,
                status="complete",
                messages=messages,
            )

        # Append assistant message to conversation
        messages.append({"role": "assistant", "content": content})

        # Execute each tool call
        tool_results = []
        for tool_use in tool_uses:
            total_tool_calls += 1
            tool_name = tool_use["name"]
            tool_input = tool_use["input"]
            tool_id = tool_use["id"]

            # Loop detection: same tool + same args 3 times in a row
            args_hash = json.dumps(tool_input, sort_keys=True)
            call_sig = (tool_name, args_hash)
            last_tool_calls.append(call_sig)
            if len(last_tool_calls) > 3:
                last_tool_calls.pop(0)
            if (
                len(last_tool_calls) == 3
                and last_tool_calls[0] == last_tool_calls[1] == last_tool_calls[2]
            ):
                return ToolLoopResult(
                    final_text=f"Loop detected: {tool_name} called 3 times with identical args",
                    tool_call_count=total_tool_calls,
                    status="stuck",
                    messages=messages,
                )

            # Execute the tool
            result_text = _execute_tool(tool_name, tool_input, project_dir)

            tool_results.append({
                "type": "tool_result",
                "tool_use_id": tool_id,
                "content": result_text,
            })

        # Append tool results as user message
        messages.append({"role": "user", "content": tool_results})

        # Check max tool calls
        if total_tool_calls >= max_tool_calls:
            return ToolLoopResult(
                final_text=f"Max tool calls ({max_tool_calls}) exceeded",
                tool_call_count=total_tool_calls,
                status="max_calls",
                messages=messages,
            )
