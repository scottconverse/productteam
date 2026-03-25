"""Tests for scaffold.py — directory creation, skill copying, toml generation."""

from __future__ import annotations

from pathlib import Path

import pytest

from productteam.scaffold import (
    _determine_pipeline_phase,
    _get_package_data_dir,
    _read_verdict,
    get_sprint_status,
    init_project,
    read_project_state,
)


# ---------------------------------------------------------------------------
# _get_package_data_dir
# ---------------------------------------------------------------------------


def test_get_package_data_dir_returns_path():
    """_get_package_data_dir returns a Path to a directory with skills/."""
    data_dir = _get_package_data_dir()
    assert isinstance(data_dir, Path)
    assert (data_dir / "skills").exists()


# ---------------------------------------------------------------------------
# init_project — directory creation
# ---------------------------------------------------------------------------


def test_init_creates_productteam_dir(tmp_path):
    """init_project creates .productteam/ directory."""
    result = init_project(tmp_path)
    assert (tmp_path / ".productteam").is_dir()
    assert result["created_productteam_dir"] is True


def test_init_creates_sprints_subdir(tmp_path):
    """init_project creates .productteam/sprints/."""
    init_project(tmp_path)
    assert (tmp_path / ".productteam" / "sprints").is_dir()


def test_init_creates_evaluations_subdir(tmp_path):
    """init_project creates .productteam/evaluations/."""
    init_project(tmp_path)
    assert (tmp_path / ".productteam" / "evaluations").is_dir()


def test_init_result_flags_on_first_run(tmp_path):
    """init_project result dict shows all True on first run."""
    result = init_project(tmp_path)
    assert result["created_productteam_dir"] is True
    assert result["created_sprints_dir"] is True
    assert result["created_evaluations_dir"] is True
    assert result["created_config"] is True


# ---------------------------------------------------------------------------
# init_project — skill copying
# ---------------------------------------------------------------------------


def test_init_copies_skills_to_claude_dir(tmp_path):
    """init_project copies skills into .claude/skills/."""
    init_project(tmp_path)
    skills_dir = tmp_path / ".claude" / "skills"
    assert skills_dir.is_dir()


def test_init_copies_multiple_skills(tmp_path):
    """init_project copies more than one skill directory."""
    init_project(tmp_path)
    skills_dir = tmp_path / ".claude" / "skills"
    skill_dirs = [d for d in skills_dir.iterdir() if d.is_dir()]
    assert len(skill_dirs) >= 2


def test_init_skills_contain_skill_md(tmp_path):
    """Each copied skill directory contains a SKILL.md file."""
    init_project(tmp_path)
    skills_dir = tmp_path / ".claude" / "skills"
    for skill_dir in skills_dir.iterdir():
        if skill_dir.is_dir():
            assert (skill_dir / "SKILL.md").exists(), (
                f"SKILL.md missing in {skill_dir.name}"
            )


# ---------------------------------------------------------------------------
# init_project — toml generation
# ---------------------------------------------------------------------------


def test_init_creates_config_toml(tmp_path):
    """init_project creates productteam.toml."""
    init_project(tmp_path)
    assert (tmp_path / "productteam.toml").is_file()


def test_init_toml_has_pipeline_section(tmp_path):
    """Generated productteam.toml contains [pipeline] section."""
    init_project(tmp_path)
    content = (tmp_path / "productteam.toml").read_text()
    assert "pipeline" in content


def test_init_toml_has_gates_section(tmp_path):
    """Generated productteam.toml contains [gates] section."""
    init_project(tmp_path)
    content = (tmp_path / "productteam.toml").read_text()
    assert "gates" in content


def test_init_toml_default_model(tmp_path):
    """Generated productteam.toml has the default model set."""
    init_project(tmp_path)
    content = (tmp_path / "productteam.toml").read_text()
    assert "claude-sonnet-4-6" in content


# ---------------------------------------------------------------------------
# init_project — idempotency
# ---------------------------------------------------------------------------


def test_init_idempotent_no_error(tmp_path):
    """Calling init_project twice does not raise."""
    init_project(tmp_path)
    init_project(tmp_path)  # should not raise


