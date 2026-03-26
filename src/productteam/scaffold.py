"""Scaffold logic for 'productteam init' command."""

from __future__ import annotations

import shutil
from pathlib import Path

from productteam.config import CONFIG_FILENAME, default_config, load_config, save_config
from productteam.models import ProductTeamConfig


def _get_package_data_dir() -> Path:
    """Return the directory where packaged skills/ and templates/ live."""
    # When installed, skills/ and templates/ are placed inside the package dir.
    # During development (editable install), __file__ is inside src/productteam/,
    # so we walk up to the repo root and use the top-level skills/ and templates/.
    package_dir = Path(__file__).parent

    # Try package-bundled location first (installed wheel)
    bundled_skills = package_dir / "skills"
    if bundled_skills.exists():
        return package_dir

    # Fall back to repo-root location (editable / dev install)
    repo_root = package_dir.parent.parent  # src/productteam -> src -> repo root
    if (repo_root / "skills").exists():
        return repo_root

    raise FileNotFoundError(
        f"Could not find skills/ directory relative to {package_dir}. "
        "Ensure the package was installed correctly."
    )


def init_project(target_dir: Path, force: bool = False) -> dict[str, bool]:
    """
    Initialise a ProductTeam project in target_dir.

    Returns a dict describing which actions were performed:
      - created_productteam_dir
      - created_sprints_dir
      - created_evaluations_dir
      - copied_skills
      - created_config
    """
    result: dict[str, bool] = {
        "created_productteam_dir": False,
        "created_sprints_dir": False,
        "created_evaluations_dir": False,
        "created_handoffs_dir": False,
        "copied_skills": False,
        "created_config": False,
    }

    # .productteam/ directory
    pt_dir = target_dir / ".productteam"
    if not pt_dir.exists():
        pt_dir.mkdir(parents=True)
        result["created_productteam_dir"] = True

    # .productteam/sprints/
    sprints_dir = pt_dir / "sprints"
    if not sprints_dir.exists():
        sprints_dir.mkdir(parents=True)
        result["created_sprints_dir"] = True

    # .productteam/evaluations/
    evals_dir = pt_dir / "evaluations"
    if not evals_dir.exists():
        evals_dir.mkdir(parents=True)
        result["created_evaluations_dir"] = True

    # .productteam/handoffs/
    handoffs_dir = pt_dir / "handoffs"
    if not handoffs_dir.exists():
        handoffs_dir.mkdir(parents=True)
        result["created_handoffs_dir"] = True

    # Copy skills into .claude/skills/
    skills_dest = target_dir / ".claude" / "skills"
    data_dir = _get_package_data_dir()
    skills_src = data_dir / "skills"

    if skills_src.exists():
        skills_dest.mkdir(parents=True, exist_ok=True)
        for skill_dir in skills_src.iterdir():
            if skill_dir.is_dir():
                dest_skill = skills_dest / skill_dir.name
                if not dest_skill.exists() or force:
                    if dest_skill.exists():
                        shutil.rmtree(dest_skill)
                    shutil.copytree(skill_dir, dest_skill)
                    result["copied_skills"] = True

    # productteam.toml
    config_path = target_dir / CONFIG_FILENAME
    if not config_path.exists() or force:
        config = default_config()
        save_config(config, config_path)
        result["created_config"] = True

    return result


def get_sprint_status(sprint_dir: Path) -> str:
    """Determine the status of a sprint from its directory contents."""
    if not sprint_dir.is_dir():
        return "unknown"

    files = {f.name.lower() for f in sprint_dir.iterdir()}

    # Check for evaluation result files
    for fname in files:
        if "eval" in fname or "evaluation" in fname:
            # Try to read verdict from YAML
            import yaml  # lazy import

            for f in sprint_dir.iterdir():
                if ("eval" in f.name.lower() or "evaluation" in f.name.lower()) and f.suffix in (
                    ".yaml",
                    ".yml",
                    ".md",
                ):
                    try:
                        content = f.read_text(encoding="utf-8")
                        if "passed" in content.lower() or "pass" in content.lower():
                            return "passed"
                        if (
                            "needs_work" in content.lower()
                            or "needs work" in content.lower()
                            or "fail" in content.lower()
                        ):
                            return "needs_work"
                        return "evaluating"
                    except OSError:
                        pass
            return "evaluating"

    # Check for build artifacts
    for fname in files:
        if any(x in fname for x in ("build", "artifact", "handoff", "sprint-contract")):
            return "building"

    # Check for planning documents
    for fname in files:
        if any(x in fname for x in ("plan", "prd", "spec")):
            return "planned"

    return "planned"


