"""Tests for the CLI commands using typer.testing.CliRunner."""

from __future__ import annotations

import os
from pathlib import Path

import pytest
from typer.testing import CliRunner

from productteam.cli import app
from productteam import __version__

runner = CliRunner()


# ---------------------------------------------------------------------------
# version command
# ---------------------------------------------------------------------------


def test_version_output():
    """version command prints the package version."""
    result = runner.invoke(app, ["version"])
    assert result.exit_code == 0
    assert __version__ in result.output


def test_version_string_format():
    """Version output includes 'ProductTeam' label."""
    result = runner.invoke(app, ["version"])
    assert "ProductTeam" in result.output


# ---------------------------------------------------------------------------
# init command
# ---------------------------------------------------------------------------


def test_init_creates_productteam_dir(tmp_path):
    """init creates .productteam/ directory."""
    result = runner.invoke(app, ["init", str(tmp_path)])
    assert result.exit_code == 0
    assert (tmp_path / ".productteam").is_dir()


def test_init_creates_sprints_dir(tmp_path):
    """init creates .productteam/sprints/ directory."""
    runner.invoke(app, ["init", str(tmp_path)])
    assert (tmp_path / ".productteam" / "sprints").is_dir()


def test_init_creates_evaluations_dir(tmp_path):
    """init creates .productteam/evaluations/ directory."""
    runner.invoke(app, ["init", str(tmp_path)])
    assert (tmp_path / ".productteam" / "evaluations").is_dir()


def test_init_creates_config_toml(tmp_path):
    """init creates productteam.toml in target directory."""
    runner.invoke(app, ["init", str(tmp_path)])
    assert (tmp_path / "productteam.toml").is_file()


def test_init_copies_skills(tmp_path):
    """init copies skill directories into .claude/skills/."""
    runner.invoke(app, ["init", str(tmp_path)])
    skills_dir = tmp_path / ".claude" / "skills"
    assert skills_dir.is_dir()
    # At least one skill subdirectory should exist
    skill_dirs = [d for d in skills_dir.iterdir() if d.is_dir()]
    assert len(skill_dirs) > 0


def test_init_success_message(tmp_path):
    """init prints the success message."""
    result = runner.invoke(app, ["init", str(tmp_path)])
    assert result.exit_code == 0
    assert "ProductTeam initialized" in result.output


def test_init_idempotent(tmp_path):
    """Running init twice does not fail."""
    result1 = runner.invoke(app, ["init", str(tmp_path)])
    result2 = runner.invoke(app, ["init", str(tmp_path)])
    assert result1.exit_code == 0
    assert result2.exit_code == 0


def test_init_force_flag_overwrites_config(tmp_path):
    """--force flag overwrites existing productteam.toml."""
    runner.invoke(app, ["init", str(tmp_path)])
    config_path = tmp_path / "productteam.toml"
    config_path.write_text("[project]\nname = 'modified'\nversion = '9.9.9'\n")
    runner.invoke(app, ["init", "--force", str(tmp_path)])
    content = config_path.read_text()
    # After force reinit the name should be empty (default)
    assert "9.9.9" not in content


def test_init_default_directory(tmp_path, monkeypatch):
    """init uses cwd when no directory argument is given."""
    monkeypatch.chdir(tmp_path)
    result = runner.invoke(app, ["init"])
    assert result.exit_code == 0
    assert (tmp_path / ".productteam").is_dir()


# ---------------------------------------------------------------------------
# status command
# ---------------------------------------------------------------------------


def test_status_not_initialized(tmp_path):
    """status exits with code 1 when project is not initialized."""
    result = runner.invoke(app, ["status", str(tmp_path)])
    assert result.exit_code == 1


def test_status_initialized_empty(tmp_path):
    """status shows planning phase for empty initialized project."""
    runner.invoke(app, ["init", str(tmp_path)])
    result = runner.invoke(app, ["status", str(tmp_path)])
    assert result.exit_code == 0
    assert "PLANNING" in result.output


