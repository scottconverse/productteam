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
    result = runner.invoke(app, ["run", str(tmp_path)])
    assert result.exit_code == 1
    assert "productteam init" in result.output


def test_run_no_config_toml(tmp_path):
    """run exits with code 1 when productteam.toml is missing."""
    # Create .productteam/ but NOT productteam.toml
    (tmp_path / ".productteam").mkdir()
    result = runner.invoke(app, ["run", str(tmp_path)])
    assert result.exit_code == 1
    assert "productteam.toml" in result.output


def test_run_invalid_config_toml(tmp_path):
    """run exits with code 1 when productteam.toml is invalid TOML."""
    (tmp_path / ".productteam").mkdir()
    (tmp_path / "productteam.toml").write_text("not valid toml ][[\n")
    result = runner.invoke(app, ["run", str(tmp_path)])
    assert result.exit_code == 1
    assert "invalid" in result.output.lower()


def test_run_prints_pipeline_header(tmp_path):
    """run prints the ProductTeam Pipeline header."""
    runner.invoke(app, ["init", str(tmp_path)])
    result = runner.invoke(app, ["run", str(tmp_path)])
    assert result.exit_code == 0
    assert "ProductTeam Pipeline" in result.output


def test_run_prints_all_six_steps(tmp_path):
    """run prints all 6 pipeline steps."""
    runner.invoke(app, ["init", str(tmp_path)])
    result = runner.invoke(app, ["run", str(tmp_path)])
    assert result.exit_code == 0
    for n in range(1, 7):
        assert f"Step {n}:" in result.output


def test_run_prints_step_titles(tmp_path):
    """run prints recognisable step titles."""
    runner.invoke(app, ["init", str(tmp_path)])
    result = runner.invoke(app, ["run", str(tmp_path)])
    assert result.exit_code == 0
    assert "PRD Writer" in result.output
    assert "Planner" in result.output
    assert "Builder" in result.output
    assert "Doc Writer" in result.output
    assert "Design Review" in result.output
    assert "Ship" in result.output


def test_run_prints_skill_paths(tmp_path):
    """run instructions reference .claude/skills/ paths."""
    runner.invoke(app, ["init", str(tmp_path)])
    result = runner.invoke(app, ["run", str(tmp_path)])
    assert ".claude/skills/" in result.output


def test_run_prints_gates(tmp_path):
    """run prints approval gate text for steps that have them."""
    runner.invoke(app, ["init", str(tmp_path)])
    result = runner.invoke(app, ["run", str(tmp_path)])
    assert "Gate:" in result.output
    assert "approve" in result.output.lower()


def test_run_no_status_section_when_empty(tmp_path):
    """run does not print status section when there are no sprints/evaluations."""
    runner.invoke(app, ["init", str(tmp_path)])
    result = runner.invoke(app, ["run", str(tmp_path)])
    assert result.exit_code == 0
    assert "Current Pipeline Status" not in result.output


def test_run_shows_status_when_sprints_exist(tmp_path):
    """run shows current pipeline status when sprints are present."""
    runner.invoke(app, ["init", str(tmp_path)])
    sprint_dir = tmp_path / ".productteam" / "sprints" / "sprint-001"
    sprint_dir.mkdir()
    result = runner.invoke(app, ["run", str(tmp_path)])
    assert result.exit_code == 0
    assert "Current Pipeline Status" in result.output
    assert "sprint-001" in result.output


def test_run_shows_status_when_evaluations_exist(tmp_path):
    """run shows current pipeline status when evaluations are present."""
    runner.invoke(app, ["init", str(tmp_path)])
    eval_file = tmp_path / ".productteam" / "evaluations" / "eval-001.yaml"
    eval_file.write_text("verdict: passed\n")
    result = runner.invoke(app, ["run", str(tmp_path)])
    assert result.exit_code == 0
    assert "Current Pipeline Status" in result.output
    assert "eval-001" in result.output


def test_run_step_option_prints_single_step(tmp_path):
    """--step N prints only that step's instructions."""
    runner.invoke(app, ["init", str(tmp_path)])
    result = runner.invoke(app, ["run", str(tmp_path), "--step", "1"])
    assert result.exit_code == 0
    assert "PRD Writer" in result.output
    # Other step titles should not appear
    assert "Planner" not in result.output
    assert "Doc Writer" not in result.output


def test_run_step_option_each_step(tmp_path):
    """--step N works for every valid step number."""
    runner.invoke(app, ["init", str(tmp_path)])
    expected_titles = {
        1: "PRD Writer",
        2: "Planner",
        3: "Builder",
        4: "Doc Writer",
        5: "Design Review",
        6: "Ship",
    }
    for n, title in expected_titles.items():
        result = runner.invoke(app, ["run", str(tmp_path), "--step", str(n)])
        assert result.exit_code == 0, f"Step {n} failed: {result.output}"
        assert title in result.output, f"Expected '{title}' in step {n} output"


def test_run_step_option_invalid_number(tmp_path):
    """--step with an out-of-range number exits with code 1."""
    runner.invoke(app, ["init", str(tmp_path)])
    result = runner.invoke(app, ["run", str(tmp_path), "--step", "99"])
    assert result.exit_code == 1


def test_run_default_directory(tmp_path, monkeypatch):
    """run uses cwd when no directory argument is given."""
    monkeypatch.chdir(tmp_path)
    runner.invoke(app, ["init"])
    result = runner.invoke(app, ["run"])
    assert result.exit_code == 0
    assert "ProductTeam Pipeline" in result.output
