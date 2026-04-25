"""Tests for productteam.onboard — interactive onboarding wizard.

Covers prefs IO, key obfuscation, Ollama detection, provider flows,
and the main wizard orchestrator. Self-contained: all subprocess,
prompts, console IO, filesystem, env, and pipeline imports are mocked.
"""
from __future__ import annotations

import base64
import json
import subprocess
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from productteam import onboard


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def tmp_prefs(tmp_path, monkeypatch):
    """Redirect _PREFS_DIR/_PREFS_FILE to a temp dir."""
    prefs_dir = tmp_path / ".productteam"
    prefs_file = prefs_dir / "prefs.json"
    monkeypatch.setattr(onboard, "_PREFS_DIR", prefs_dir)
    monkeypatch.setattr(onboard, "_PREFS_FILE", prefs_file)
    return prefs_file


@pytest.fixture
def clean_env(monkeypatch):
    for var in ("ANTHROPIC_API_KEY", "OPENAI_API_KEY", "GEMINI_API_KEY"):
        monkeypatch.delenv(var, raising=False)
    yield monkeypatch


# ---------------------------------------------------------------------------
# Preferences IO
# ---------------------------------------------------------------------------

class TestPrefs:
    def test_load_missing_returns_empty(self, tmp_prefs):
        assert onboard._load_prefs() == {}

    def test_load_valid_json(self, tmp_prefs):
        tmp_prefs.parent.mkdir(parents=True, exist_ok=True)
        tmp_prefs.write_text(json.dumps({"provider": "ollama", "model": "x"}), encoding="utf-8")
        assert onboard._load_prefs() == {"provider": "ollama", "model": "x"}

    def test_load_corrupt_json_returns_empty(self, tmp_prefs):
        tmp_prefs.parent.mkdir(parents=True, exist_ok=True)
        tmp_prefs.write_text("not json{", encoding="utf-8")
        assert onboard._load_prefs() == {}

    def test_load_oserror_returns_empty(self, tmp_prefs, monkeypatch):
        tmp_prefs.parent.mkdir(parents=True, exist_ok=True)
        tmp_prefs.write_text("{}", encoding="utf-8")
        def boom(*a, **k):
            raise OSError("denied")
        monkeypatch.setattr(Path, "read_text", boom)
        assert onboard._load_prefs() == {}

    def test_save_creates_dir_and_writes(self, tmp_prefs):
        onboard._save_prefs({"k": "v"})
        assert tmp_prefs.exists()
        assert json.loads(tmp_prefs.read_text(encoding="utf-8")) == {"k": "v"}

    def test_save_roundtrip(self, tmp_prefs):
        data = {"provider": "anthropic", "api_key": "abc", "model": "m"}
        onboard._save_prefs(data)
        assert onboard._load_prefs() == data


# ---------------------------------------------------------------------------
# Key obfuscation
# ---------------------------------------------------------------------------

class TestKeyObfuscation:
    def test_obfuscate_deobfuscate_roundtrip(self):
        key = "sk-ant-1234567890"
        encoded = onboard._obfuscate_key(key)
        assert encoded != key
        assert onboard._deobfuscate_key(encoded) == key

    def test_obfuscate_is_b64(self):
        encoded = onboard._obfuscate_key("hello")
        assert base64.b64decode(encoded).decode() == "hello"

    def test_deobfuscate_invalid_returns_empty(self):
        assert onboard._deobfuscate_key("!!!not-base64!!!") == ""

    def test_mask_long_key(self):
        key = "sk-ant-abcdefghijklmnopqrstuvwxyz1234"
        masked = onboard._mask_key(key)
        assert masked.startswith(key[:7])
        assert masked.endswith(key[-4:])
        assert "..." in masked

    def test_mask_short_key(self):
        assert onboard._mask_key("short") == "***"
        assert onboard._mask_key("a" * 15) == "***"


# ---------------------------------------------------------------------------
# Ollama detection
# ---------------------------------------------------------------------------

