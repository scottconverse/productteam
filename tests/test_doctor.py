"""Tests for productteam doctor."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from productteam.doctor import (
    check_config,
    check_disk_space,
    check_forge_queue,
    check_package_version,
    check_productteam_dir,
    check_provider,
    check_python_version,
    check_skills,
    run_doctor,
    thinker_doer_note,
)


def test_python_version_passes():
    """Python version check passes on 3.11+."""
    result = check_python_version()
    assert result.passed is True


def test_package_version_passes():
    """Package version check always passes when installed."""
    result = check_package_version()
    assert result.passed is True
    from productteam import __version__
    assert __version__ in result.message


def test_config_missing(tmp_path):
    """Config check warns when productteam.toml missing."""
    result = check_config(tmp_path)
    assert result.passed is False


def test_config_valid(tmp_path):
    """Config check passes when productteam.toml is valid."""
    from productteam.config import default_config, save_config
    save_config(default_config(), tmp_path / "productteam.toml")
    result = check_config(tmp_path)
    assert result.passed is True


def test_productteam_dir_exists(tmp_path):
    """Directory check passes when .productteam/ exists."""
    (tmp_path / ".productteam").mkdir()
    result = check_productteam_dir(tmp_path)
    assert result.passed is True


def test_productteam_dir_missing(tmp_path):
    """Directory check warns when .productteam/ missing."""
    result = check_productteam_dir(tmp_path)
    assert result.passed is False


def test_skills_missing(tmp_path):
    """Skills check warns when .claude/skills/ missing."""
    result = check_skills(tmp_path)
    assert result.passed is False


def test_skills_present(tmp_path):
    """Skills check passes when all expected skills exist."""
    from productteam.scaffold import init_project
    init_project(tmp_path)
    result = check_skills(tmp_path)
    assert result.passed is True


def test_provider_no_config(tmp_path):
    """Provider check warns when no config file."""
    result = check_provider(tmp_path)
    assert result.passed is False


def test_provider_anthropic_key_set(tmp_path, monkeypatch):
    """Provider check passes when ANTHROPIC_API_KEY is set."""
    from productteam.config import default_config, save_config
    save_config(default_config(), tmp_path / "productteam.toml")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")
    result = check_provider(tmp_path)
    assert result.passed is True
    assert "[set]" in result.message


def test_provider_anthropic_key_missing(tmp_path, monkeypatch):
    """Provider check fails when ANTHROPIC_API_KEY is not set."""
    from productteam.config import default_config, save_config
    save_config(default_config(), tmp_path / "productteam.toml")
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    result = check_provider(tmp_path)
    assert result.passed is False
    assert "NOT SET" in result.message


def test_disk_space_check():
    """Disk space check runs without error."""
    result = check_disk_space()
    # Should pass unless disk is literally full
    assert result.passed is True


def test_run_doctor_exit_0_when_all_pass(tmp_path, monkeypatch):
    """run_doctor returns exit 0 when all checks pass."""
    from productteam.scaffold import init_project
    init_project(tmp_path)
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")
    results, exit_code = run_doctor(tmp_path)
    assert exit_code == 0


def test_run_doctor_json_output(tmp_path):
    """run_doctor results are JSON-serializable."""
    results, _ = run_doctor(tmp_path)
    data = [r.to_dict() for r in results]
    json_str = json.dumps(data)
    assert json_str  # Valid JSON


def test_thinker_doer_note():
    """Thinker/doer note is always returned."""
    note = thinker_doer_note()
    assert "Builder" in note
    assert "tool-use loop" in note
