"""Interactive onboarding wizard for ProductTeam.

Handles first-run setup and returning-user flow:
- Concept input
- Provider selection (local Ollama vs cloud API)
- Ollama model checks and installation
- API key entry and encrypted storage
- Launches pipeline when ready
"""

from __future__ import annotations

import base64
import json
import os
import platform
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Optional

from rich.console import Console
from rich.panel import Panel
from rich.prompt import Prompt

console = Console()
error_console = Console(stderr=True)

# User prefs stored in ~/.productteam/prefs.json
_PREFS_DIR = Path.home() / ".productteam"
_PREFS_FILE = _PREFS_DIR / "prefs.json"

# Recommended Ollama models in priority order
RECOMMENDED_MODELS = [
    ("gpt-oss:20b", "13 GB", "OpenAI open-weight, best tool-calling"),
    ("devstral:24b", "14 GB", "Mistral coding agent, strong backup"),
]


# ---------------------------------------------------------------------------
# Preferences (persisted across sessions)
# ---------------------------------------------------------------------------

def _load_prefs() -> dict:
    """Load user preferences from disk."""
    if _PREFS_FILE.exists():
        try:
            return json.loads(_PREFS_FILE.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            return {}
    return {}


def _save_prefs(prefs: dict) -> None:
    """Save user preferences to disk."""
    _PREFS_DIR.mkdir(parents=True, exist_ok=True)
    _PREFS_FILE.write_text(json.dumps(prefs, indent=2), encoding="utf-8")


def _obfuscate_key(key: str) -> str:
    """Simple obfuscation for API key storage. Not encryption, but keeps
    keys out of plain-text config files."""
    return base64.b64encode(key.encode()).decode()


def _deobfuscate_key(encoded: str) -> str:
    """Reverse obfuscation."""
    try:
        return base64.b64decode(encoded.encode()).decode()
    except Exception:
        return ""


def _mask_key(key: str) -> str:
    """Show first 7 and last 4 chars of an API key."""
    if len(key) > 15:
        return key[:7] + "..." + key[-4:]
    return "***"


# ---------------------------------------------------------------------------
# Ollama detection
# ---------------------------------------------------------------------------

def _check_ollama_installed() -> tuple[bool, str]:
    """Check if Ollama CLI is available. Returns (installed, version)."""
    try:
        r = subprocess.run(
            ["ollama", "--version"],
            capture_output=True, text=True, timeout=10,
        )
        if r.returncode == 0:
            version = r.stdout.strip().replace("ollama version is ", "")
            return True, version
    except (FileNotFoundError, subprocess.TimeoutExpired, OSError):
        pass
    return False, ""


def _list_ollama_models() -> list[str]:
    """Get list of installed Ollama models."""
    try:
        r = subprocess.run(
            ["ollama", "list"],
            capture_output=True, text=True, timeout=10,
        )
        if r.returncode == 0:
            models = []
            for line in r.stdout.strip().splitlines()[1:]:  # skip header
                parts = line.split()
                if parts:
                    models.append(parts[0])
            return models
    except (FileNotFoundError, subprocess.TimeoutExpired, OSError):
        pass
    return []


def _find_recommended_model(installed: list[str]) -> Optional[str]:
    """Find the best recommended model from installed list."""
    for model_name, _, _ in RECOMMENDED_MODELS:
        if model_name in installed:
            return model_name
    return None


def _pull_ollama_model(model: str) -> bool:
    """Pull an Ollama model interactively."""
    console.print(f"\n  Pulling {model}... (this may take a few minutes)")
    try:
        result = subprocess.run(
            ["ollama", "pull", model],
            timeout=1800,  # 30 min max
        )
        return result.returncode == 0
    except (subprocess.TimeoutExpired, OSError):
        return False


# ---------------------------------------------------------------------------
# Concept input
# ---------------------------------------------------------------------------

def _get_concept() -> str:
    """Prompt user for their product concept."""
    console.print("  [bold]What are we building?[/bold]\n")
    concept = Prompt.ask("  ")
    while not concept.strip():
        concept = Prompt.ask("  [dim]Describe your product idea[/dim]")
    return concept.strip()


# ---------------------------------------------------------------------------
# Provider selection flows
# ---------------------------------------------------------------------------

def _flow_local(prefs: dict) -> Optional[dict]:
    """Handle local AI (Ollama) setup. Returns config dict or None to abort."""
    console.print("\n  Checking local setup...\n")

    # Check Ollama installed
    installed, version = _check_ollama_installed()
    if not installed:
        console.print("    Ollama:         [red]not found[/red]\n")
        console.print(
            "  Ollama is a free, local AI runtime. To install it:\n"
            "\n"
            "    1. Download from [bold cyan]https://ollama.com/download[/bold cyan]\n"
            "    2. Run the installer\n"
            "    3. Then run [bold]productteam[/bold] again.\n"
        )
        return None

    console.print(f"    Ollama:         [green]installed[/green] (v{version})")

    # Check for recommended models
    models = _list_ollama_models()
    primary = RECOMMENDED_MODELS[0][0]
    backup = RECOMMENDED_MODELS[1][0]

    has_primary = primary in models
    has_backup = backup in models

    if has_primary:
        console.print(f"    {primary}:    [green]installed[/green] (recommended)")
    else:
        console.print(f"    {primary}:    [yellow]not installed[/yellow]")

    if has_backup:
        console.print(f"    {backup}:     [green]installed[/green] (backup)")
    else:
        console.print(f"    {backup}:      [dim]not installed[/dim]")

    # If neither recommended model is installed, offer to pull
    if not has_primary and not has_backup:
        # Check if they have ANY model that might work
        best = _find_recommended_model(models)
        if best:
            console.print(f"\n    Using installed model: [bold]{best}[/bold]")
            chosen_model = best
        else:
            console.print(f"\n  You need at least one recommended model.\n")
            choice = Prompt.ask(
                f"  Install {primary} now? ({RECOMMENDED_MODELS[0][1]} download)",
                choices=["y", "n"], default="y",
            )
            if choice == "y":
                if _pull_ollama_model(primary):
                    console.print(f"    [green]{primary} installed.[/green]")
                    chosen_model = primary
                else:
                    console.print(f"    [red]Failed to pull {primary}.[/red]")
                    console.print(f"\n  You can install it manually:\n    ollama pull {primary}\n")
                    return None
            else:
                console.print(f"\n  Install it later with:\n    [bold]ollama pull {primary}[/bold]\n")
                return None
    elif has_primary:
        chosen_model = primary
    else:
        chosen_model = backup

    # Save preference
    prefs["provider"] = "ollama"
    prefs["model"] = chosen_model
    prefs.pop("api_key", None)
    prefs.pop("api_provider", None)
    _save_prefs(prefs)

    return {
        "provider": "ollama",
        "model": chosen_model,
    }


def _flow_cloud(prefs: dict) -> Optional[dict]:
    """Handle cloud AI (API key) setup. Returns config dict or None to abort."""
    console.print()

    # Provider selection
    console.print("  [bold]Which provider?[/bold]\n")
    console.print("    [bold][1][/bold] Anthropic (Claude)")
    console.print("    [bold][2][/bold] OpenAI")
    console.print("    [bold][3][/bold] Google (Gemini)\n")

    provider_choice = Prompt.ask("  ", choices=["1", "2", "3"], default="1")
    provider_map = {"1": "anthropic", "2": "openai", "3": "gemini"}
    model_defaults = {
        "anthropic": "claude-sonnet-4-6",
        "openai": "gpt-4o",
        "gemini": "gemini-2.0-flash",
    }
    env_var_map = {
        "anthropic": "ANTHROPIC_API_KEY",
        "openai": "OPENAI_API_KEY",
        "gemini": "GEMINI_API_KEY",
    }
    provider_name = provider_map[provider_choice]
    model = model_defaults[provider_name]
    env_var = env_var_map[provider_name]

    # Check for existing key in environment
    env_key = os.environ.get(env_var, "")
    if env_key:
        console.print(f"\n  Found {env_var} in your environment: {_mask_key(env_key)}")
        use_env = Prompt.ask("  Use this key?", choices=["y", "n"], default="y")
        if use_env == "y":
            prefs["provider"] = provider_name
            prefs["model"] = model
            prefs["api_provider"] = provider_name
            # Don't store env-based keys — they're already in the environment
            prefs.pop("api_key", None)
            _save_prefs(prefs)
            return {
                "provider": provider_name,
                "model": model,
                "api_key_source": "environment",
            }

    # Prompt for API key
    console.print(f"\n  Enter your {provider_name.title()} API key:")
    api_key = Prompt.ask("  ", password=True)

    if not api_key.strip():
        console.print("  [red]No key entered.[/red]")
        return None

    console.print(
        "\n  [dim]Your key is stored locally in ~/.productteam/prefs.json.[/dim]"
        "\n  [dim]It never leaves your machine and is never sent to us.[/dim]"
    )

    # Save
    prefs["provider"] = provider_name
    prefs["model"] = model
    prefs["api_provider"] = provider_name
    prefs["api_key"] = _obfuscate_key(api_key.strip())
    _save_prefs(prefs)

    # Also set the env var for this session so the provider factory picks it up
    os.environ[env_var] = api_key.strip()

    return {
        "provider": provider_name,
        "model": model,
    }


def _flow_cloud_returning(prefs: dict) -> Optional[dict]:
    """Handle returning cloud user. Returns config dict or None to abort."""
    provider_name = prefs.get("api_provider", prefs.get("provider", "anthropic"))
    model = prefs.get("model", "claude-sonnet-4-6")
    stored_key = prefs.get("api_key", "")

    env_var_map = {
        "anthropic": "ANTHROPIC_API_KEY",
        "openai": "OPENAI_API_KEY",
        "gemini": "GEMINI_API_KEY",
    }
    env_var = env_var_map.get(provider_name, "")

    # Check environment first
    env_key = os.environ.get(env_var, "") if env_var else ""

    if env_key:
        # Key in environment — use it
        return {"provider": provider_name, "model": model}

    if stored_key:
        # Key in prefs — restore to environment
        real_key = _deobfuscate_key(stored_key)
        if real_key and env_var:
            os.environ[env_var] = real_key
            return {"provider": provider_name, "model": model}

    # No key found — re-enter
    console.print(f"\n  [yellow]No {provider_name.title()} API key found.[/yellow]")
    return _flow_cloud(prefs)


# ---------------------------------------------------------------------------
# Main wizard
# ---------------------------------------------------------------------------

def run_wizard(directory: Optional[Path] = None) -> None:
    """Run the interactive onboarding wizard.

    This is the main entry point when the user types just 'productteam'.
    """
    import asyncio

    from productteam import __version__

    target = (directory or Path.cwd()).resolve()
    prefs = _load_prefs()
    is_returning = bool(prefs.get("provider"))

    # Banner
    console.print()
    console.print(
        Panel(
            f"[bold]ProductTeam[/bold] v{__version__}\n"
            "[dim]AI-Powered Product Builder[/dim]",
            border_style="cyan",
            expand=False,
            padding=(0, 2),
        )
    )
    console.print()

    # Step 1: Get concept
    concept = _get_concept()
    console.print()

    # Step 2: Provider selection
    if is_returning:
        config = _returning_user_flow(prefs, concept)
    else:
        config = _first_time_flow(prefs, concept)

    if config is None:
        console.print("\n  [dim]Come back when you're ready.[/dim]\n")
        return

    # Step 3: Initialize project and run pipeline
    _init_and_run(target, concept, config)


def _first_time_flow(prefs: dict, concept: str) -> Optional[dict]:
    """First-time user: choose local or cloud."""
    console.print("  [bold]How would you like to run this?[/bold]\n")
    console.print(
        "    [bold cyan][A][/bold cyan] Local AI  "
        "[dim]-- Free. Runs on your machine. Slower (~20-30 min).[/dim]"
    )
    console.print(
        "    [bold cyan][B][/bold cyan] Cloud AI  "
        "[dim]-- Fast (~1 min). Standard API costs (~$0.10-0.30/run).[/dim]"
    )
    console.print()

    choice = Prompt.ask("  ", choices=["a", "b", "A", "B"], default="a").lower()

    if choice == "a":
        return _flow_local(prefs)
    else:
        return _flow_cloud(prefs)


def _returning_user_flow(prefs: dict, concept: str) -> Optional[dict]:
    """Returning user: offer to reuse last setup."""
    provider = prefs.get("provider", "")
    model = prefs.get("model", "")

    if provider == "ollama":
        label = f"Local AI ({model})"
    else:
        provider_label = prefs.get("api_provider", provider).title()
        label = f"Cloud AI ({provider_label})"

    console.print(f"  Last time you used: [bold]{label}[/bold]\n")
    console.print("    [bold cyan][A][/bold cyan] Same setup")
    console.print("    [bold cyan][B][/bold cyan] Switch to Local AI" if provider != "ollama"
                   else "    [bold cyan][B][/bold cyan] Switch to Cloud AI")
    console.print("    [bold cyan][C][/bold cyan] Change model or settings")
    console.print()

    choice = Prompt.ask("  ", choices=["a", "b", "c", "A", "B", "C"], default="a").lower()

    if choice == "a":
        # Reuse existing setup
        if provider == "ollama":
            return {"provider": "ollama", "model": model}
        else:
            return _flow_cloud_returning(prefs)

    elif choice == "b":
        # Switch provider type
        if provider == "ollama":
            return _flow_cloud(prefs)
        else:
            return _flow_local(prefs)

    elif choice == "c":
        # Full re-selection
        return _first_time_flow(prefs, concept)

    return None


def _init_and_run(target: Path, concept: str, config: dict) -> None:
    """Initialize project if needed and run the pipeline."""
    import asyncio

    from productteam.config import load_config, save_config
    from productteam.models import ProductTeamConfig
    from productteam.providers.factory import get_provider
    from productteam.scaffold import init_project
    from productteam.supervisor import Supervisor
    from productteam.errors import BudgetExceededError

    provider_name = config["provider"]
    model = config["model"]

    # Auto-init if not already set up
    pt_dir = target / ".productteam"
    config_path = target / "productteam.toml"

    if not pt_dir.exists():
        console.print("  [dim]Setting up project...[/dim]")
        init_project(target)

    # Load or create config
    if config_path.exists():
        pt_config = load_config(config_path)
    else:
        pt_config = ProductTeamConfig()

    # Apply provider settings
    pt_config.pipeline.provider = provider_name
    pt_config.pipeline.model = model
    pt_config.pipeline.auto_approve = True

    # Auto-tune for Ollama
    if provider_name == "ollama":
        pt_config.pipeline.stage_timeout_seconds = 3600
        pt_config.pipeline.planner_timeout_seconds = 3600
        pt_config.pipeline.builder_timeout_seconds = 3600
        pt_config.pipeline.require_design_review = False
        pt_config.gates.prd_approval = False
        pt_config.gates.sprint_approval = False
        pt_config.gates.ship_approval = False

    # Set project name from concept (first few words)
    if not pt_config.project.name:
        words = concept.split()[:3]
        pt_config.project.name = "-".join(w.lower().strip(".,!?") for w in words)

    save_config(pt_config, config_path)

    # Create provider
    try:
        provider = get_provider(
            provider=provider_name,
            model=model,
            api_base=pt_config.pipeline.api_base,
        )
    except Exception as exc:
        error_console.print(f"\n  [red]Error:[/red] {exc}")
        return

    # Show what we're doing
    if provider_name == "ollama":
        mode_label = "local"
        cost_label = "Free"
        time_label = "~20-45 min"
    else:
        mode_label = "cloud"
        cost_label = "~$0.10-0.30"
        time_label = "~1 min"

    console.print(
        f"\n  [bold]Starting pipeline[/bold] "
        f"[dim]({mode_label}: {model}, est. {time_label}, {cost_label})[/dim]\n"
    )

    supervisor = Supervisor(
        project_dir=target,
        config=pt_config,
        provider=provider,
        auto_approve=True,
    )

    try:
        result = asyncio.run(
            supervisor.run(concept=concept)
        )
    except BudgetExceededError as exc:
        error_console.print(f"\n  [bold red]BUDGET EXCEEDED[/bold red]: {exc}")
        return
    except KeyboardInterrupt:
        console.print("\n\n  [yellow]Cancelled.[/yellow] Your progress is saved. Run productteam to resume.\n")
        return

    # Results
    summary = result.token_summary(model_id=model)
    total_in = summary["total_input_tokens"]
    total_out = summary["total_output_tokens"]
    if total_in > 0:
        console.print(f"\n  [dim]Tokens: {total_in:,} in / {total_out:,} out[/dim]")
        if summary["est_cost_usd"] is not None:
            console.print(f"  [dim]Cost: ${summary['est_cost_usd']:.4f}[/dim]")

    if result.status == "complete":
        console.print("\n  [bold green]Pipeline complete.[/bold green] Your project is ready.\n")
    elif result.status == "partial":
        console.print("\n  [yellow]Pipeline paused. Run productteam to resume.[/yellow]\n")
    elif result.status == "stuck":
        console.print("\n  [red]Pipeline stuck. Check the output above.[/red]\n")
    elif result.status == "failed":
        console.print("\n  [red]Pipeline failed.[/red]\n")
