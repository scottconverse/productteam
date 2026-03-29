"""Preflight model capability checker.

Quick diagnostic that tests whether an Ollama model can:
1. Respond to a basic prompt
2. Make tool calls (write_file)
3. Handle multi-turn tool conversations (read result, call another tool)

Usage:
    from productteam.preflight import check_model
    result = asyncio.run(check_model("qwen3:8b"))
"""

from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass

from productteam.providers.ollama import OllamaProvider


@dataclass
class PreflightResult:
    model: str
    basic_response: bool = False
    basic_response_time: float = 0.0
    basic_response_error: str = ""
    tool_calling: bool = False
    tool_calling_time: float = 0.0
    tool_calling_error: str = ""
    multi_turn: bool = False
    multi_turn_time: float = 0.0
    multi_turn_error: str = ""

    @property
    def pipeline_ready(self) -> bool:
        return self.basic_response and self.tool_calling and self.multi_turn


_WRITE_FILE_TOOL = {
    "name": "write_file",
    "description": "Write content to a file at the given path.",
    "input_schema": {
        "type": "object",
        "properties": {
            "path": {"type": "string", "description": "File path to write to"},
            "content": {"type": "string", "description": "Content to write"},
        },
        "required": ["path", "content"],
    },
}

_READ_FILE_TOOL = {
    "name": "read_file",
    "description": "Read the contents of a file at the given path.",
    "input_schema": {
        "type": "object",
        "properties": {
            "path": {"type": "string", "description": "File path to read"},
        },
        "required": ["path"],
    },
}


async def check_model(
    model: str,
    host: str = "",
    timeout: float = 120.0,
) -> PreflightResult:
    """Run all preflight checks on a model. Returns PreflightResult."""
    result = PreflightResult(model=model)
    provider = OllamaProvider(model=model, host=host)

    # Test 1: Basic response
    t0 = time.monotonic()
    try:
        text, _usage = await asyncio.wait_for(
            provider.complete(
                system="You are a helpful assistant. Be brief.",
                messages=[{"role": "user", "content": "Say hello in one sentence."}],
                max_tokens=512,
            ),
            timeout=timeout,
        )
        result.basic_response_time = time.monotonic() - t0
        if text and len(text.strip()) > 0:
            result.basic_response = True
        else:
            result.basic_response_error = "Empty response"
    except asyncio.TimeoutError:
        result.basic_response_time = time.monotonic() - t0
        result.basic_response_error = f"Timed out after {timeout:.0f}s"
    except Exception as e:
        result.basic_response_time = time.monotonic() - t0
        result.basic_response_error = str(e)

    if not result.basic_response:
        return result

    # Test 2: Tool calling
    t0 = time.monotonic()
    try:
        resp = await asyncio.wait_for(
            provider.complete_with_tools(
                system=(
                    "You are a coding assistant. You MUST use the write_file tool "
                    "to create files. Do not describe what you would do — use the tool."
                ),
                messages=[{
                    "role": "user",
                    "content": "Create a file called hello.txt with the content 'Hello World'",
                }],
                tools=[_WRITE_FILE_TOOL],
                max_tokens=256,
            ),
            timeout=timeout,
        )
        result.tool_calling_time = time.monotonic() - t0

        # Check if response contains a tool_use block
        tool_uses = [
            b for b in resp.get("content", [])
            if b.get("type") == "tool_use"
        ]
        if tool_uses:
            tc = tool_uses[0]
            if tc.get("name") == "write_file":
                result.tool_calling = True
            else:
                result.tool_calling_error = (
                    f"Called wrong tool: {tc.get('name')} (expected write_file)"
                )
        else:
            # Model responded with text instead of tool call
            text_parts = [
                b.get("text", "") for b in resp.get("content", [])
                if b.get("type") == "text"
            ]
            preview = " ".join(text_parts)[:100]
            result.tool_calling_error = f"No tool call — responded with text: {preview!r}"
    except asyncio.TimeoutError:
        result.tool_calling_time = time.monotonic() - t0
        result.tool_calling_error = f"Timed out after {timeout:.0f}s"
    except Exception as e:
        result.tool_calling_time = time.monotonic() - t0
        result.tool_calling_error = str(e)

    if not result.tool_calling:
        return result

    # Test 3: Multi-turn tool use
    t0 = time.monotonic()
    try:
        # Build conversation: user asked to write, assistant called write_file,
        # we return the tool result, then ask it to read the file.
        tool_use_block = [
            b for b in resp.get("content", [])
            if b.get("type") == "tool_use"
        ][0]
        tool_id = tool_use_block["id"]

        messages = [
            {"role": "user", "content": "Create a file called hello.txt with the content 'Hello World'"},
            {"role": "assistant", "content": resp["content"]},
            {"role": "user", "content": [
                {
                    "type": "tool_result",
                    "tool_use_id": tool_id,
                    "content": "File written successfully: hello.txt",
                }
            ]},
            {"role": "user", "content": (
                "Good. Now use the read_file tool to read hello.txt. "
                "You MUST call the read_file tool. Do not respond with text."
            )},
        ]

        resp2 = await asyncio.wait_for(
            provider.complete_with_tools(
                system=(
                    "You are a coding assistant. You MUST use tools to complete tasks. "
                    "Never describe what you would do — always call the appropriate tool. "
                    "Use read_file to read files."
                ),
                messages=messages,
                tools=[_WRITE_FILE_TOOL, _READ_FILE_TOOL],
                max_tokens=256,
            ),
            timeout=timeout,
        )
        result.multi_turn_time = time.monotonic() - t0

        tool_uses2 = [
            b for b in resp2.get("content", [])
            if b.get("type") == "tool_use"
        ]
        if tool_uses2:
            result.multi_turn = True
        else:
            text_parts = [
                b.get("text", "") for b in resp2.get("content", [])
                if b.get("type") == "text"
            ]
            preview = " ".join(text_parts)[:100]
            result.multi_turn_error = f"No tool call in turn 2 — text: {preview!r}"
    except asyncio.TimeoutError:
        result.multi_turn_time = time.monotonic() - t0
        result.multi_turn_error = f"Timed out after {timeout:.0f}s"
    except Exception as e:
        result.multi_turn_time = time.monotonic() - t0
        result.multi_turn_error = str(e)

    return result


async def check_all_models(
    models: list[str],
    host: str = "",
    timeout: float = 120.0,
) -> list[PreflightResult]:
    """Run preflight checks on multiple models sequentially."""
    results = []
    for model in models:
        r = await check_model(model, host=host, timeout=timeout)
        results.append(r)
    return results


def format_result(r: PreflightResult) -> str:
    """Format a single preflight result as a readable string."""
    lines = [f"  Model: {r.model}"]

    def _status(passed: bool, t: float, err: str) -> str:
        if passed:
            return f"PASS ({t:.1f}s)"
        return f"FAIL — {err}"

    lines.append(f"    Basic response:  {_status(r.basic_response, r.basic_response_time, r.basic_response_error)}")
    lines.append(f"    Tool calling:    {_status(r.tool_calling, r.tool_calling_time, r.tool_calling_error)}")
    lines.append(f"    Multi-turn:      {_status(r.multi_turn, r.multi_turn_time, r.multi_turn_error)}")
    lines.append(f"    Pipeline ready:  {'YES' if r.pipeline_ready else 'NO'}")
    return "\n".join(lines)