class TestOllamaDetection:
    def test_check_installed_success(self, monkeypatch):
        mock_result = MagicMock(returncode=0, stdout="ollama version is 0.1.0\n")
        monkeypatch.setattr(subprocess, "run", lambda *a, **k: mock_result)
        installed, version = onboard._check_ollama_installed()
        assert installed is True
        assert version == "0.1.0"

    def test_check_installed_nonzero(self, monkeypatch):
        mock_result = MagicMock(returncode=1, stdout="")
        monkeypatch.setattr(subprocess, "run", lambda *a, **k: mock_result)
        installed, version = onboard._check_ollama_installed()
        assert installed is False
        assert version == ""

    def test_check_installed_filenotfound(self, monkeypatch):
        def boom(*a, **k): raise FileNotFoundError()
        monkeypatch.setattr(subprocess, "run", boom)
        assert onboard._check_ollama_installed() == (False, "")

    def test_check_installed_timeout(self, monkeypatch):
        def boom(*a, **k): raise subprocess.TimeoutExpired(cmd="ollama", timeout=10)
        monkeypatch.setattr(subprocess, "run", boom)
        assert onboard._check_ollama_installed() == (False, "")

    def test_check_installed_oserror(self, monkeypatch):
        def boom(*a, **k): raise OSError("denied")
        monkeypatch.setattr(subprocess, "run", boom)
        assert onboard._check_ollama_installed() == (False, "")

    def test_list_models_success(self, monkeypatch):
        out = "NAME ID SIZE\ngpt-oss:20b abc 13GB\ndevstral:24b def 14GB\n"
        mock_result = MagicMock(returncode=0, stdout=out)
        monkeypatch.setattr(subprocess, "run", lambda *a, **k: mock_result)
        models = onboard._list_ollama_models()
        assert "gpt-oss:20b" in models
        assert "devstral:24b" in models

    def test_list_models_empty(self, monkeypatch):
        mock_result = MagicMock(returncode=0, stdout="NAME ID SIZE\n")
        monkeypatch.setattr(subprocess, "run", lambda *a, **k: mock_result)
        assert onboard._list_ollama_models() == []

    def test_list_models_nonzero(self, monkeypatch):
        mock_result = MagicMock(returncode=1, stdout="")
        monkeypatch.setattr(subprocess, "run", lambda *a, **k: mock_result)
        assert onboard._list_ollama_models() == []

    def test_list_models_filenotfound(self, monkeypatch):
        def boom(*a, **k): raise FileNotFoundError()
        monkeypatch.setattr(subprocess, "run", boom)
        assert onboard._list_ollama_models() == []

    def test_list_models_timeout(self, monkeypatch):
        def boom(*a, **k): raise subprocess.TimeoutExpired(cmd="x", timeout=10)
        monkeypatch.setattr(subprocess, "run", boom)
        assert onboard._list_ollama_models() == []

    def test_find_recommended_primary(self):
        primary = onboard.RECOMMENDED_MODELS[0][0]
        backup = onboard.RECOMMENDED_MODELS[1][0]
        assert onboard._find_recommended_model([primary, "other"]) == primary
        assert onboard._find_recommended_model([backup]) == backup
        assert onboard._find_recommended_model(["other"]) is None
        assert onboard._find_recommended_model([]) is None

    def test_pull_model_success(self, monkeypatch):
        mock_result = MagicMock(returncode=0)
        monkeypatch.setattr(subprocess, "run", lambda *a, **k: mock_result)
        assert onboard._pull_ollama_model("m") is True

    def test_pull_model_failure(self, monkeypatch):
        mock_result = MagicMock(returncode=1)
        monkeypatch.setattr(subprocess, "run", lambda *a, **k: mock_result)
        assert onboard._pull_ollama_model("m") is False

    def test_pull_model_timeout(self, monkeypatch):
        def boom(*a, **k): raise subprocess.TimeoutExpired(cmd="x", timeout=10)
        monkeypatch.setattr(subprocess, "run", boom)
        assert onboard._pull_ollama_model("m") is False

    def test_pull_model_oserror(self, monkeypatch):
        def boom(*a, **k): raise OSError()
        monkeypatch.setattr(subprocess, "run", boom)
        assert onboard._pull_ollama_model("m") is False


# ---------------------------------------------------------------------------
# Concept input
# ---------------------------------------------------------------------------