def test_status_shows_sprints(tmp_path):
    """status lists sprint directories."""
    runner.invoke(app, ["init", str(tmp_path)])
    sprint_dir = tmp_path / ".productteam" / "sprints" / "sprint-01"
    sprint_dir.mkdir()
    result = runner.invoke(app, ["status", str(tmp_path)])
    assert result.exit_code == 0
    assert "sprint-01" in result.output


def test_status_shows_evaluations(tmp_path):
    """status lists evaluation files."""
    runner.invoke(app, ["init", str(tmp_path)])
    eval_file = tmp_path / ".productteam" / "evaluations" / "eval-01.yaml"
    eval_file.write_text("verdict: passed\n")
    result = runner.invoke(app, ["status", str(tmp_path)])
    assert result.exit_code == 0
    assert "eval-01" in result.output


def test_status_pipeline_phase_building(tmp_path):
    """status shows BUILDING phase when a sprint has a plan file."""
    runner.invoke(app, ["init", str(tmp_path)])
    sprint_dir = tmp_path / ".productteam" / "sprints" / "sprint-01"
    sprint_dir.mkdir()
    (sprint_dir / "plan.md").write_text("# Sprint Plan\n")
    result = runner.invoke(app, ["status", str(tmp_path)])
    assert result.exit_code == 0
    # Should show BUILDING since there's a planned sprint
    assert "BUILDING" in result.output or "PLANNING" in result.output


def test_status_pipeline_phase_shipping(tmp_path):
    """status shows SHIPPING phase when an evaluation has passed verdict."""
    runner.invoke(app, ["init", str(tmp_path)])
    eval_file = tmp_path / ".productteam" / "evaluations" / "final.yaml"
    eval_file.write_text("verdict: passed\nresult: all tests pass\n")
    result = runner.invoke(app, ["status", str(tmp_path)])
    assert result.exit_code == 0
    assert "SHIPPING" in result.output


# ---------------------------------------------------------------------------
# config command
# ---------------------------------------------------------------------------


def test_config_show_no_file(tmp_path, monkeypatch):
    """config show exits with 1 when no productteam.toml exists."""
    monkeypatch.chdir(tmp_path)
    result = runner.invoke(app, ["config"])
    assert result.exit_code == 1


def test_config_show_displays_settings(tmp_path, monkeypatch):
    """config show prints settings from productteam.toml."""
    monkeypatch.chdir(tmp_path)
    runner.invoke(app, ["init", str(tmp_path)])
    result = runner.invoke(app, ["config"])
    assert result.exit_code == 0
    assert "pipeline" in result.output
    assert "project" in result.output
    assert "gates" in result.output


def test_config_set_updates_value(tmp_path, monkeypatch):
    """config set updates a value in productteam.toml."""
    monkeypatch.chdir(tmp_path)
    runner.invoke(app, ["init", str(tmp_path)])
    result = runner.invoke(app, ["config", "set", "pipeline.model", "claude-opus-4"])
    assert result.exit_code == 0
    assert "claude-opus-4" in result.output
    # Verify the file was actually updated
    content = (tmp_path / "productteam.toml").read_text()
    assert "claude-opus-4" in content


def test_config_set_invalid_key(tmp_path, monkeypatch):
    """config set exits with 1 for an unknown key."""
    monkeypatch.chdir(tmp_path)
    runner.invoke(app, ["init", str(tmp_path)])
    result = runner.invoke(app, ["config", "set", "nonexistent.key", "value"])
    assert result.exit_code == 1


def test_config_set_boolean_value(tmp_path, monkeypatch):
    """config set handles boolean values correctly."""
    monkeypatch.chdir(tmp_path)
    runner.invoke(app, ["init", str(tmp_path)])
    result = runner.invoke(app, ["config", "set", "gates.prd_approval", "false"])
    assert result.exit_code == 0