def test_init_idempotent_no_overwrite_config(tmp_path):
    """Second init does not overwrite existing productteam.toml."""
    init_project(tmp_path)
    config_path = tmp_path / "productteam.toml"
    config_path.write_text("[project]\nname = 'my-project'\nversion = '1.0.0'\n")
    init_project(tmp_path)
    content = config_path.read_text()
    assert "my-project" in content


def test_init_force_overwrites_config(tmp_path):
    """force=True overwrites existing productteam.toml."""
    init_project(tmp_path)
    config_path = tmp_path / "productteam.toml"
    config_path.write_text("[project]\nname = 'old'\nversion = '9.9.9'\n")
    init_project(tmp_path, force=True)
    content = config_path.read_text()
    assert "9.9.9" not in content


def test_init_force_result_flag_created_config(tmp_path):
    """force=True sets created_config True even when file exists."""
    init_project(tmp_path)
    result = init_project(tmp_path, force=True)
    assert result["created_config"] is True


def test_init_second_run_result_flags_false(tmp_path):
    """Second init without force returns False for already-existing items."""
    init_project(tmp_path)
    result = init_project(tmp_path)
    assert result["created_productteam_dir"] is False
    assert result["created_sprints_dir"] is False
    assert result["created_evaluations_dir"] is False
    assert result["created_config"] is False


# ---------------------------------------------------------------------------
# get_sprint_status
# ---------------------------------------------------------------------------


def test_sprint_status_empty_dir(tmp_path):
    """Empty sprint directory returns 'planned'."""
    sprint_dir = tmp_path / "sprint-01"
    sprint_dir.mkdir()
    assert get_sprint_status(sprint_dir) == "planned"


def test_sprint_status_with_plan_file(tmp_path):
    """Sprint with plan.md returns 'planned' or 'building'."""
    sprint_dir = tmp_path / "sprint-01"
    sprint_dir.mkdir()
    (sprint_dir / "plan.md").write_text("# Plan\n")
    status = get_sprint_status(sprint_dir)
    assert status in ("planned", "building")


def test_sprint_status_passed(tmp_path):
    """Sprint with evaluation file containing 'passed' returns 'passed'."""
    sprint_dir = tmp_path / "sprint-01"
    sprint_dir.mkdir()
    (sprint_dir / "evaluation.yaml").write_text("verdict: passed\n")
    assert get_sprint_status(sprint_dir) == "passed"


def test_sprint_status_needs_work(tmp_path):
    """Sprint with evaluation file containing 'needs_work' returns 'needs_work'."""
    sprint_dir = tmp_path / "sprint-01"
    sprint_dir.mkdir()
    (sprint_dir / "evaluation.yaml").write_text("verdict: needs_work\n")
    assert get_sprint_status(sprint_dir) == "needs_work"


# ---------------------------------------------------------------------------
# read_project_state
# ---------------------------------------------------------------------------


def test_read_project_state_not_initialized(tmp_path):
    """read_project_state shows not initialized for bare directory."""
    state = read_project_state(tmp_path)
    assert state["initialized"] is False


def test_read_project_state_initialized(tmp_path):
    """read_project_state shows initialized after init_project."""
    init_project(tmp_path)
    state = read_project_state(tmp_path)
    assert state["initialized"] is True


def test_read_project_state_sprints_listed(tmp_path):
    """read_project_state lists sprint directories."""
    init_project(tmp_path)
    (tmp_path / ".productteam" / "sprints" / "sprint-01").mkdir()
    state = read_project_state(tmp_path)
    names = [s["name"] for s in state["sprints"]]
    assert "sprint-01" in names


def test_read_project_state_evaluations_listed(tmp_path):
    """read_project_state lists evaluation files."""
    init_project(tmp_path)
    (tmp_path / ".productteam" / "evaluations" / "eval-01.yaml").write_text(
        "verdict: passed\n"
    )
    state = read_project_state(tmp_path)
    names = [e["name"] for e in state["evaluations"]]
    assert "eval-01" in names