class TestGetConcept:
    def test_get_concept_first_try(self, monkeypatch):
        monkeypatch.setattr(onboard.Prompt, "ask", lambda *a, **k: "Build me a thing")
        assert onboard._get_concept() == "Build me a thing"

    def test_get_concept_strips(self, monkeypatch):
        monkeypatch.setattr(onboard.Prompt, "ask", lambda *a, **k: "  hello  ")
        assert onboard._get_concept() == "hello"

    def test_get_concept_reprompts_on_blank(self, monkeypatch):
        responses = iter(["", "   ", "real concept"])
        monkeypatch.setattr(onboard.Prompt, "ask", lambda *a, **k: next(responses))
        assert onboard._get_concept() == "real concept"


# ---------------------------------------------------------------------------
# Local flow
# ---------------------------------------------------------------------------

class TestFlowLocal:
    def test_ollama_not_installed(self, tmp_prefs, monkeypatch):
        monkeypatch.setattr(onboard, "_check_ollama_installed", lambda: (False, ""))
        assert onboard._flow_local({}) is None

    def test_primary_installed(self, tmp_prefs, monkeypatch):
        primary = onboard.RECOMMENDED_MODELS[0][0]
        monkeypatch.setattr(onboard, "_check_ollama_installed", lambda: (True, "0.1"))
        monkeypatch.setattr(onboard, "_list_ollama_models", lambda: [primary])
        prefs = {"old": "data"}
        result = onboard._flow_local(prefs)
        assert result == {"provider": "ollama", "model": primary}
        assert prefs["provider"] == "ollama"
        assert prefs["model"] == primary

    def test_backup_only_installed(self, tmp_prefs, monkeypatch):
        backup = onboard.RECOMMENDED_MODELS[1][0]
        monkeypatch.setattr(onboard, "_check_ollama_installed", lambda: (True, "0.1"))
        monkeypatch.setattr(onboard, "_list_ollama_models", lambda: [backup])
        result = onboard._flow_local({})
        assert result["model"] == backup

    def test_pop_old_api_keys_on_success(self, tmp_prefs, monkeypatch):
        primary = onboard.RECOMMENDED_MODELS[0][0]
        monkeypatch.setattr(onboard, "_check_ollama_installed", lambda: (True, "0.1"))
        monkeypatch.setattr(onboard, "_list_ollama_models", lambda: [primary])
        prefs = {"api_key": "abc", "api_provider": "anthropic"}
        onboard._flow_local(prefs)
        assert "api_key" not in prefs
        assert "api_provider" not in prefs

    def test_neither_installed_user_pulls_yes_success(self, tmp_prefs, monkeypatch):
        primary = onboard.RECOMMENDED_MODELS[0][0]
        monkeypatch.setattr(onboard, "_check_ollama_installed", lambda: (True, "0.1"))
        monkeypatch.setattr(onboard, "_list_ollama_models", lambda: [])
        monkeypatch.setattr(onboard, "_find_recommended_model", lambda m: None)
        monkeypatch.setattr(onboard.Prompt, "ask", lambda *a, **k: "y")
        monkeypatch.setattr(onboard, "_pull_ollama_model", lambda m: True)
        result = onboard._flow_local({})
        assert result["model"] == primary

    def test_neither_installed_pull_fails(self, tmp_prefs, monkeypatch):
        monkeypatch.setattr(onboard, "_check_ollama_installed", lambda: (True, "0.1"))
        monkeypatch.setattr(onboard, "_list_ollama_models", lambda: [])
        monkeypatch.setattr(onboard, "_find_recommended_model", lambda m: None)
        monkeypatch.setattr(onboard.Prompt, "ask", lambda *a, **k: "y")
        monkeypatch.setattr(onboard, "_pull_ollama_model", lambda m: False)
        assert onboard._flow_local({}) is None

    def test_neither_installed_user_says_no(self, tmp_prefs, monkeypatch):
        monkeypatch.setattr(onboard, "_check_ollama_installed", lambda: (True, "0.1"))
        monkeypatch.setattr(onboard, "_list_ollama_models", lambda: [])
        monkeypatch.setattr(onboard, "_find_recommended_model", lambda m: None)
        monkeypatch.setattr(onboard.Prompt, "ask", lambda *a, **k: "n")
        assert onboard._flow_local({}) is None

    def test_neither_recommended_but_other_model_present(self, tmp_prefs, monkeypatch):
        # has_primary/has_backup both False but _find_recommended_model returns one
        # _find_recommended_model only returns from RECOMMENDED_MODELS, so we mock it
        monkeypatch.setattr(onboard, "_check_ollama_installed", lambda: (True, "0.1"))
        monkeypatch.setattr(onboard, "_list_ollama_models", lambda: ["llama2"])
        monkeypatch.setattr(onboard, "_find_recommended_model", lambda m: "llama2")
        result = onboard._flow_local({})
        assert result["model"] == "llama2"


