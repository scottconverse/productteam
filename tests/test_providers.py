"""Tests for the multi-provider LLM abstraction layer."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest

from productteam.errors import ProductTeamConfigError
from productteam.providers.base import LLMProvider
from productteam.providers.factory import get_provider


# ---------------------------------------------------------------------------
# Factory selection tests
# ---------------------------------------------------------------------------


def test_factory_unknown_provider_raises():
    """get_provider raises for unknown provider name."""
    with pytest.raises(ProductTeamConfigError, match="Unknown provider"):
        get_provider(provider="nonexistent")


def test_factory_anthropic_with_key(monkeypatch):
    """get_provider('anthropic') returns AnthropicProvider when key is set."""
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key-123")
    with patch("productteam.providers.anthropic.anthropic") as mock_sdk:
        mock_sdk.AsyncAnthropic = MagicMock(return_value=MagicMock())
        p = get_provider(provider="anthropic")
        assert p.name() == "anthropic"
        assert isinstance(p, LLMProvider)


def test_factory_anthropic_no_key_raises(monkeypatch):
    """get_provider('anthropic') raises when ANTHROPIC_API_KEY is not set."""
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    with pytest.raises(ProductTeamConfigError, match="ANTHROPIC_API_KEY"):
        get_provider(provider="anthropic")


def test_factory_openai_with_key(monkeypatch):
    """get_provider('openai') returns OpenAIProvider when key is set."""
    monkeypatch.setenv("OPENAI_API_KEY", "test-key-456")
    p = get_provider(provider="openai")
    assert p.name() == "openai"
    assert isinstance(p, LLMProvider)


def test_factory_openai_with_api_base_no_key(monkeypatch):
    """get_provider('openai') works with api_base and no key (local server)."""
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    p = get_provider(provider="openai", api_base="http://localhost:1234/v1")
    assert p.name() == "openai"


def test_factory_openai_no_key_no_base_raises(monkeypatch):
    """get_provider('openai') raises when neither key nor api_base is set."""
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    with pytest.raises(ProductTeamConfigError, match="OPENAI_API_KEY"):
        get_provider(provider="openai")


def test_factory_ollama_default():
    """get_provider('ollama') returns OllamaProvider with defaults."""
    p = get_provider(provider="ollama")
    assert p.name() == "ollama"
    assert isinstance(p, LLMProvider)


def test_factory_gemini_with_key(monkeypatch):
    """get_provider('gemini') returns GeminiProvider when key is set."""
    monkeypatch.setenv("GEMINI_API_KEY", "test-key-789")
    p = get_provider(provider="gemini")
    assert p.name() == "gemini"
    assert isinstance(p, LLMProvider)


def test_factory_gemini_no_key_raises(monkeypatch):
    """get_provider('gemini') raises when GEMINI_API_KEY is not set."""
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    with pytest.raises(ProductTeamConfigError, match="GEMINI_API_KEY"):
        get_provider(provider="gemini")


def test_factory_case_insensitive(monkeypatch):
    """Provider name is case-insensitive."""
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")
    with patch("productteam.providers.anthropic.anthropic") as mock_sdk:
        mock_sdk.AsyncAnthropic = MagicMock(return_value=MagicMock())
        p = get_provider(provider="ANTHROPIC")
        assert p.name() == "anthropic"


def test_factory_custom_model(monkeypatch):
    """Custom model name is passed through to provider."""
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")
    with patch("productteam.providers.anthropic.anthropic") as mock_sdk:
        mock_sdk.AsyncAnthropic = MagicMock(return_value=MagicMock())
        p = get_provider(provider="anthropic", model="claude-opus-4-6")
        assert p.model_id() == "claude-opus-4-6"


# ---------------------------------------------------------------------------
# Anthropic provider mock tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_anthropic_complete(monkeypatch):
    """AnthropicProvider.complete() returns text from API response."""
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")

    mock_block = MagicMock()
    mock_block.text = "Hello from Claude"
    mock_block.type = "text"

    mock_usage = MagicMock()
    mock_usage.input_tokens = 100
    mock_usage.output_tokens = 20

    mock_response = MagicMock()
    mock_response.content = [mock_block]
    mock_response.usage = mock_usage

    mock_client = AsyncMock()
    mock_client.messages.create = AsyncMock(return_value=mock_response)

    with patch("productteam.providers.anthropic.anthropic") as mock_sdk:
        mock_sdk.AsyncAnthropic = MagicMock(return_value=mock_client)
        p = get_provider(provider="anthropic")
        text, usage = await p.complete(
            system="You are helpful.",
            messages=[{"role": "user", "content": "Hi"}],
        )

    assert text == "Hello from Claude"
    assert usage["input_tokens"] == 100
    assert usage["output_tokens"] == 20


@pytest.mark.asyncio
async def test_anthropic_complete_with_tools(monkeypatch):
    """AnthropicProvider.complete_with_tools() returns tool_use blocks."""
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")

    mock_block = MagicMock()
    mock_block.type = "tool_use"
    mock_block.id = "toolu_123"
    mock_block.name = "read_file"
    mock_block.input = {"path": "src/main.py"}

    mock_response = MagicMock()
    mock_response.content = [mock_block]
    mock_response.stop_reason = "tool_use"

    mock_client = AsyncMock()
    mock_client.messages.create = AsyncMock(return_value=mock_response)

    with patch("productteam.providers.anthropic.anthropic") as mock_sdk:
        mock_sdk.AsyncAnthropic = MagicMock(return_value=mock_client)
        p = get_provider(provider="anthropic")
        result = await p.complete_with_tools(
            system="You are a builder.",
            messages=[{"role": "user", "content": "Build it"}],
            tools=[{"name": "read_file", "input_schema": {"type": "object"}}],
        )

    assert result["role"] == "assistant"
    assert result["stop_reason"] == "tool_use"
    assert result["content"][0]["type"] == "tool_use"
    assert result["content"][0]["name"] == "read_file"


# ---------------------------------------------------------------------------
# OpenAI provider mock tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_openai_complete(monkeypatch):
    """OpenAIProvider.complete() returns text from API response."""
    monkeypatch.setenv("OPENAI_API_KEY", "test-key")

    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.raise_for_status = MagicMock()
    mock_resp.json.return_value = {
        "choices": [{"message": {"content": "Hello from GPT"}}]
    }

    with patch("productteam.providers.openai.httpx") as mock_httpx:
        mock_client = AsyncMock()
        mock_client.post = AsyncMock(return_value=mock_resp)
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        mock_httpx.AsyncClient = MagicMock(return_value=mock_client)

        p = get_provider(provider="openai")
        result = await p.complete(
            system="You are helpful.",
            messages=[{"role": "user", "content": "Hi"}],
        )

    text, usage = result
    assert text == "Hello from GPT"
    assert usage["input_tokens"] == 0


# ---------------------------------------------------------------------------
# Ollama provider mock tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_ollama_complete():
    """OllamaProvider.complete() returns text from Ollama API."""
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.raise_for_status = MagicMock()
    mock_resp.json.return_value = {
        "message": {"role": "assistant", "content": "Hello from Llama"}
    }

    with patch("productteam.providers.ollama.httpx") as mock_httpx:
        mock_client = AsyncMock()
        mock_client.post = AsyncMock(return_value=mock_resp)
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        mock_httpx.AsyncClient = MagicMock(return_value=mock_client)

        p = get_provider(provider="ollama")
        result = await p.complete(
            system="You are helpful.",
            messages=[{"role": "user", "content": "Hi"}],
        )

    text, usage = result
    assert text == "Hello from Llama"
    assert usage["input_tokens"] == 0


# ---------------------------------------------------------------------------
# Gemini provider mock tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_gemini_complete(monkeypatch):
    """GeminiProvider.complete() returns text from Gemini API."""
    monkeypatch.setenv("GEMINI_API_KEY", "test-key")

    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.raise_for_status = MagicMock()
    mock_resp.json.return_value = {
        "candidates": [{
            "content": {
                "parts": [{"text": "Hello from Gemini"}],
                "role": "model",
            }
        }]
    }

    with patch("productteam.providers.gemini.httpx") as mock_httpx:
        mock_client = AsyncMock()
        mock_client.post = AsyncMock(return_value=mock_resp)
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        mock_httpx.AsyncClient = MagicMock(return_value=mock_client)

        p = get_provider(provider="gemini")
        result = await p.complete(
            system="You are helpful.",
            messages=[{"role": "user", "content": "Hi"}],
        )

    text, usage = result
    assert text == "Hello from Gemini"
    assert usage["input_tokens"] == 0


@pytest.mark.asyncio
async def test_gemini_complete_with_tools(monkeypatch):
    """GeminiProvider.complete_with_tools() returns tool_use blocks."""
    monkeypatch.setenv("GEMINI_API_KEY", "test-key")

    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.raise_for_status = MagicMock()
    mock_resp.json.return_value = {
        "candidates": [{
            "content": {
                "parts": [
                    {
                        "functionCall": {
                            "name": "read_file",
                            "args": {"path": "src/main.py"},
                        }
                    }
                ],
                "role": "model",
            }
        }]
    }

    with patch("productteam.providers.gemini.httpx") as mock_httpx:
        mock_client = AsyncMock()
        mock_client.post = AsyncMock(return_value=mock_resp)
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        mock_httpx.AsyncClient = MagicMock(return_value=mock_client)

        p = get_provider(provider="gemini")
        result = await p.complete_with_tools(
            system="You are a builder.",
            messages=[{"role": "user", "content": "Read the file"}],
            tools=[{"name": "read_file", "description": "Read a file", "input_schema": {"type": "object"}}],
        )

    assert result["role"] == "assistant"
    assert result["stop_reason"] == "tool_use"
    assert len(result["content"]) == 1
    block = result["content"][0]
    assert block["type"] == "tool_use"
    assert block["name"] == "read_file"
    assert block["input"] == {"path": "src/main.py"}
    assert block["id"].startswith("toolu_")


@pytest.mark.asyncio
async def test_ollama_complete_with_tools():
    """OllamaProvider.complete_with_tools() returns tool_use blocks."""
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.raise_for_status = MagicMock()
    mock_resp.json.return_value = {
        "message": {
            "role": "assistant",
            "content": "",
            "tool_calls": [
                {
                    "function": {
                        "name": "read_file",
                        "arguments": {"path": "src/main.py"},
                    }
                }
            ],
        }
    }

    with patch("productteam.providers.ollama.httpx") as mock_httpx:
        mock_client = AsyncMock()
        mock_client.post = AsyncMock(return_value=mock_resp)
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        mock_httpx.AsyncClient = MagicMock(return_value=mock_client)

        p = get_provider(provider="ollama")
        result = await p.complete_with_tools(
            system="You are a builder.",
            messages=[{"role": "user", "content": "Read the file"}],
            tools=[{"name": "read_file", "description": "Read a file", "input_schema": {"type": "object"}}],
        )

    assert result["role"] == "assistant"
    assert result["stop_reason"] == "tool_use"
    assert len(result["content"]) == 1
    block = result["content"][0]
    assert block["type"] == "tool_use"
    assert block["name"] == "read_file"
    assert block["input"] == {"path": "src/main.py"}
    assert block["id"].startswith("toolu_")


@pytest.mark.asyncio
async def test_openai_complete_with_tools(monkeypatch):
    """OpenAIProvider.complete_with_tools() returns tool_use blocks."""
    monkeypatch.setenv("OPENAI_API_KEY", "test-key")

    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.raise_for_status = MagicMock()
    mock_resp.json.return_value = {
        "choices": [{
            "message": {
                "content": None,
                "tool_calls": [
                    {
                        "id": "call_abc123",
                        "type": "function",
                        "function": {
                            "name": "read_file",
                            "arguments": '{"path": "src/main.py"}',
                        },
                    }
                ],
            },
            "finish_reason": "tool_calls",
        }]
    }

    with patch("productteam.providers.openai.httpx") as mock_httpx:
        mock_client = AsyncMock()
        mock_client.post = AsyncMock(return_value=mock_resp)
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        mock_httpx.AsyncClient = MagicMock(return_value=mock_client)

        p = get_provider(provider="openai")
        result = await p.complete_with_tools(
            system="You are a builder.",
            messages=[{"role": "user", "content": "Read the file"}],
            tools=[{"name": "read_file", "description": "Read a file", "input_schema": {"type": "object"}}],
        )

    assert result["role"] == "assistant"
    assert result["stop_reason"] == "tool_use"
    assert len(result["content"]) == 1
    block = result["content"][0]
    assert block["type"] == "tool_use"
    assert block["id"] == "call_abc123"
    assert block["name"] == "read_file"
    assert block["input"] == {"path": "src/main.py"}


# ---------------------------------------------------------------------------
# OpenAI defensive tool parsing tests (P1 #4)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_openai_tool_args_as_dict(monkeypatch):
    """OpenAI-compatible servers may return arguments as a dict, not string."""
    monkeypatch.setenv("OPENAI_API_KEY", "test-key")

    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.raise_for_status = MagicMock()
    mock_resp.json.return_value = {
        "choices": [{
            "message": {
                "content": None,
                "tool_calls": [{
                    "id": "call_dict",
                    "type": "function",
                    "function": {
                        "name": "write_file",
                        "arguments": {"path": "test.py", "content": "print()"},
                    },
                }],
            },
            "finish_reason": "tool_calls",
        }]
    }

    with patch("productteam.providers.openai.httpx") as mock_httpx:
        mock_client = AsyncMock()
        mock_client.post = AsyncMock(return_value=mock_resp)
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        mock_httpx.AsyncClient = MagicMock(return_value=mock_client)

        p = get_provider(provider="openai")
        result = await p.complete_with_tools(
            system="test", messages=[{"role": "user", "content": "go"}],
            tools=[{"name": "write_file", "input_schema": {"type": "object"}}],
        )

    block = result["content"][0]
    assert block["input"] == {"path": "test.py", "content": "print()"}


@pytest.mark.asyncio
async def test_openai_tool_args_malformed_json(monkeypatch):
    """Malformed JSON arguments should not crash — captured in _raw_arguments."""
    monkeypatch.setenv("OPENAI_API_KEY", "test-key")

    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.raise_for_status = MagicMock()
    mock_resp.json.return_value = {
        "choices": [{
            "message": {
                "content": None,
                "tool_calls": [{
                    "id": "call_bad",
                    "type": "function",
                    "function": {
                        "name": "read_file",
                        "arguments": "{broken json",
                    },
                }],
            },
            "finish_reason": "tool_calls",
        }]
    }

    with patch("productteam.providers.openai.httpx") as mock_httpx:
        mock_client = AsyncMock()
        mock_client.post = AsyncMock(return_value=mock_resp)
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        mock_httpx.AsyncClient = MagicMock(return_value=mock_client)

        p = get_provider(provider="openai")
        result = await p.complete_with_tools(
            system="test", messages=[{"role": "user", "content": "go"}],
            tools=[{"name": "read_file", "input_schema": {"type": "object"}}],
        )

    block = result["content"][0]
    assert block["input"] == {"_raw_arguments": "{broken json"}


@pytest.mark.asyncio
async def test_openai_tool_args_missing(monkeypatch):
    """Missing arguments field should default to empty dict."""
    monkeypatch.setenv("OPENAI_API_KEY", "test-key")

    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.raise_for_status = MagicMock()
    mock_resp.json.return_value = {
        "choices": [{
            "message": {
                "content": None,
                "tool_calls": [{
                    "id": "call_none",
                    "type": "function",
                    "function": {"name": "list_dir"},
                }],
            },
            "finish_reason": "tool_calls",
        }]
    }

    with patch("productteam.providers.openai.httpx") as mock_httpx:
        mock_client = AsyncMock()
        mock_client.post = AsyncMock(return_value=mock_resp)
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        mock_httpx.AsyncClient = MagicMock(return_value=mock_client)

        p = get_provider(provider="openai")
        result = await p.complete_with_tools(
            system="test", messages=[{"role": "user", "content": "go"}],
            tools=[{"name": "list_dir", "input_schema": {"type": "object"}}],
        )

    block = result["content"][0]
    assert block["input"] == {}


# ---------------------------------------------------------------------------
# Gemini function response name test (P1 #5)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_gemini_tool_result_uses_tool_name(monkeypatch):
    """Gemini provider should use tool_name, not tool_use_id, in function responses."""
    monkeypatch.setenv("GEMINI_API_KEY", "test-key")

    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.raise_for_status = MagicMock()
    mock_resp.json.return_value = {
        "candidates": [{
            "content": {
                "parts": [{"text": "Done."}],
            },
        }],
        "usageMetadata": {"promptTokenCount": 10, "candidatesTokenCount": 5},
    }

    # Build messages that include a tool_result with both tool_use_id and tool_name
    messages = [
        {"role": "user", "content": "Read main.py"},
        {"role": "assistant", "content": [
            {"type": "tool_use", "id": "toolu_abc123", "name": "read_file", "input": {"path": "main.py"}},
        ]},
        {"role": "user", "content": [
            {"type": "tool_result", "tool_use_id": "toolu_abc123", "tool_name": "read_file", "content": "print('hi')"},
        ]},
    ]

    with patch("productteam.providers.gemini.httpx") as mock_httpx:
        mock_client = AsyncMock()
        mock_client.post = AsyncMock(return_value=mock_resp)
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        mock_httpx.AsyncClient = MagicMock(return_value=mock_client)

        p = get_provider(provider="gemini")
        result = await p.complete_with_tools(
            system="test", messages=messages,
            tools=[{"name": "read_file", "description": "Read", "input_schema": {"type": "object"}}],
        )

    # Verify the function response name in the request payload
    call_args = mock_client.post.call_args
    payload = call_args.kwargs.get("json") or call_args[1].get("json")
    # Find the functionResponse in the sent contents
    for content_block in payload["contents"]:
        for part in content_block.get("parts", []):
            if "functionResponse" in part:
                assert part["functionResponse"]["name"] == "read_file", \
                    f"Expected 'read_file', got '{part['functionResponse']['name']}'"
                break


# ---------------------------------------------------------------------------
# model_id() tests
# ---------------------------------------------------------------------------


def test_gemini_model_id(monkeypatch):
    """GeminiProvider.model_id() returns the configured model."""
    monkeypatch.setenv("GEMINI_API_KEY", "test-key")
    p = get_provider(provider="gemini", model="gemini-2.0-pro")
    assert p.model_id() == "gemini-2.0-pro"


def test_ollama_model_id():
    """OllamaProvider.model_id() returns the configured model."""
    p = get_provider(provider="ollama", model="mistral")
    assert p.model_id() == "mistral"


def test_openai_model_id(monkeypatch):
    """OpenAIProvider.model_id() returns the configured model."""
    monkeypatch.setenv("OPENAI_API_KEY", "test-key")
    p = get_provider(provider="openai", model="gpt-4-turbo")
    assert p.model_id() == "gpt-4-turbo"


# ---------------------------------------------------------------------------
# Ollama retry on transient errors
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_ollama_retries_on_500():
    """OllamaProvider retries on 500 errors and succeeds on later attempt."""
    from productteam.providers.ollama import OllamaProvider

    ok_resp = MagicMock()
    ok_resp.status_code = 200
    ok_resp.raise_for_status = MagicMock()
    ok_resp.json.return_value = {
        "message": {"role": "assistant", "content": "recovered"}
    }

    err_resp = MagicMock()
    err_resp.status_code = 500
    err_resp.raise_for_status = MagicMock(
        side_effect=httpx.HTTPStatusError(
            "500 Server Error", request=MagicMock(), response=err_resp,
        )
    )

    mock_client = AsyncMock()
    mock_client.post = AsyncMock(side_effect=[err_resp, ok_resp])

    provider = OllamaProvider(model="test-model")

    with patch("productteam.providers.ollama.asyncio.sleep", new_callable=AsyncMock):
        data = await provider._post_with_retry(
            mock_client,
            {"model": "test", "messages": [], "stream": False},
        )
    assert data["message"]["content"] == "recovered"
    assert mock_client.post.call_count == 2


# ---------------------------------------------------------------------------
# Anthropic cache_control tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_anthropic_complete_sends_cache_control():
    """complete() sends system as a list block with cache_control."""
    mock_response = MagicMock()
    mock_response.content = [MagicMock(text="response", type="text")]
    mock_response.usage.input_tokens = 100
    mock_response.usage.output_tokens = 10
    mock_response.usage.cache_creation_input_tokens = 90
    mock_response.usage.cache_read_input_tokens = 0

    with patch("productteam.providers.anthropic.anthropic") as mock_sdk:
        mock_client = MagicMock()
        mock_sdk.AsyncAnthropic.return_value = mock_client
        mock_client.messages.create = AsyncMock(return_value=mock_response)

        from productteam.providers.anthropic import AnthropicProvider
        provider = AnthropicProvider(model="claude-haiku-4-5-20251001", api_key="test-key")
        await provider.complete("You are a builder.", [{"role": "user", "content": "hi"}])

        call_kwargs = mock_client.messages.create.call_args.kwargs
        system_arg = call_kwargs["system"]

        assert isinstance(system_arg, list), "system must be a list for cache_control"
        assert system_arg[0]["type"] == "text"
        assert system_arg[0]["cache_control"] == {"type": "ephemeral"}


@pytest.mark.asyncio
async def test_anthropic_complete_with_tools_sends_cache_control():
    """complete_with_tools() sends system as a list block with cache_control."""
    mock_response = MagicMock()
    mock_response.content = []
    mock_response.stop_reason = "end_turn"
    mock_response.usage.input_tokens = 100
    mock_response.usage.output_tokens = 10
    mock_response.usage.cache_creation_input_tokens = 90
    mock_response.usage.cache_read_input_tokens = 0

    with patch("productteam.providers.anthropic.anthropic") as mock_sdk:
        mock_client = MagicMock()
        mock_sdk.AsyncAnthropic.return_value = mock_client
        mock_client.messages.create = AsyncMock(return_value=mock_response)

        from productteam.providers.anthropic import AnthropicProvider
        provider = AnthropicProvider(model="claude-haiku-4-5-20251001", api_key="test-key")
        await provider.complete_with_tools(
            "You are an evaluator.",
            [{"role": "user", "content": "evaluate"}],
            tools=[],
        )

        call_kwargs = mock_client.messages.create.call_args.kwargs
        system_arg = call_kwargs["system"]

        assert isinstance(system_arg, list)
        assert system_arg[0]["cache_control"] == {"type": "ephemeral"}
