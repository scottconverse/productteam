#!/usr/bin/env python3
"""Bump ProductTeam version across all 5 locations.

Usage:
    python bump_version.py 2.5.0
    python bump_version.py 2.5.0 --dry-run
"""

import argparse
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent

# All locations where the version string appears
TARGETS = [
    {
        "path": ROOT / "pyproject.toml",
        "pattern": r'(version\s*=\s*)"[^"]+"',
        "replacement": r'\g<1>"{version}"',
        "label": "pyproject.toml",
    },
    {
        "path": ROOT / "src" / "productteam" / "__init__.py",
        "pattern": r'(__version__\s*=\s*)"[^"]+"',
        "replacement": r'\g<1>"{version}"',
        "label": "src/productteam/__init__.py",
    },
    {
        "path": ROOT / "docs" / "index.html",
        "pattern": r"ProductTeam v[\d.]+",
        "replacement": "ProductTeam v{version}",
        "label": "docs/index.html",
    },
    {
        "path": ROOT / "docs" / "architecture.svg",
        "pattern": r"ProductTeam v[\d.]+ Architecture",
        "replacement": "ProductTeam v{version} Architecture",
        "label": "docs/architecture.svg",
    },
    {
        "path": ROOT / "CHANGELOG.md",
        "pattern": None,  # Special: prepend new entry
        "label": "CHANGELOG.md",
    },
]

VERSION_RE = re.compile(r"^\d+\.\d+\.\d+$")


def current_version() -> str:
    """Read the current version from pyproject.toml."""
    text = (ROOT / "pyproject.toml").read_text(encoding="utf-8")
    match = re.search(r'version\s*=\s*"([^"]+)"', text)
    if not match:
        sys.exit("Could not find version in pyproject.toml")
    return match.group(1)


def bump(version: str, dry_run: bool = False) -> None:
    old = current_version()
    if old == version:
        print(f"Already at {version}, nothing to do.")
        return

    print(f"Bumping {old} -> {version}\n")

    for target in TARGETS:
        path: Path = target["path"]
        label: str = target["label"]

        if not path.exists():
            print(f"  SKIP  {label} (file not found)")
            continue

        text = path.read_text(encoding="utf-8")

        if target["pattern"] is None:
            # CHANGELOG.md: check if entry already exists
            if f"[{version}]" in text:
                print(f"  SKIP  {label} (entry already exists)")
                continue
            # Insert placeholder after "# Changelog\n"
            entry = f"\n## [{version}] - YYYY-MM-DD\n\n### Changed\n- (describe changes here)\n"
            text = text.replace("# Changelog\n", "# Changelog\n" + entry, 1)
            print(f"  OK    {label} (added placeholder entry)")
        else:
            pattern = target["pattern"]
            replacement = target["replacement"].format(version=version)
            new_text = re.sub(pattern, replacement, text, count=1)
            if new_text == text:
                print(f"  SKIP  {label} (pattern not matched)")
                continue
            text = new_text
            print(f"  OK    {label}")

        if not dry_run:
            path.write_text(text, encoding="utf-8")

    print(f"\n{'DRY RUN — no files changed.' if dry_run else 'Done.'}")
    if not dry_run:
        print(f"Review the CHANGELOG.md placeholder, then commit.")


def main() -> None:
    parser = argparse.ArgumentParser(description="Bump ProductTeam version.")
    parser.add_argument("version", help="New version (e.g. 2.5.0)")
    parser.add_argument("--dry-run", action="store_true", help="Show what would change without writing")
    args = parser.parse_args()

    if not VERSION_RE.match(args.version):
        sys.exit(f"Invalid version format: {args.version} (expected X.Y.Z)")

    bump(args.version, dry_run=args.dry_run)


if __name__ == "__main__":
    main()