# ---------------------------------------------------------------------------
# Cloud flow
# ---------------------------------------------------------------------------

class TestFlowCloud:
    def test_anthropic_with_env_key_use(self, tmp_prefs, clean_env):
        clean_env.setenv("ANTHROPIC_API_KEY", "sk-ant-existingkey1234567")
        responses = iter(["1", "y"])
        with patch.object(onboard.Prompt, "ask", side_effect=lambda *a, **k: next(responses)):
            result = onboard._flow_cloud({})
        assert result["provider"] == "anthropic"
        assert result["api_key_source"] == "environment"

    def test_openai_no_env_prompts_for_key(self, tmp_prefs, clean_env):
        responses = iter(["2", "sk-openai-key-xyz"])
        with patch.object(onboard.Prompt, "ask", side_effect=lambda *a, **k: next(responses)):
            result = onboard._flow_cloud({})
        assert result["provider"] == "openai"
        assert "OPENAI_API_KEY" in __import__("os").environ

    def test_gemini_no_env_prompts(self, tmp_prefs, clean_env):
        responses = iter(["3", "gemini-secret"])
        with patch.object(onboard.Prompt, "ask", side_effect=lambda *a, **k: next(responses)):
            result = onboard._flow_cloud({})
        assert result["provider"] == "gemini"
        assert result["model"] == "gemini-2.0-flash"

    def test_env_key_decline_falls_through_to_prompt(self, tmp_prefs, clean_env):
        clean_env.setenv("ANTHROPIC_API_KEY", "sk-ant-old-1234567")
        responses = iter(["1", "n", "sk-ant-newkey"])
        with patch.object(onboard.Prompt, "ask", side_effect=lambda *a, **k: next(responses)):
            result = onboard._flow_cloud({})
        assert result["provider"] == "anthropic"
        prefs = onboard._load_prefs()
        assert "api_key" in prefs

    def test_blank_key_aborts(self, tmp_prefs, clean_env):
        responses = iter(["1", "   "])
        with patch.object(onboard.Prompt, "ask", side_effect=lambda *a, **k: next(responses)):
            result = onboard._flow_cloud({})
        assert result is None

    def test_key_stored_obfuscated(self, tmp_prefs, clean_env):
        responses = iter(["1", "sk-ant-test123"])
        with patch.object(onboard.Prompt, "ask", side_effect=lambda *a, **k: next(responses)):
            onboard._flow_cloud({})
        prefs = onboard._load_prefs()
        assert prefs["api_key"] != "sk-ant-test123"
        assert onboard._deobfuscate_key(prefs["api_key"]) == "sk-ant-test123"


# ---------------------------------------------------------------------------
# Cloud returning flow
# ---------------------------------------------------------------------------