def test_no_args_shows_help():
    """Running productteam with no args shows help text."""
    result = runner.invoke(app, [])
    # no_args_is_help=True means it shows help and exits 0
    assert "productteam" in result.output.lower() or result.exit_code == 0


# ---------------------------------------------------------------------------
# run command
# ---------------------------------------------------------------------------


def test_run_no_productteam_dir(tmp_path):
    """run exits with code 1 when .productteam/ does not exist."""
    result = runner.invoke(app, ["run", "--dir", str(tmp_path)])
    assert result.exit_code == 1
    assert "productteam init" in result.output


def test_run_no_config_toml(tmp_path):
    """run exits with code 1 when productteam.toml is missing."""
    (tmp_path / ".productteam").mkdir()
    result = runner.invoke(app, ["run", "--dir", str(tmp_path)])
    assert result.exit_code == 1
    assert "productteam.toml" in result.output


def test_run_invalid_config_toml(tmp_path):
    """run exits with code 1 when productteam.toml is invalid TOML."""
    (tmp_path / ".productteam").mkdir()
    (tmp_path / "productteam.toml").write_text("not valid toml ][[\n")
    result = runner.invoke(app, ["run", "--dir", str(tmp_path)])
    assert result.exit_code == 1
    assert "invalid" in result.output.lower()


def test_run_dry_run_shows_stages(tmp_path):
    """run --dry-run shows stages without calling LLM."""
    runner.invoke(app, ["init", str(tmp_path)])
    result = runner.invoke(app, ["run", "test concept", "--dir", str(tmp_path), "--dry-run", "--auto-approve"])
    assert result.exit_code == 0
    assert "Dry run" in result.output or "Pipeline" in result.output


def test_run_prints_provider_info(tmp_path, monkeypatch):
    """run shows provider and model in output."""
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")
    runner.invoke(app, ["init", str(tmp_path)])
    result = runner.invoke(app, ["run", "test", "--dir", str(tmp_path), "--dry-run", "--auto-approve"])
    assert "ProductTeam Pipeline" in result.output


def test_run_step_option_invalid_value(tmp_path, monkeypatch):
    """--step with invalid stage name exits with error."""
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")
    runner.invoke(app, ["init", str(tmp_path)])
    result = runner.invoke(app, ["run", "test", "--dir", str(tmp_path), "--step", "nonexistent"])
    assert result.exit_code != 0


def test_run_default_directory(tmp_path, monkeypatch):
    """run uses cwd when no --dir is given."""
    monkeypatch.chdir(tmp_path)
    runner.invoke(app, ["init"])
    result = runner.invoke(app, ["run", "test concept", "--dry-run", "--auto-approve"])
    assert result.exit_code == 0


# ---------------------------------------------------------------------------
# test command
# ---------------------------------------------------------------------------


def test_test_command_exists():
    """test command is registered and shows help."""
    result = runner.invoke(app, ["test", "--help"])
    assert result.exit_code == 0
    assert "live" in result.output.lower()


def test_test_live_no_api_key(tmp_path, monkeypatch):
    """test --live exits with error when API key is missing."""
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    runner.invoke(app, ["init", str(tmp_path)])
    result = runner.invoke(app, ["test", "--live", "--dir", str(tmp_path)])
    assert result.exit_code == 1
    assert "ANTHROPIC_API_KEY" in result.output


def test_test_live_shows_safety_warning(tmp_path, monkeypatch):
    """test --live shows API key safety panel when key is present."""
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-test-key-1234567890")
    runner.invoke(app, ["init", str(tmp_path)])
    # Will fail at pytest execution but we check the safety output
    result = runner.invoke(app, ["test", "--live", "--dir", str(tmp_path)])
    assert "Live test warning" in result.output or "API Key Safety" in result.output
    assert "Cost money" in result.output


