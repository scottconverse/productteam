"""productteam.toml loader and saver."""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

import tomli_w

if sys.version_info >= (3, 11):
    import tomllib
else:
    try:
        import tomllib  # type: ignore[no-redef]
    except ImportError:
        import tomli as tomllib  # type: ignore[no-redef]

from productteam.models import ProductTeamConfig

CONFIG_FILENAME = "productteam.toml"


def find_config(start: Path | None = None) -> Path | None:
    """Walk up from start directory looking for productteam.toml."""
    directory = Path(start or Path.cwd())
    for parent in [directory, *directory.parents]:
        candidate = parent / CONFIG_FILENAME
        if candidate.exists():
            return candidate
    return None


def load_config(path: Path) -> ProductTeamConfig:
    """Load and validate productteam.toml from path."""
    if not path.exists():
        raise FileNotFoundError(f"Config file not found: {path}")
    with path.open("rb") as fh:
        data = tomllib.load(fh)
    return ProductTeamConfig.model_validate(data)


def save_config(config: ProductTeamConfig, path: Path) -> None:
    """Write ProductTeamConfig to path as TOML."""
    data: dict[str, Any] = config.model_dump()
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("wb") as fh:
        tomli_w.dump(data, fh)


def default_config() -> ProductTeamConfig:
    """Return a default ProductTeamConfig instance."""
    return ProductTeamConfig()


def get_config_value(config: ProductTeamConfig, key: str) -> Any:
    """Get a dot-separated key from config, e.g. 'pipeline.model'."""
    parts = key.split(".")
    obj: Any = config
    for part in parts:
        if hasattr(obj, part):
            obj = getattr(obj, part)
        elif isinstance(obj, dict):
            obj = obj[part]
        else:
            raise KeyError(f"Config key not found: {key!r}")
    return obj


def set_config_value(config: ProductTeamConfig, key: str, value: str) -> ProductTeamConfig:
    """Set a dot-separated key on config. Returns updated config."""
    parts = key.split(".")
    if len(parts) != 2:
        raise ValueError(f"Key must be in 'section.field' format, got: {key!r}")
    section_name, field_name = parts
    data = config.model_dump()
    if section_name not in data:
        raise KeyError(f"Unknown config section: {section_name!r}")
    if field_name not in data[section_name]:
        raise KeyError(f"Unknown config field: {field_name!r} in section {section_name!r}")

    # Coerce value to the field's type
    current = data[section_name][field_name]
    if isinstance(current, bool):
        coerced: Any = value.lower() in ("true", "1", "yes", "on")
    elif isinstance(current, int):
        coerced = int(value)
    else:
        coerced = value

    data[section_name][field_name] = coerced
    return ProductTeamConfig.model_validate(data)