class TestFlowCloudReturning:
    def test_env_key_present(self, tmp_prefs, clean_env):
        clean_env.setenv("ANTHROPIC_API_KEY", "k")
        prefs = {"api_provider": "anthropic", "model": "claude-sonnet-4-6"}
        result = onboard._flow_cloud_returning(prefs)
        assert result == {"provider": "anthropic", "model": "claude-sonnet-4-6"}

    def test_stored_key_restored_to_env(self, tmp_prefs, clean_env):
        import os as _os
        prefs = {
            "api_provider": "openai",
            "model": "gpt-4o",
            "api_key": onboard._obfuscate_key("sk-stored"),
        }
        result = onboard._flow_cloud_returning(prefs)
        assert result["provider"] == "openai"
        assert _os.environ["OPENAI_API_KEY"] == "sk-stored"

    def test_no_key_falls_back_to_flow_cloud(self, tmp_prefs, clean_env, monkeypatch):
        prefs = {"api_provider": "anthropic", "model": "claude-sonnet-4-6"}
        called = {}
        def fake_flow(p):
            called["yes"] = True
            return {"provider": "anthropic", "model": "claude-sonnet-4-6"}
        monkeypatch.setattr(onboard, "_flow_cloud", fake_flow)
        result = onboard._flow_cloud_returning(prefs)
        assert called.get("yes")
        assert result["provider"] == "anthropic"

    def test_unknown_provider_no_env_var_map(self, tmp_prefs, clean_env, monkeypatch):
        # provider not in env_var_map → env_var = ""
        prefs = {"provider": "unknown"}
        monkeypatch.setattr(onboard, "_flow_cloud", lambda p: None)
        result = onboard._flow_cloud_returning(prefs)
        assert result is None

    def test_stored_key_deobfuscate_fails(self, tmp_prefs, clean_env, monkeypatch):
        # api_key present but deobfuscate returns "" → falls through to _flow_cloud
        prefs = {"api_provider": "anthropic", "model": "x", "api_key": "!!!bad!!!"}
        monkeypatch.setattr(onboard, "_flow_cloud", lambda p: {"provider": "anthropic", "model": "x"})
        result = onboard._flow_cloud_returning(prefs)
        assert result == {"provider": "anthropic", "model": "x"}


# ---------------------------------------------------------------------------
# First-time and returning user flows
# ---------------------------------------------------------------------------

class TestFirstTimeFlow:
    def test_choice_a_local(self, tmp_prefs, monkeypatch):
        monkeypatch.setattr(onboard.Prompt, "ask", lambda *a, **k: "a")
        monkeypatch.setattr(onboard, "_flow_local", lambda p: {"provider": "ollama"})
        result = onboard._first_time_flow({}, "concept")
        assert result == {"provider": "ollama"}

    def test_choice_b_cloud(self, tmp_prefs, monkeypatch):
        monkeypatch.setattr(onboard.Prompt, "ask", lambda *a, **k: "b")
        monkeypatch.setattr(onboard, "_flow_cloud", lambda p: {"provider": "anthropic"})
        result = onboard._first_time_flow({}, "concept")
        assert result == {"provider": "anthropic"}


class TestReturningUserFlow:
    def test_a_reuse_ollama(self, tmp_prefs, monkeypatch):
        monkeypatch.setattr(onboard.Prompt, "ask", lambda *a, **k: "a")
        prefs = {"provider": "ollama", "model": "gpt-oss:20b"}
        result = onboard._returning_user_flow(prefs, "c")
        assert result == {"provider": "ollama", "model": "gpt-oss:20b"}

    def test_a_reuse_cloud(self, tmp_prefs, monkeypatch):
        monkeypatch.setattr(onboard.Prompt, "ask", lambda *a, **k: "a")
        monkeypatch.setattr(onboard, "_flow_cloud_returning",
                            lambda p: {"provider": "anthropic", "model": "x"})
        prefs = {"provider": "anthropic", "api_provider": "anthropic", "model": "x"}
        result = onboard._returning_user_flow(prefs, "c")
        assert result["provider"] == "anthropic"

    def test_b_switch_from_ollama_to_cloud(self, tmp_prefs, monkeypatch):
        monkeypatch.setattr(onboard.Prompt, "ask", lambda *a, **k: "b")
        monkeypatch.setattr(onboard, "_flow_cloud", lambda p: {"provider": "anthropic"})
        prefs = {"provider": "ollama", "model": "x"}
        result = onboard._returning_user_flow(prefs, "c")
        assert result["provider"] == "anthropic"

    def test_b_switch_from_cloud_to_local(self, tmp_prefs, monkeypatch):
        monkeypatch.setattr(onboard.Prompt, "ask", lambda *a, **k: "b")
        monkeypatch.setattr(onboard, "_flow_local", lambda p: {"provider": "ollama"})
        prefs = {"provider": "anthropic", "model": "x"}
        result = onboard._returning_user_flow(prefs, "c")
        assert result["provider"] == "ollama"

    def test_c_full_reselection(self, tmp_prefs, monkeypatch):
        monkeypatch.setattr(onboard.Prompt, "ask", lambda *a, **k: "c")
        monkeypatch.setattr(onboard, "_first_time_flow",
                            lambda p, c: {"provider": "ollama"})
        prefs = {"provider": "anthropic", "model": "x"}
        result = onboard._returning_user_flow(prefs, "concept")
        assert result == {"provider": "ollama"}


