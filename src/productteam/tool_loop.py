"""Tool-use loop for doer stages (Builder, Evaluator, Doc Writer).

This module implements the agentic loop that lets doer agents
read files, write code, run commands, and react to results.
Four tools only: read_file, write_file, run_bash, list_dir.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import re
import shlex
import subprocess
import sys
from pathlib import Path

logger = logging.getLogger(__name__)

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
        "description": "Run a shell command in the project directory. Returns stdout, stderr, and exit code. Python and pip are available on PATH — use 'python' and 'pip' directly (do NOT search for them).",
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


# Shell metacharacter pattern — commands matching this need shell=True
_SHELL_FEATURE_RE = re.compile(r"[|><;]|&&|\|\||`|\$\(")


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


def _check_write_restricted(path_str: str) -> str | None:
    """Block writes to .claude/ and .productteam/ directories.

    Exception: .productteam/sprints/ is writable (Planner needs it).
    Returns an error string if blocked, None if OK.
    """
    parts = Path(path_str).parts
    if not parts:
        return None
    top = parts[0]
    if top == ".claude":
        return f"Writes to .claude/ are blocked: {path_str}"
    if top == ".productteam":
        # Allow .productteam/sprints/ and anything below it
        if len(parts) >= 2 and parts[1] == "sprints":
            return None
        return f"Writes to .productteam/ are blocked (except sprints/): {path_str}"
    return None


# Patterns that indicate environment variable dumping
ENV_DUMP_PATTERNS = [
    "printenv", "/proc/self/environ", "/proc/environ",
    "export | ", "export|",
    "set | grep", "set |grep",
]

# Patterns where "env" is used as a command (not as part of a word like "poetry env")
ENV_CMD_PATTERNS = [" env | ", " env|"]

# Windows/PowerShell patterns that dump or read environment variables
WIN_ENV_PATTERNS = [
    "$env:",                                        # PowerShell env access
    "get-childitem env:",                           # PowerShell env listing
    "[system.environment]::getenvironmentvariable",  # .NET env access
    "[environment]::getenvironmentvariable",         # .NET shorthand
]

# Credential-adjacent keywords
CRED_KEYWORDS = ["api_key", "token", "secret", "password", "credential"]

# Commands that read environment variables (used with CRED_KEYWORDS)
ENV_READ_CMDS = ["echo $", "echo ${", "printenv", "os.environ"]


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
    lower = command.lower()
    for pattern in ENV_DUMP_PATTERNS:
        if pattern in lower:
            return "Command attempts to read environment variables"

    # "env" as a standalone command (at start or after space, not inside words)
    for pattern in ENV_CMD_PATTERNS:
        if pattern in lower or lower.startswith(pattern.lstrip()):
            return "Command attempts to read environment variables"

    # Block Windows/PowerShell environment variable access
    for pattern in WIN_ENV_PATTERNS:
        if pattern in lower:
            return "Command attempts to read environment variables"

    # Block credential-adjacent keywords combined with env-reading commands
    if any(kw in lower for kw in CRED_KEYWORDS):
        if any(cmd in lower for cmd in ENV_READ_CMDS):
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
        # Block writes to .claude/ and .productteam/ (except sprints/)
        write_err = _check_write_restricted(path_str)
        if write_err:
            return json.dumps({"error": write_err})
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
            # Ensure Python is on PATH for the subprocess.
            env = os.environ.copy()
            python_dir = str(Path(sys.executable).parent)
            env["PATH"] = python_dir + os.pathsep + env.get("PATH", "")
            venv_scripts = project_dir / ".venv" / ("Scripts" if os.name == "nt" else "bin")
            if venv_scripts.exists():
                env["PATH"] = str(venv_scripts) + os.pathsep + env["PATH"]

            # Default to shell=False for security. Fall back to shell=True
            # only when the command uses shell features that require it.
            use_shell = bool(_SHELL_FEATURE_RE.search(command))
            if use_shell:
                logger.warning("run_bash: shell=True fallback for: %s", command)
                cmd_arg: str | list[str] = command
            else:
                cmd_arg = shlex.split(command)

            result = subprocess.run(
                cmd_arg,
                shell=use_shell,
                cwd=str(project_dir),
                capture_output=True,
                text=True,
                timeout=timeout,
                env=env,
                encoding="utf-8",
                errors="replace",
            )
            return json.dumps({
                "stdout": result.stdout[-4000:] if len(result.stdout) > 4000 else result.stdout,
                "stderr": result.stderr[-2000:] if len(result.stderr) > 2000 else result.stderr,
                "exit_code": result.returncode,
            })
        except subprocess.TimeoutExpired:
            return json.dumps({"error": f"Command timed out after {timeout} seconds"})
        except OSError as e:
            # Windows subprocess errors (WinError 6/50) when stdout handles are invalid
            return json.dumps({"error": f"Command failed (OS error): {e}"})
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
        input_tokens: int = 0,
        output_tokens: int = 0,
        cache_creation_input_tokens: int = 0,
        cache_read_input_tokens: int = 0,
    ):
        self.final_text = final_text
        self.tool_call_count = tool_call_count
        self.status = status  # "complete" | "stuck" | "max_calls"
        self.messages = messages
        self.input_tokens = input_tokens
        self.output_tokens = output_tokens
        self.cache_creation_input_tokens = cache_creation_input_tokens
        self.cache_read_input_tokens = cache_read_input_tokens


async def run_tool_loop(
    provider: LLMProvider,
    system_prompt: str,
    initial_user_message: str,
    project_dir: Path,
    max_tool_calls: int = 50,
    timeout_seconds: float | None = None,
    loop_detection_window: int = 5,
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
        loop_detection_window: Consecutive identical calls before marking stuck.

    Returns:
        ToolLoopResult with final text, call count, and status.
    """
    if timeout_seconds is not None:
        try:
            return await asyncio.wait_for(
                _run_tool_loop_inner(
                    provider, system_prompt, initial_user_message,
                    project_dir, max_tool_calls, loop_detection_window,
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
        project_dir, max_tool_calls, loop_detection_window,
    )


_MAX_HISTORY_EXCHANGES = 10  # Keep last 10 tool call/result pairs


def _truncate_messages(messages: list[dict]) -> list[dict]:
    """Keep the initial task message plus the last N tool exchanges.

    Prevents O(n²) token growth in long tool loops. Each exchange is
    2 messages: assistant (tool_use) + user (tool_result).
    The initial user message is always preserved so the model remembers
    what it was asked to do.
    """
    if len(messages) <= 1:
        return messages

    first = messages[:1]           # Always keep the initial task
    rest = messages[1:]            # Everything after the task
    max_msgs = _MAX_HISTORY_EXCHANGES * 2  # Each exchange = 2 messages

    if len(rest) <= max_msgs:
        return messages            # No truncation needed yet

    return first + rest[-max_msgs:]  # Task + last N exchanges


async def _run_tool_loop_inner(
    provider: LLMProvider,
    system_prompt: str,
    initial_user_message: str,
    project_dir: Path,
    max_tool_calls: int = 50,
    loop_detection_window: int = 5,
) -> ToolLoopResult:
    """Inner tool loop implementation."""
    messages: list[dict] = [
        {"role": "user", "content": initial_user_message},
    ]
    total_tool_calls = 0
    total_input_tokens = 0
    total_output_tokens = 0
    total_cache_creation = 0
    total_cache_read = 0
    last_tool_calls: list[tuple[str, str]] = []  # (name, args_hash) for loop detection

    while True:
        response = await provider.complete_with_tools(
            system=system_prompt,
            messages=_truncate_messages(messages),
            tools=BUILDER_TOOLS,
        )

        # Accumulate token usage
        usage = response.get("usage", {})
        total_input_tokens += usage.get("input_tokens", 0)
        total_output_tokens += usage.get("output_tokens", 0)
        total_cache_creation += usage.get("cache_creation_input_tokens", 0)
        total_cache_read += usage.get("cache_read_input_tokens", 0)

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
                input_tokens=total_input_tokens,
                output_tokens=total_output_tokens,
                cache_creation_input_tokens=total_cache_creation,
                cache_read_input_tokens=total_cache_read,
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

            # Loop detection: same tool + same args N times in a row
            args_hash = json.dumps(tool_input, sort_keys=True)
            call_sig = (tool_name, args_hash)
            last_tool_calls.append(call_sig)
            if len(last_tool_calls) > loop_detection_window:
                last_tool_calls.pop(0)
            if (
                len(last_tool_calls) == loop_detection_window
                and len(set(last_tool_calls)) == 1
            ):
                return ToolLoopResult(
                    final_text=f"Loop detected: {tool_name} called {loop_detection_window} times with identical args",
                    tool_call_count=total_tool_calls,
                    status="stuck",
                    messages=messages,
                    input_tokens=total_input_tokens,
                    output_tokens=total_output_tokens,
                    cache_creation_input_tokens=total_cache_creation,
                    cache_read_input_tokens=total_cache_read,
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
                input_tokens=total_input_tokens,
                output_tokens=total_output_tokens,
                cache_creation_input_tokens=total_cache_creation,
                cache_read_input_tokens=total_cache_read,
            )
