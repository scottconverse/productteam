"""v2.4.0 security hardening — cross-cutting tests.

Tests that verify the security properties introduced in v2.4.0:
- Dependency pinning (exact versions in pyproject.toml)
- Dashboard default bind (127.0.0.1)
- serve_dashboard default host
"""

from __future__ import annotations

from pathlib import Path

import pytest


# ---------------------------------------------------------------------------
# Dependency pinning (Fix 4)
# ---------------------------------------------------------------------------

PYPROJECT = Path(__file__).resolve().parent.parent / "pyproject.toml"


def test_dependencies_are_pinned():
    """All runtime dependencies use == (exact pin), not >= ranges."""
    text = PYPROJECT.read_text()
    in_deps = False
    deps = []
    for line in text.splitlines():
        stripped = line.strip()
        if stripped.startswith("dependencies"):
            in_deps = True
            continue
        if in_deps:
            if stripped == "]":
                break
            if stripped.startswith('"'):
                deps.append(stripped.strip('",'))
    assert len(deps) >= 7, f"Expected at least 7 deps, found {len(deps)}: {deps}"
    for dep in deps:
        assert "==" in dep, f"Dependency not pinned to exact version: {dep}"
        assert ">=" not in dep, f"Dependency uses >= range: {dep}"


# ---------------------------------------------------------------------------
# Dashboard default bind (Fix 1)
# ---------------------------------------------------------------------------


def test_serve_dashboard_default_host():
    """serve_dashboard defaults to 127.0.0.1."""
    import inspect
    from productteam.forge.dashboard import serve_dashboard

    sig = inspect.signature(serve_dashboard)
    host_default = sig.parameters["host"].default
    assert host_default == "127.0.0.1", f"serve_dashboard host default is {host_default!r}, expected '127.0.0.1'"