# ---------------------------------------------------------------------------
# Main wizard entry + _init_and_run
# ---------------------------------------------------------------------------

def _stub_pipeline_modules(monkeypatch):
    """Install stub pipeline modules so _init_and_run runs without real deps."""
    from productteam import config as _config_mod
    from productteam import models as _models_mod
    from productteam.providers import factory as _factory_mod
    from productteam import scaffold as _scaffold_mod
    from productteam import supervisor as _sup_mod
    from productteam import errors as _err_mod

    monkeypatch.setattr(_scaffold_mod, "init_project", lambda t: None)

    fake_cfg = MagicMock()
    fake_cfg.pipeline = MagicMock(api_base=None)
    fake_cfg.gates = MagicMock()
    # MagicMock(name="x") sets the mock's name, not an attribute. Use a plain object.
    class _Proj:
        name = ""
    fake_cfg.project = _Proj()
    monkeypatch.setattr(_config_mod, "load_config", lambda p: fake_cfg)
    monkeypatch.setattr(_config_mod, "save_config", lambda c, p: None)
    monkeypatch.setattr(_models_mod, "ProductTeamConfig", lambda: fake_cfg)

    monkeypatch.setattr(_factory_mod, "get_provider",
                        lambda **kw: MagicMock())

    fake_result = MagicMock(status="complete")
    fake_result.token_summary = lambda model_id: {
        "total_input_tokens": 100,
        "total_output_tokens": 50,
        "est_cost_usd": 0.01,
    }
    fake_supervisor = MagicMock()
    fake_supervisor.run = MagicMock(return_value=_async_value(fake_result))
    monkeypatch.setattr(_sup_mod, "Supervisor", lambda **kw: fake_supervisor)

    return fake_cfg, fake_result, fake_supervisor, _err_mod


def _async_value(v):
    async def coro(*a, **k):
        return v
    return coro()


