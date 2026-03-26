"""productteam doctor: diagnostic checks for setup problems."""

from __future__ import annotations

import json
import os
import shutil
import sys
from pathlib import Path

from productteam import __version__


class CheckResult:
    """Result of a single diagnostic check."""

    def __init__(self, name: str, passed: bool, message: str, severity: str = "error"):
        self.name = name
        self.passed = passed
        self.message = message
        self.severity = severity  # "error" | "warning" | "info"

    def to_dict(self) -> dict:
        return {
            "name": self.name,
            "passed": self.passed,
            "message": self.message,
            "severity": self.severity,
        }


def check_python_version() -> CheckResult:
    """Check Python >= 3.11."""
    v = sys.version_info
    version_str = f"{v.major}.{v.minor}.{v.micro}"
    if v >= (3, 11):
        return CheckResult("python_version", True, f"Python {version_str} (>=3.11 required)")
    return CheckResult("python_version", False, f"Python {version_str} (>=3.11 required)")


def check_package_version() -> CheckResult:
    """Check productteam is installed and report version."""
    return CheckResult("package_version", True, f"productteam {__version__} installed")


def check_config(project_dir: Path) -> CheckResult:
    """Check productteam.toml is present and valid."""
    config_path = project_dir / "productteam.toml"
    if not config_path.exists():
        return CheckResult("config", False, "productteam.toml not found", "warning")
    try:
        from productteam.config import load_config
        load_config(config_path)
        return CheckResult("config", True, f"productteam.toml found at {config_path}")
    except Exception as e:
        return CheckResult("config", False, f"productteam.toml invalid: {e}")


def check_productteam_dir(project_dir: Path) -> CheckResult:
    """Check .productteam/ directory exists."""
    pt_dir = project_dir / ".productteam"
    if pt_dir.exists():
        return CheckResult("productteam_dir", True, ".productteam/ directory exists")
    return CheckResult("productteam_dir", False, ".productteam/ not found (run productteam init)", "warning")


def check_skills(project_dir: Path) -> CheckResult:
    """Check .claude/skills/ exists with expected skills."""
    skills_dir = project_dir / ".claude" / "skills"
    if not skills_dir.exists():
        return CheckResult("skills", False, ".claude/skills/ not found", "warning")

    expected = {"prd-writer", "planner", "builder", "ui-builder", "evaluator", "evaluator-design", "doc-writer", "orchestrator"}
    found = {d.name for d in skills_dir.iterdir() if d.is_dir()}
    missing = expected - found
    if missing:
        return CheckResult("skills", False, f"Missing skills: {', '.join(sorted(missing))}", "warning")
    return CheckResult("skills", True, f".claude/skills/ ({len(found)} skills found)")


def check_provider(project_dir: Path) -> CheckResult:
    """Check which provider is configured and if API key is set."""
    config_path = project_dir / "productteam.toml"
    if not config_path.exists():
        return CheckResult("provider", False, "No config to check provider", "warning")

    from productteam.config import load_config
    try:
        config = load_config(config_path)
    except Exception:
        return CheckResult("provider", False, "Config invalid", "warning")

    provider = config.pipeline.provider
    env_vars = {
        "anthropic": "ANTHROPIC_API_KEY",
        "openai": "OPENAI_API_KEY",
        "gemini": "GEMINI_API_KEY",
        "ollama": "OLLAMA_HOST",
    }

    env_var = env_vars.get(provider, "")
    if provider == "ollama":
        # Ollama doesn't need an API key
        return CheckResult("provider", True, f"Provider: {provider} (no API key required)")

    if env_var and os.environ.get(env_var):
        return CheckResult("provider", True, f"Provider: {provider}, {env_var} [set]")
    elif env_var:
        return CheckResult("provider", False, f"Provider: {provider}, {env_var} [NOT SET]")
    else:
        return CheckResult("provider", False, f"Unknown provider: {provider}")


def check_forge_queue() -> CheckResult:
    """Check forge queue directory."""
    queue_dir = Path.home() / ".productteam" / "forge" / "queue"
    if queue_dir.exists():
        # Check for stuck jobs
        stuck = 0
        for item in queue_dir.iterdir():
            if item.is_dir() and (item / "job.json").exists():
                try:
                    data = json.loads((item / "job.json").read_text(encoding="utf-8"))
                    if data.get("status") == "running":
                        stuck += 1
                except Exception:
                    pass
        if stuck:
            return CheckResult("forge_queue", True, f"Queue: {queue_dir} ({stuck} potentially stuck jobs)", "warning")
        return CheckResult("forge_queue", True, f"Queue: {queue_dir}")
    return CheckResult("forge_queue", True, f"Queue: {queue_dir} (will be created on first use)", "info")


def check_disk_space() -> CheckResult:
    """Check disk space at ~/.productteam/."""
    target = Path.home() / ".productteam"
    try:
        usage = shutil.disk_usage(target.parent)
        free_gb = usage.free / (1024 ** 3)
        if free_gb < 1.0:
            return CheckResult("disk_space", False, f"{free_gb:.1f} GB available (< 1 GB warning)", "warning")
        return CheckResult("disk_space", True, f"{free_gb:.1f} GB available at {target}")
    except Exception:
        return CheckResult("disk_space", True, "Could not check disk space", "info")


def thinker_doer_note() -> str:
    """Return the thinker/doer limitation note."""
    return (
        "Builder and UI Builder use the tool-use loop regardless of provider setting.\n"
        "All other stages (PRD, Plan, Evaluate, Document) use the configured provider."
    )


def run_doctor(
    project_dir: Path,
    no_network: bool = False,
    as_json: bool = False,
) -> tuple[list[CheckResult], int]:
    """Run all diagnostic checks.

    Returns (results, exit_code). exit_code is 0 if all pass, 1 otherwise.
    """
    results = [
        check_python_version(),
        check_package_version(),
        check_config(project_dir),
        check_productteam_dir(project_dir),
        check_skills(project_dir),
        check_provider(project_dir),
        check_forge_queue(),
        check_disk_space(),
    ]

    has_failure = any(not r.passed and r.severity == "error" for r in results)
    exit_code = 1 if has_failure else 0
    return results, exit_code