def read_project_state(target_dir: Path) -> dict:
    """
    Read the .productteam/ directory and return structured state info.

    Reads from state.json first if available (v2.0 format), falls back
    to directory scan for backwards compatibility.

    Returns:
      {
        "initialized": bool,
        "sprints": [{"name": str, "status": str}],
        "evaluations": [{"name": str, "verdict": str}],
        "pipeline_phase": str,
      }
    """
    pt_dir = target_dir / ".productteam"
    state: dict = {
        "initialized": pt_dir.exists(),
        "sprints": [],
        "evaluations": [],
        "pipeline_phase": "planning",
    }

    if not pt_dir.exists():
        return state

    # Try state.json first (v2.0 format)
    state_json = pt_dir / "state.json"
    if state_json.exists():
        try:
            import json
            data = json.loads(state_json.read_text(encoding="utf-8"))
            state["pipeline_phase"] = data.get("pipeline_phase", "planning")
            # Extract sprint statuses from stages
            stages = data.get("stages", {})
            for key, info in stages.items():
                if key.startswith("build:"):
                    sprint_name = key.split(":", 1)[1]
                    status = "passed" if info.get("status") == "passed" else "building"
                    state["sprints"].append({"name": sprint_name, "status": status})
        except Exception:
            pass  # Fall through to directory scan

    # Directory scan fallback (also supplements state.json data)
    sprints_dir = pt_dir / "sprints"
    if sprints_dir.exists():
        existing_names = {s["name"] for s in state["sprints"]}
        for item in sorted(sprints_dir.iterdir()):
            if item.is_dir() and item.name not in existing_names:
                status = get_sprint_status(item)
                state["sprints"].append({"name": item.name, "status": status})
            elif item.is_file() and item.suffix in (".yaml", ".yml") and item.stem not in existing_names:
                state["sprints"].append({"name": item.stem, "status": "planned"})

    # Evaluations
    evals_dir = pt_dir / "evaluations"
    if evals_dir.exists():
        for item in sorted(evals_dir.iterdir()):
            if item.is_file() and item.suffix in (".yaml", ".yml", ".md", ".json"):
                verdict = _read_verdict(item)
                state["evaluations"].append({"name": item.stem, "verdict": verdict})

    # Determine overall pipeline phase (directory scan may override state.json)
    if not state_json.exists():
        state["pipeline_phase"] = _determine_pipeline_phase(state)

    return state


def _read_verdict(eval_file: Path) -> str:
    """Extract verdict from an evaluation file."""
    try:
        content = eval_file.read_text(encoding="utf-8").lower()
        if "passed" in content or "pass" in content:
            return "passed"
        if "needs_work" in content or "needs work" in content or "fail" in content:
            return "needs_work"
        return "pending"
    except OSError:
        return "unknown"


def _determine_pipeline_phase(state: dict) -> str:
    """Determine the overall pipeline phase from state."""
    sprints = state["sprints"]
    evaluations = state["evaluations"]

    statuses = {s["status"] for s in sprints}
    verdicts = {e["verdict"] for e in evaluations}

    # Check passed evaluations first — highest priority
    if "passed" in verdicts:
        return "shipping"

    if not sprints:
        # Only evaluations present (or nothing)
        if evaluations:
            return "evaluating"
        return "planning"

    if "evaluating" in statuses or evaluations:
        return "evaluating"
    if "building" in statuses:
        return "building"
    if "planned" in statuses:
        return "building"

    return "planning"