class TestInitAndRun:
    def test_complete_pipeline(self, tmp_path, monkeypatch):
        fake_cfg, fake_result, fake_sup, _ = _stub_pipeline_modules(monkeypatch)
        # pt_dir doesn't exist → init_project called; config_path doesn't exist → use default
        onboard._init_and_run(tmp_path, "build something cool", {"provider": "ollama", "model": "m"})
        # auto-tune for ollama
        assert fake_cfg.pipeline.stage_timeout_seconds == 3600

    def test_existing_config_loaded(self, tmp_path, monkeypatch):
        fake_cfg, _, _, _ = _stub_pipeline_modules(monkeypatch)
        (tmp_path / ".productteam").mkdir()
        (tmp_path / "productteam.toml").write_text("# stub", encoding="utf-8")
        onboard._init_and_run(tmp_path, "concept words here", {"provider": "anthropic", "model": "x"})
        # cloud → no auto-tune; project name set from concept
        assert fake_cfg.project.name == "concept-words-here"

    def test_provider_factory_error(self, tmp_path, monkeypatch):
        _stub_pipeline_modules(monkeypatch)
        from productteam.providers import factory as _factory_mod
        def boom(**kw): raise RuntimeError("no provider")
        monkeypatch.setattr(_factory_mod, "get_provider", boom)
        # should print error and return cleanly
        onboard._init_and_run(tmp_path, "x", {"provider": "ollama", "model": "m"})

    def test_budget_exceeded(self, tmp_path, monkeypatch):
        _stub_pipeline_modules(monkeypatch)
        from productteam import supervisor as _sup_mod
        from productteam import errors as _err_mod

        fake_supervisor = MagicMock()
        async def boom(**kw):
            raise _err_mod.BudgetExceededError(10.0, 5.0, "test")
        fake_supervisor.run = boom
        monkeypatch.setattr(_sup_mod, "Supervisor", lambda **kw: fake_supervisor)
        onboard._init_and_run(tmp_path, "x", {"provider": "ollama", "model": "m"})

    def test_keyboard_interrupt(self, tmp_path, monkeypatch):
        _stub_pipeline_modules(monkeypatch)
        from productteam import supervisor as _sup_mod
        fake_supervisor = MagicMock()
        async def boom(**kw):
            raise KeyboardInterrupt()
        fake_supervisor.run = boom
        monkeypatch.setattr(_sup_mod, "Supervisor", lambda **kw: fake_supervisor)
        onboard._init_and_run(tmp_path, "x", {"provider": "ollama", "model": "m"})

    @pytest.mark.parametrize("status", ["partial", "stuck", "failed"])
    def test_non_complete_statuses(self, tmp_path, monkeypatch, status):
        fake_cfg, fake_result, fake_sup, _ = _stub_pipeline_modules(monkeypatch)
        from productteam import supervisor as _sup_mod
        fake_result.status = status
        fake_supervisor = MagicMock()
        fake_supervisor.run = MagicMock(return_value=_async_value(fake_result))
        monkeypatch.setattr(_sup_mod, "Supervisor", lambda **kw: fake_supervisor)
        onboard._init_and_run(tmp_path, "x", {"provider": "ollama", "model": "m"})

    def test_zero_tokens_skips_summary(self, tmp_path, monkeypatch):
        fake_cfg, fake_result, fake_sup, _ = _stub_pipeline_modules(monkeypatch)
        from productteam import supervisor as _sup_mod
        fake_result.token_summary = lambda model_id: {
            "total_input_tokens": 0, "total_output_tokens": 0, "est_cost_usd": None
        }
        fake_supervisor = MagicMock()
        fake_supervisor.run = MagicMock(return_value=_async_value(fake_result))
        monkeypatch.setattr(_sup_mod, "Supervisor", lambda **kw: fake_supervisor)
        onboard._init_and_run(tmp_path, "x", {"provider": "anthropic", "model": "m"})

    def test_no_cost_displayed_when_none(self, tmp_path, monkeypatch):
        fake_cfg, fake_result, _, _ = _stub_pipeline_modules(monkeypatch)
        from productteam import supervisor as _sup_mod
        fake_result.token_summary = lambda model_id: {
            "total_input_tokens": 100, "total_output_tokens": 50, "est_cost_usd": None
        }
        fake_supervisor = MagicMock()
        fake_supervisor.run = MagicMock(return_value=_async_value(fake_result))
        monkeypatch.setattr(_sup_mod, "Supervisor", lambda **kw: fake_supervisor)
        onboard._init_and_run(tmp_path, "x", {"provider": "anthropic", "model": "m"})


class TestRunWizard:
    def test_first_time_user_aborts(self, tmp_prefs, tmp_path, monkeypatch):
        monkeypatch.setattr(onboard, "_get_concept", lambda: "my idea")
        monkeypatch.setattr(onboard, "_first_time_flow", lambda p, c: None)
        # Should not call _init_and_run
        called = {}
        monkeypatch.setattr(onboard, "_init_and_run",
                            lambda *a, **k: called.setdefault("yes", True))
        onboard.run_wizard(directory=tmp_path)
        assert "yes" not in called

    def test_returning_user_runs_pipeline(self, tmp_prefs, tmp_path, monkeypatch):
        tmp_prefs.parent.mkdir(parents=True, exist_ok=True)
        tmp_prefs.write_text(json.dumps({"provider": "ollama", "model": "m"}), encoding="utf-8")
        monkeypatch.setattr(onboard, "_get_concept", lambda: "idea")
        monkeypatch.setattr(onboard, "_returning_user_flow",
                            lambda p, c: {"provider": "ollama", "model": "m"})
        called = {}
        def fake_init(target, concept, config):
            called["target"] = target
            called["concept"] = concept
            called["config"] = config
        monkeypatch.setattr(onboard, "_init_and_run", fake_init)
        onboard.run_wizard(directory=tmp_path)
        assert called["concept"] == "idea"
        assert called["config"] == {"provider": "ollama", "model": "m"}

    def test_default_directory_is_cwd(self, tmp_prefs, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        monkeypatch.setattr(onboard, "_get_concept", lambda: "idea")
        monkeypatch.setattr(onboard, "_first_time_flow", lambda p, c: None)
        called = {}
        monkeypatch.setattr(onboard, "_init_and_run",
                            lambda *a, **k: called.setdefault("yes", True))
        onboard.run_wizard()  # no directory arg
        # First-time flow returned None, init not called
        assert "yes" not in called