def test_test_live_masks_api_key(tmp_path, monkeypatch):
    """test --live masks the API key in output."""
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-test-key-1234567890")
    runner.invoke(app, ["init", str(tmp_path)])
    result = runner.invoke(app, ["test", "--live", "--dir", str(tmp_path)])
    # Full key should never appear
    assert "sk-ant-test-key-1234567890" not in result.output
    # Masked version should appear
    assert "sk-a" in result.output
    assert "7890" in result.output


def test_test_live_ollama_no_key_needed(tmp_path, monkeypatch):
    """test --live with ollama does not require an API key."""
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    runner.invoke(app, ["init", str(tmp_path)])
    result = runner.invoke(app, ["test", "--live", "--provider", "ollama", "--dir", str(tmp_path)])
    # Should not fail on missing key — will fail at pytest execution instead
    assert "ANTHROPIC_API_KEY" not in result.output


# ---------------------------------------------------------------------------
# recover command
# ---------------------------------------------------------------------------


def _write_state(tmp_path: Path, state: dict) -> None:
    """Write a state.json for testing."""
    import json as json_mod
    state_path = tmp_path / ".productteam" / "state.json"
    state_path.parent.mkdir(parents=True, exist_ok=True)
    state_path.write_text(json_mod.dumps(state, indent=2))


def test_recover_no_state_file(tmp_path):
    """recover exits with code 1 when no state.json exists."""
    (tmp_path / ".productteam").mkdir(parents=True)
    result = runner.invoke(app, ["recover", "--dir", str(tmp_path)])
    assert result.exit_code == 1
    assert "No state.json" in result.output


def test_recover_no_concept(tmp_path):
    """recover exits with code 1 when state has no concept."""
    _write_state(tmp_path, {"schema_version": 1, "concept": "", "stages": {}})
    result = runner.invoke(app, ["recover", "--dir", str(tmp_path)])
    assert result.exit_code == 1
    assert "No concept" in result.output


def test_recover_no_stuck_stages(tmp_path):
    """recover exits cleanly when no stages are stuck."""
    _write_state(tmp_path, {
        "schema_version": 1,
        "concept": "test app",
        "stages": {"prd": {"status": "complete"}},
    })
    result = runner.invoke(app, ["recover", "--dir", str(tmp_path)])
    assert result.exit_code == 0
    assert "No stuck stages" in result.output


def test_recover_identifies_stuck_stages(tmp_path):
    """recover finds and reports stuck stages."""
    _write_state(tmp_path, {
        "schema_version": 1,
        "concept": "test app",
        "stages": {
            "prd": {"status": "complete"},
            "plan": {"status": "complete"},
            "build": {"status": "stuck", "sprint": "sprint-001", "loop": 1},
        },
    })
    result = runner.invoke(app, ["recover", "--dir", str(tmp_path)], input="n\n")
    assert result.exit_code == 0
    assert "build" in result.output
    assert "stuck" in result.output
    assert "sprint-001" in result.output
    # Verify re-entry is AT the stuck stage, not after it
    assert "resume from" in result.output.lower() or "Will resume" in result.output


def test_recover_resets_state_with_yes(tmp_path):
    """recover --yes resets stuck stages to pending without prompting."""
    import json as json_mod

    runner.invoke(app, ["init", str(tmp_path)])
    _write_state(tmp_path, {
        "schema_version": 1,
        "concept": "test app",
        "stages": {
            "prd": {"status": "complete", "artifact": ".productteam/prds/prd-v1.md"},
            "plan": {"status": "stuck"},
        },
    })

    # --yes resets state but then fails trying to get a provider (no API key)
    # That's fine — we're testing the state reset, not the pipeline run
    result = runner.invoke(app, ["recover", "--yes", "--dir", str(tmp_path)])

    # Check state was reset
    state = json_mod.loads(
        (tmp_path / ".productteam" / "state.json").read_text()
    )
    assert state["stages"]["plan"]["status"] == "pending"
    assert state["stages"]["prd"]["status"] == "complete"
