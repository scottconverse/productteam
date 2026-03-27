"""Tests for config.py — load/save/validate TOML, defaults, missing file handling."""

from __future__ import annotations

from pathlib import Path

import pytest

from productteam.config import (
    CONFIG_FILENAME,
    default_config,
    find_config,
    get_config_value,
    load_config,
    save_config,
    set_config_value,
)
from productteam.models import ForgeConfig, GatesConfig, PipelineConfig, ProductTeamConfig, ProjectConfig


# ---------------------------------------------------------------------------
# default_config
# ---------------------------------------------------------------------------


def test_default_config_returns_model():
    """default_config returns a ProductTeamConfig instance."""
    cfg = default_config()
    assert isinstance(cfg, ProductTeamConfig)


def test_default_config_project_name_empty():
    """Default project name is an empty string."""
    cfg = default_config()
    assert cfg.project.name == ""


def test_default_config_pipeline_model():
    """Default model is claude-sonnet-4-6."""
    cfg = default_config()
    assert cfg.pipeline.model == "claude-sonnet-4-6"


def test_default_forge_host_is_localhost():
    """v2.4.0: Default dashboard bind is 127.0.0.1, not 0.0.0.0."""
    cfg = default_config()
    assert cfg.forge.status_host == "127.0.0.1"


def test_forge_config_default_host_localhost():
    """ForgeConfig model default is 127.0.0.1."""
    forge = ForgeConfig()
    assert forge.status_host == "127.0.0.1"


def test_default_config_max_loops():
    """Default max_loops is 3."""
    cfg = default_config()
    assert cfg.pipeline.max_loops == 3


def test_default_config_require_evaluator():
    """Default require_evaluator is True."""
    cfg = default_config()
    assert cfg.pipeline.require_evaluator is True


def test_default_config_gates_all_true():
    """All default gates are enabled."""
    cfg = default_config()
    assert cfg.gates.prd_approval is True
    assert cfg.gates.sprint_approval is True
    assert cfg.gates.ship_approval is True


# ---------------------------------------------------------------------------
# save_config / load_config round-trip
# ---------------------------------------------------------------------------


def test_save_creates_file(tmp_path):
    """save_config creates the TOML file."""
    cfg = default_config()
    path = tmp_path / "productteam.toml"
    save_config(cfg, path)
    assert path.exists()


def test_save_load_roundtrip(tmp_path):
    """save then load returns equivalent config."""
    cfg = default_config()
    cfg.project.name = "test-project"
    cfg.pipeline.max_loops = 5
    path = tmp_path / "productteam.toml"
    save_config(cfg, path)
    loaded = load_config(path)
    assert loaded.project.name == "test-project"
    assert loaded.pipeline.max_loops == 5


def test_save_load_boolean_roundtrip(tmp_path):
    """Boolean values survive save/load roundtrip."""
    cfg = default_config()
    cfg.gates.prd_approval = False
    path = tmp_path / "productteam.toml"
    save_config(cfg, path)
    loaded = load_config(path)
    assert loaded.gates.prd_approval is False


def test_load_missing_file_raises(tmp_path):
    """load_config raises FileNotFoundError for missing file."""
    with pytest.raises(FileNotFoundError):
        load_config(tmp_path / "nonexistent.toml")


def test_save_creates_parent_directories(tmp_path):
    """save_config creates parent directories if needed."""
    path = tmp_path / "nested" / "deep" / "productteam.toml"
    save_config(default_config(), path)
    assert path.exists()


# ---------------------------------------------------------------------------
# find_config
# ---------------------------------------------------------------------------


def test_find_config_finds_file(tmp_path):
    """find_config finds productteam.toml in given directory."""
    toml_path = tmp_path / CONFIG_FILENAME
    save_config(default_config(), toml_path)
    found = find_config(tmp_path)
    assert found == toml_path


def test_find_config_walks_up(tmp_path):
    """find_config walks up parent directories."""
    toml_path = tmp_path / CONFIG_FILENAME
    save_config(default_config(), toml_path)
    subdir = tmp_path / "src" / "module"
    subdir.mkdir(parents=True)
    found = find_config(subdir)
    assert found == toml_path


def test_find_config_returns_none_when_missing(tmp_path):
    """find_config returns None when no productteam.toml exists anywhere."""
    # Use a deeply nested path inside tmp_path which has no toml
    subdir = tmp_path / "a" / "b" / "c"
    subdir.mkdir(parents=True)
    found = find_config(subdir)
    # Should be None (no productteam.toml in any parent up to filesystem root)
    assert found is None


# ---------------------------------------------------------------------------
# get_config_value
# ---------------------------------------------------------------------------


def test_get_config_value_simple():
    """get_config_value retrieves nested value."""
    cfg = default_config()
    assert get_config_value(cfg, "pipeline.model") == "claude-sonnet-4-6"


def test_get_config_value_boolean():
    """get_config_value retrieves boolean value."""
    cfg = default_config()
    assert get_config_value(cfg, "gates.prd_approval") is True


def test_get_config_value_missing_raises():
    """get_config_value raises KeyError for unknown key."""
    cfg = default_config()
    with pytest.raises(KeyError):
        get_config_value(cfg, "pipeline.nonexistent_field")


# ---------------------------------------------------------------------------
# set_config_value
# ---------------------------------------------------------------------------


def test_set_config_value_string():
    """set_config_value updates string field."""
    cfg = default_config()
    updated = set_config_value(cfg, "pipeline.model", "claude-opus-4")
    assert updated.pipeline.model == "claude-opus-4"


def test_set_config_value_integer():
    """set_config_value coerces string to int for integer fields."""
    cfg = default_config()
    updated = set_config_value(cfg, "pipeline.max_loops", "7")
    assert updated.pipeline.max_loops == 7


def test_set_config_value_boolean_true():
    """set_config_value coerces 'true' string to bool True."""
    cfg = default_config()
    cfg.gates.prd_approval = False
    updated = set_config_value(cfg, "gates.prd_approval", "true")
    assert updated.gates.prd_approval is True


def test_set_config_value_boolean_false():
    """set_config_value coerces 'false' string to bool False."""
    cfg = default_config()
    updated = set_config_value(cfg, "gates.prd_approval", "false")
    assert updated.gates.prd_approval is False


def test_set_config_value_invalid_section():
    """set_config_value raises KeyError for unknown section."""
    cfg = default_config()
    with pytest.raises(KeyError):
        set_config_value(cfg, "unknown_section.field", "value")


def test_set_config_value_invalid_field():
    """set_config_value raises KeyError for unknown field."""
    cfg = default_config()
    with pytest.raises(KeyError):
        set_config_value(cfg, "pipeline.nonexistent", "value")


def test_set_config_value_bad_format():
    """set_config_value raises ValueError for non-dotted key."""
    cfg = default_config()
    with pytest.raises(ValueError):
        set_config_value(cfg, "badkey", "value")


def test_set_config_value_does_not_mutate_original():
    """set_config_value returns new config, original unchanged."""
    cfg = default_config()
    original_model = cfg.pipeline.model
    updated = set_config_value(cfg, "pipeline.model", "new-model")
    assert cfg.pipeline.model == original_model
    assert updated.pipeline.model == "new-model"
