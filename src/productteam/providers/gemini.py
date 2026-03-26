"""Google Gemini API provider."""

from __future__ import annotations

import os

import httpx

from productteam.errors import ProductTeamConfigError
from productteam.providers.base import LLMProvider


class GeminiProvider(LLMProvider):
    """Google Gemini API provider."""

    def __init__(
        self,
        model: str = "gemini-2.0-flash",
        api_key: str | None = None,
    ):
        self._model = model
        self._api_key = api_key or os.environ.get("GEMINI_API_KEY", "")
        if not self._api_key:
            raise ProductTeamConfigError(
                "Gemini API key not found. "
                "Set the GEMINI_API_KEY environment variable."
            )
        self._base_url = "https://generativelanguage.googleapis.com/v1beta"

    async def complete(
        self,
        system: str,
        messages: list[dict],
        max_tokens: int = 8192,
    ) -> str:
        # Convert messages to Gemini format
        contents = []
        for msg in messages:
            role = "user" if msg["role"] == "user" else "model"
            contents.append({
                "role": role,
                "parts": [{"text": msg["content"]}],
            })

        payload = {
            "contents": contents,
            "systemInstruction": {"parts": [{"text": system}]},
            "generationConfig": {"maxOutputTokens": max_tokens},
        }

        url = (
            f"{self._base_url}/models/{self._model}:generateContent"
            f"?key={self._api_key}"
        )
        async with httpx.AsyncClient(timeout=120.0) as client:
            resp = await client.post(url, json=payload)
            resp.raise_for_status()
            data = resp.json()

        # Extract text from response
        candidates = data.get("candidates", [])
        if not candidates:
            return ""
        parts = candidates[0].get("content", {}).get("parts", [])
        return "".join(p.get("text", "") for p in parts)

    async def complete_with_tools(
        self,
        system: str,
        messages: list[dict],
        tools: list[dict],
        max_tokens: int = 8192,
    ) -> dict:
        contents = []
        for msg in messages:
            role = "user" if msg["role"] == "user" else "model"
            if isinstance(msg.get("content"), str):
                contents.append({
                    "role": role,
                    "parts": [{"text": msg["content"]}],
                })
            elif isinstance(msg.get("content"), list):
                parts = []
                for block in msg["content"]:
                    if block.get("type") == "text":
                        parts.append({"text": block["text"]})
                    elif block.get("type") == "tool_result":
                        parts.append({
                            "functionResponse": {
                                "name": block.get("tool_use_id", "unknown"),
                                "response": {"result": block.get("content", "")},
                            }
                        })
                contents.append({"role": role, "parts": parts})

        # Convert tools to Gemini format
        function_declarations = []
        for tool in tools:
            function_declarations.append({
                "name": tool["name"],
                "description": tool.get("description", ""),
                "parameters": tool.get("input_schema", {}),
            })

        payload = {
            "contents": contents,
            "systemInstruction": {"parts": [{"text": system}]},
            "tools": [{"functionDeclarations": function_declarations}],
            "generationConfig": {"maxOutputTokens": max_tokens},
        }

        url = (
            f"{self._base_url}/models/{self._model}:generateContent"
            f"?key={self._api_key}"
        )
        async with httpx.AsyncClient(timeout=120.0) as client:
            resp = await client.post(url, json=payload)
            resp.raise_for_status()
            data = resp.json()

        candidates = data.get("candidates", [])
        content = []
        if candidates:
            parts = candidates[0].get("content", {}).get("parts", [])
            for part in parts:
                if "text" in part:
                    content.append({"type": "text", "text": part["text"]})
                elif "functionCall" in part:
                    import uuid
                    fc = part["functionCall"]
                    content.append({
                        "type": "tool_use",
                        "id": f"toolu_{uuid.uuid4().hex[:24]}",
                        "name": fc["name"],
                        "input": fc.get("args", {}),
                    })

        has_tool_use = any(c["type"] == "tool_use" for c in content)
        return {
            "role": "assistant",
            "content": content,
            "stop_reason": "tool_use" if has_tool_use else "end_turn",
        }

    def name(self) -> str:
        return "gemini"

    def model_id(self) -> str:
        return self._model


