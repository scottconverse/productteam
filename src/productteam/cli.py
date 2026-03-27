"""Typer CLI application for ProductTeam."""

from __future__ import annotations

from pathlib import Path
from typing import Optional

import typer
from rich.console import Console
from rich.panel import Panel
from rich.table import Table
from rich import box

from productteam import __version__

app = typer.Typer(
    name="productteam",
    help="AI-powered product development pipeline using Claude skills.",
    add_completion=False,
    no_args_is_help=True,
)

test_app = typer.Typer(help="Run ProductTeam test suite.")
app.add_typer(test_app, name="test")

config_app = typer.Typer(help="Manage productteam.toml configuration.")
app.add_typer(config_app, name="config")

forge_app = typer.Typer(help="Forge: submit ideas, run pipelines headlessly.")
app.add_typer(forge_app, name="forge")

console = Console()
error_console = Console(stderr=True)


# ---------------------------------------------------------------------------
# productteam version
# ---------------------------------------------------------------------------


@app.command("version")
def version_cmd() -> None:
    """Show ProductTeam version."""
    console.print(f"ProductTeam v{__version__}")


# ---------------------------------------------------------------------------
# productteam doctor
# ---------------------------------------------------------------------------


@app.command("doctor")
def doctor_cmd(
    no_network: bool = typer.Option(False, "--no-network", help="Skip API reachability checks"),
    json_output: bool = typer.Option(False, "--json", help="Output as JSON"),
    directory: Optional[Path] = typer.Option(
        None, "--dir", "-d", help="Project directory (default: current directory)"
    ),
) -> None:
    """Check ProductTeam environment and configuration."""
    import json

    from productteam.doctor import run_doctor, thinker_doer_note

    target = (directory or Path.cwd()).resolve()
    results, exit_code = run_doctor(target, no_network=no_network)

    if json_output:
        data = [r.to_dict() for r in results]
        console.print(json.dumps(data, indent=2))
        raise typer.Exit(code=exit_code)

    console.print("\n[bold]Checking ProductTeam environment...[/bold]\n")

    for r in results:
        if r.passed:
            icon = "[green][check][/green]" if r.severity != "info" else "[blue][i][/blue]"
            console.print(f"  {icon} {r.message}")
        else:
            if r.severity == "warning":
                console.print(f"  [yellow][ ][/yellow] {r.message}")
            else:
                console.print(f"  [red][X][/red] {r.message}")

    console.print(f"\n[dim]{thinker_doer_note()}[/dim]")

    if exit_code == 0:
        console.print("\n[bold green]All checks passed. ProductTeam is ready.[/bold green]")
    else:
        console.print("\n[bold red]Some checks failed. Fix the issues above.[/bold red]")

    raise typer.Exit(code=exit_code)


# ---------------------------------------------------------------------------
# productteam init
# ---------------------------------------------------------------------------


@app.command("init")
def init_cmd(
    directory: Optional[Path] = typer.Argument(
        None, help="Target directory (default: current directory)"
    ),
    force: bool = typer.Option(False, "--force", "-f", help="Overwrite existing files"),
) -> None:
    """Initialize ProductTeam in the current project."""
    from productteam.scaffold import init_project

    target = (directory or Path.cwd()).resolve()

    console.print(f"[bold cyan]Initializing ProductTeam in[/bold cyan] {target}")

    try:
        result = init_project(target, force=force)
    except FileNotFoundError as exc:
        error_console.print(f"[red]Error:[/red] {exc}")
        raise typer.Exit(code=1)

    # Report what happened
    if result["created_productteam_dir"]:
        console.print("  [green]OK[/green] Created .productteam/")
    else:
        console.print("  [dim]-- .productteam/ already exists[/dim]")

    if result["created_sprints_dir"]:
        console.print("  [green]OK[/green] Created .productteam/sprints/")

    if result["created_evaluations_dir"]:
        console.print("  [green]OK[/green] Created .productteam/evaluations/")

    if result["copied_skills"]:
        console.print("  [green]OK[/green] Copied skills into .claude/skills/")
    else:
        console.print("  [dim]-- Skills already present (use --force to overwrite)[/dim]")

    if result["created_config"]:
        console.print("  [green]OK[/green] Created productteam.toml")
    else:
        console.print("  [dim]-- productteam.toml already exists[/dim]")

    console.print(
        "\n[bold green]ProductTeam initialized.[/bold green] "
        "Run [bold]'productteam status'[/bold] to see pipeline state."
    )


# ---------------------------------------------------------------------------
# productteam status
# ---------------------------------------------------------------------------


@app.command("status")
def status_cmd(
    directory: Optional[Path] = typer.Argument(
        None, help="Project directory (default: current directory)"
    ),
) -> None:
    """Show pipeline status for the current project."""
    from productteam.scaffold import read_project_state

    target = (directory or Path.cwd()).resolve()
    state = read_project_state(target)

    if not state["initialized"]:
        error_console.print(
            "[yellow]ProductTeam not initialized.[/yellow] "
            "Run [bold]'productteam init'[/bold] first."
        )
        raise typer.Exit(code=1)

    # Pipeline phase panel
    phase = state["pipeline_phase"].upper()
    phase_colors = {
        "PLANNING": "blue",
        "BUILDING": "yellow",
        "EVALUATING": "cyan",
        "DOCUMENTING": "magenta",
        "SHIPPING": "green",
    }
    color = phase_colors.get(phase, "white")
    console.print(
        Panel(
            f"[bold {color}]{phase}[/bold {color}]",
            title="Pipeline Phase",
            border_style=color,
            expand=False,
        )
    )

    # Sprints table
    sprints = state["sprints"]
    if sprints:
        sprint_table = Table(title="Sprints", box=box.ROUNDED)
        sprint_table.add_column("Sprint", style="bold")
        sprint_table.add_column("Status")
        status_styles = {
            "planned": "blue",
            "building": "yellow",
            "evaluating": "cyan",
            "passed": "green",
            "needs_work": "red",
            "unknown": "dim",
        }
        for sprint in sprints:
            s = sprint["status"]
            style = status_styles.get(s, "white")
            sprint_table.add_row(sprint["name"], f"[{style}]{s}[/{style}]")
        console.print(sprint_table)
    else:
        console.print("[dim]No sprints found in .productteam/sprints/[/dim]")

    # Evaluations table
    evaluations = state["evaluations"]
    if evaluations:
        eval_table = Table(title="Evaluations", box=box.ROUNDED)
        eval_table.add_column("Evaluation", style="bold")
        eval_table.add_column("Verdict")
        verdict_styles = {
            "passed": "green",
            "needs_work": "red",
            "pending": "yellow",
            "unknown": "dim",
        }
        for ev in evaluations:
            v = ev["verdict"]
            style = verdict_styles.get(v, "white")
            eval_table.add_row(ev["name"], f"[{style}]{v}[/{style}]")
        console.print(eval_table)
    else:
        console.print("[dim]No evaluations found in .productteam/evaluations/[/dim]")


# ---------------------------------------------------------------------------
# productteam config  (sub-commands)
# ---------------------------------------------------------------------------


@config_app.callback(invoke_without_command=True)
def config_show(ctx: typer.Context) -> None:
    """Show current productteam.toml settings."""
    if ctx.invoked_subcommand is not None:
        return

    from productteam.config import find_config, load_config

    config_path = find_config()
    if config_path is None:
        error_console.print(
            "[yellow]No productteam.toml found.[/yellow] "
            "Run [bold]'productteam init'[/bold] to create one."
        )
        raise typer.Exit(code=1)

    config = load_config(config_path)
    data = config.model_dump()

    console.print(f"[dim]Config file: {config_path}[/dim]\n")
    for section, values in data.items():
        table = Table(title=f"\\[{section}]", box=box.SIMPLE, show_header=True)
        table.add_column("Key", style="bold cyan")
        table.add_column("Value")
        for key, val in values.items():
            table.add_row(key, str(val))
        console.print(table)


# ---------------------------------------------------------------------------
# productteam run
# ---------------------------------------------------------------------------


@app.command("run")
def run_cmd(
    concept: Optional[str] = typer.Argument(
        None, help="The product concept to build. Optional if resuming."
    ),
    step: Optional[str] = typer.Option(
        None, "--step", help="Run only a specific stage (prd|plan|build|evaluate|document|evaluate-design|ship)"
    ),
    sprint: Optional[str] = typer.Option(
        None, "--sprint", help="Target a specific sprint (with --step build or evaluate)"
    ),
    auto_approve: bool = typer.Option(
        False, "--auto-approve", help="Skip interactive approval gates"
    ),
    rebuild: bool = typer.Option(
        False, "--rebuild", help="Force rebuild even if a sprint has already passed"
    ),
    dry_run: bool = typer.Option(
        False, "--dry-run", help="Show what would happen without calling the LLM"
    ),
    directory: Optional[Path] = typer.Option(
        None, "--dir", "-d", help="Project directory (default: current directory)"
    ),
) -> None:
    """Run the full product development pipeline."""
    import asyncio

    from productteam.config import load_config
    from productteam.providers.factory import get_provider
    from productteam.supervisor import Supervisor

    target = (directory or Path.cwd()).resolve()

    # Check .productteam/ exists
    pt_dir = target / ".productteam"
    if not pt_dir.exists():
        error_console.print(
            "[red]Error:[/red] .productteam/ not found. "
            "Run [bold]'productteam init'[/bold] first."
        )
        raise typer.Exit(code=1)

    # Check productteam.toml exists and is valid
    config_path = target / "productteam.toml"
    if not config_path.exists():
        error_console.print(
            "[red]Error:[/red] productteam.toml not found. "
            "Run [bold]'productteam init'[/bold] to create one."
        )
        raise typer.Exit(code=1)

    try:
        config = load_config(config_path)
    except Exception as exc:
        error_console.print(f"[red]Error:[/red] productteam.toml is invalid: {exc}")
        raise typer.Exit(code=1)

    # Create provider (skip for dry run)
    provider = None
    if not dry_run:
        try:
            provider = get_provider(
                provider=config.pipeline.provider,
                model=config.pipeline.model,
                api_base=config.pipeline.api_base,
            )
        except Exception as exc:
            error_console.print(f"[red]Error:[/red] {exc}")
            raise typer.Exit(code=1)

    if provider:
        console.print(
            f"[bold]ProductTeam Pipeline[/bold] "
            f"[dim](provider: {provider.name()}, model: {provider.model_id()})[/dim]"
        )
    else:
        console.print("[bold]ProductTeam Pipeline[/bold] [dim](dry run)[/dim]")

    use_auto = auto_approve or config.pipeline.auto_approve

    supervisor = Supervisor(
        project_dir=target,
        config=config,
        provider=provider,
        auto_approve=use_auto,
    )

    result = asyncio.run(
        supervisor.run(
            concept=concept or "",
            step=step,
            sprint=sprint,
            rebuild=rebuild,
            dry_run=dry_run,
        )
    )

    if result.status == "complete":
        console.print("\n[bold green]Pipeline complete.[/bold green]")
    elif result.status == "partial":
        console.print("\n[yellow]Pipeline paused. Run again to resume.[/yellow]")
    elif result.status == "stuck":
        console.print("\n[red]Pipeline stuck. Check the output above.[/red]")
        raise typer.Exit(code=1)
    elif result.status == "failed":
        console.print("\n[red]Pipeline failed.[/red]")
        raise typer.Exit(code=1)


# ---------------------------------------------------------------------------
# productteam recover
# ---------------------------------------------------------------------------


# Pipeline stage ordering — used by recover to find the resume point
_STAGE_ORDER = ["prd", "plan", "build", "evaluate", "document", "evaluate-design", "ship"]


@app.command("recover")
def recover_cmd(
    yes: bool = typer.Option(False, "--yes", "-y", help="Resume immediately without confirmation"),
    stage: Optional[str] = typer.Option(
        None, "--stage", "-s",
        help="Reset only this specific stage (prd|plan|build|evaluate|document|evaluate-design). "
             "Default: reset all stuck stages."
    ),
    directory: Optional[Path] = typer.Option(
        None, "--dir", "-d", help="Project directory (default: current directory)"
    ),
) -> None:
    """Recover a stuck pipeline and resume from the last completed stage.

    Reads state.json, identifies stuck/running stages, resets them to pending,
    and re-runs from the stuck stage. The stuck stage is always re-executed
    because a timeout or crash typically means incomplete output (e.g. the
    Planner wrote some sprint files but not all).

    With --stage, resets only the specified stage to pending without touching
    other stages or re-entering the pipeline. Use 'productteam run' afterward
    to resume.

    If the stuck stage already produced valid artifacts and you don't want them
    overwritten, use 'productteam run' instead — it skips stages marked complete.
    Use 'productteam run --rebuild' for a full clean re-run of a stage.
    """
    import asyncio

    target = (directory or Path.cwd()).resolve()
    state_path = target / ".productteam" / "state.json"

    if not state_path.exists():
        error_console.print(
            "[red]Error:[/red] No state.json found. "
            "Nothing to recover. Run [bold]'productteam run'[/bold] first."
        )
        raise typer.Exit(code=1)

    import json as json_mod

    state = json_mod.loads(state_path.read_text(encoding="utf-8"))
    stages = state.get("stages", {})
    concept = state.get("concept", "")

    if not concept:
        error_console.print("[red]Error:[/red] No concept in state.json. Nothing to recover.")
        raise typer.Exit(code=1)

    # --stage mode: reset a single stage and exit (no pipeline re-entry)
    _VALID_STAGES = {"prd", "plan", "build", "evaluate", "document", "evaluate-design", "ship"}
    if stage:
        if stage not in _VALID_STAGES:
            error_console.print(
                f"[red]Error:[/red] Unknown stage '{stage}'. "
                f"Valid stages: {', '.join(sorted(_VALID_STAGES))}"
            )
            raise typer.Exit(code=1)

        # Find matching stage keys (handles both "build" and "build:sprint-001")
        matching = [
            (name, info.get("status", ""))
            for name, info in stages.items()
            if name == stage or name.startswith(f"{stage}:")
        ]

        if not matching:
            console.print(f"[yellow]Stage '{stage}' not found in state.json.[/yellow]")
            raise typer.Exit(code=0)

        stuck_matching = [(n, s) for n, s in matching if s not in ("complete", "passed", "pending")]
        if not stuck_matching:
            console.print(f"[green]Stage '{stage}' is not stuck.[/green] Nothing to reset.")
            console.print(f"  Current status: {', '.join(f'{n}={s}' for n, s in matching)}")
            raise typer.Exit(code=0)

        for name, status in stuck_matching:
            stages[name]["status"] = "pending"
            console.print(f"  Reset [red]{name}[/red] ({status}) → [green]pending[/green]")

        state["stages"] = stages
        state_path.write_text(json_mod.dumps(state, indent=2), encoding="utf-8")
        console.print(f"\n[green]Done.[/green] Run [bold]'productteam run'[/bold] to resume.")
        raise typer.Exit(code=0)

    # Default mode: find and reset all stuck stages, then re-enter pipeline
    stuck_stages = []
    completed_stages = []
    for name, info in stages.items():
        status = info.get("status", "")
        if status in ("stuck", "running", "needs_work", "max_calls"):
            stuck_stages.append((name, status))
        elif status == "complete":
            completed_stages.append(name)

    if not stuck_stages:
        console.print("[green]No stuck stages found.[/green] Pipeline state looks clean.")
        console.print("[dim]Use 'productteam run' to continue the pipeline.[/dim]")
        raise typer.Exit(code=0)

    # Determine resume point
    # The resume stage is the first stuck stage in pipeline order
    resume_stage = None
    for stage_name in _STAGE_ORDER:
        for stuck_name, _ in stuck_stages:
            # Handle both "build" and "build:sprint-001" style keys
            base = stuck_name.split(":")[0]
            if base == stage_name:
                resume_stage = stage_name
                break
        if resume_stage:
            break

    if not resume_stage:
        # Fallback: just use the first stuck stage
        resume_stage = stuck_stages[0][0].split(":")[0]

    # Find sprint context for build/evaluate recovery
    resume_sprint = None
    for stuck_name, _ in stuck_stages:
        info = stages.get(stuck_name, {})
        if info.get("sprint"):
            resume_sprint = info["sprint"]
            break

    # Report what we found
    console.print(f"\n[bold]Pipeline Recovery[/bold]")
    console.print(f"  Concept: [dim]{concept[:80]}[/dim]")
    console.print(f"  Completed stages: [green]{', '.join(completed_stages) or 'none'}[/green]")
    console.print(f"  Stuck stages:")
    for name, status in stuck_stages:
        console.print(f"    [red]{name}[/red]: {status}")

    console.print(f"\n  [bold]Will resume from:[/bold] [cyan]{resume_stage}[/cyan]"
                  + (f" (sprint: {resume_sprint})" if resume_sprint else ""))

    # What recovery will do
    console.print(f"\n  Recovery actions:")
    for stuck_name, _ in stuck_stages:
        console.print(f"    Reset [red]{stuck_name}[/red] → pending")

    if not yes:
        from rich.prompt import Prompt
        choice = Prompt.ask("\nProceed with recovery?", choices=["y", "n"], default="y")
        if choice != "y":
            console.print("[yellow]Recovery cancelled.[/yellow]")
            raise typer.Exit(code=0)

    # Reset stuck stages
    for stuck_name, _ in stuck_stages:
        stages[stuck_name]["status"] = "pending"
    state["stages"] = stages
    state["updated_at"] = ""  # will be set by _save_state
    state_path.write_text(json_mod.dumps(state, indent=2), encoding="utf-8")
    console.print("[green]State reset.[/green]")

    # Re-enter pipeline
    from productteam.config import load_config
    from productteam.providers.factory import get_provider
    from productteam.supervisor import Supervisor

    config_path = target / "productteam.toml"
    if not config_path.exists():
        error_console.print("[red]Error:[/red] productteam.toml not found.")
        raise typer.Exit(code=1)

    config = load_config(config_path)

    try:
        provider = get_provider(
            provider=config.pipeline.provider,
            model=config.pipeline.model,
            api_base=config.pipeline.api_base,
        )
    except Exception as exc:
        error_console.print(f"[red]Error:[/red] {exc}")
        raise typer.Exit(code=1)

    console.print(
        f"\n[bold]Resuming pipeline[/bold] "
        f"[dim](from: {resume_stage})[/dim]"
    )

    # Use --step for build/evaluate recovery with sprint context,
    # otherwise let the full pipeline handle it (it skips completed stages)
    supervisor = Supervisor(
        project_dir=target,
        config=config,
        provider=provider,
        auto_approve=True,
    )

    if resume_stage in ("build", "evaluate") and resume_sprint:
        result = asyncio.run(
            supervisor.run(step=resume_stage, sprint=resume_sprint)
        )
    else:
        result = asyncio.run(supervisor.run())

    if result.status == "complete":
        console.print("\n[bold green]Pipeline recovered and completed.[/bold green]")
    elif result.status == "partial":
        console.print("\n[yellow]Pipeline paused at gate. Run again to continue.[/yellow]")
    elif result.status == "stuck":
        console.print("\n[red]Pipeline stuck again. Check the output above.[/red]")
        raise typer.Exit(code=1)
    elif result.status == "failed":
        console.print("\n[red]Pipeline failed.[/red]")
        raise typer.Exit(code=1)


# ---------------------------------------------------------------------------
# productteam test
# ---------------------------------------------------------------------------

_LIVE_API_KEY_MAP = {
    "anthropic": "ANTHROPIC_API_KEY",
    "openai": "OPENAI_API_KEY",
    "gemini": "GEMINI_API_KEY",
}


@test_app.callback(invoke_without_command=True)
def test_cmd(
    ctx: typer.Context,
    live: bool = typer.Option(False, "--live", help="Run live integration tests (makes real API calls)"),
    provider: Optional[str] = typer.Option(
        None, "--provider", "-p",
        help="LLM provider for live tests (anthropic|openai|ollama|gemini). Default: from config or anthropic.",
    ),
    model: Optional[str] = typer.Option(
        None, "--model", "-m",
        help="Model override for live tests.",
    ),
    verbose: bool = typer.Option(False, "--verbose", "-v", help="Verbose pytest output"),
    coverage: bool = typer.Option(False, "--cov", help="Run with coverage reporting"),
    keyword: Optional[str] = typer.Option(None, "-k", help="pytest -k filter expression"),
    directory: Optional[Path] = typer.Option(
        None, "--dir", "-d", help="Project directory (default: current directory)"
    ),
) -> None:
    """Run the ProductTeam test suite.

    By default runs offline unit tests only. Use --live to run integration
    tests that make real API calls (costs money, requires API key).
    """
    if ctx.invoked_subcommand is not None:
        return

    import subprocess
    import sys

    target = (directory or Path.cwd()).resolve()

    # Build pytest args
    pytest_args = [sys.executable, "-m", "pytest"]

    if live:
        _live_preflight(target, provider, model)
        pytest_args += ["-m", "live"]
    else:
        pytest_args += ["-m", "not live"]

    if verbose:
        pytest_args.append("-v")
    if coverage:
        pytest_args += ["--cov=productteam", "--cov-report=term-missing"]
    if keyword:
        pytest_args += ["-k", keyword]

    pytest_args.append("tests/")

    console.print(
        f"[bold]Running {'live integration' if live else 'unit'} tests[/bold]"
        + (f" [dim](provider: {provider or 'config default'})[/dim]" if live else "")
    )
    console.print(f"[dim]{' '.join(pytest_args)}[/dim]\n")

    result = subprocess.run(pytest_args, cwd=str(target))
    raise typer.Exit(code=result.returncode)


def _live_preflight(target: Path, provider: str | None, model: str | None) -> None:
    """Safety checks before running live tests."""
    import os

    # Resolve provider from config if not specified
    effective_provider = provider
    if not effective_provider:
        config_path = target / "productteam.toml"
        if config_path.exists():
            from productteam.config import load_config
            cfg = load_config(config_path)
            effective_provider = cfg.pipeline.provider
        else:
            effective_provider = "anthropic"

    # Check for API key
    env_var = _LIVE_API_KEY_MAP.get(effective_provider, "")
    if env_var:
        key = os.environ.get(env_var, "")
        if not key:
            error_console.print(
                f"[red]Error:[/red] Live tests require {env_var} to be set.\n"
                f"  export {env_var}=sk-..."
            )
            raise typer.Exit(code=1)
        # Mask the key for display
        masked = key[:4] + "..." + key[-4:] if len(key) > 12 else "***"
        console.print(f"[dim]API key:[/dim] {env_var}={masked}")
    elif effective_provider == "ollama":
        console.print("[dim]Provider: ollama (local, no API key needed)[/dim]")

    # Safety warning
    console.print(
        Panel(
            "[bold yellow]Live test warning[/bold yellow]\n\n"
            "This will make real API calls that:\n"
            "  [yellow]$[/yellow]  Cost money (billed to your API key)\n"
            "  [yellow]>[/yellow]  Send test prompts to the provider\n"
            "  [yellow]~[/yellow]  Take 30-120 seconds to complete\n\n"
            "The test suite uses small prompts to minimize cost.\n"
            f"Provider: [bold]{effective_provider}[/bold]"
            + (f"  Model: [bold]{model}[/bold]" if model else ""),
            border_style="yellow",
            title="[bold yellow]API Key Safety[/bold yellow]",
        )
    )

    # Set env vars for live tests to pick up
    if provider:
        os.environ["PRODUCTTEAM_TEST_PROVIDER"] = provider
    if model:
        os.environ["PRODUCTTEAM_TEST_MODEL"] = model


@config_app.command("set")
def config_set(
    key: str = typer.Argument(..., help="Dot-separated key, e.g. 'pipeline.model'"),
    value: str = typer.Argument(..., help="New value"),
) -> None:
    """Set a configuration value in productteam.toml."""
    from productteam.config import find_config, load_config, save_config, set_config_value

    config_path = find_config()
    if config_path is None:
        error_console.print(
            "[yellow]No productteam.toml found.[/yellow] "
            "Run [bold]'productteam init'[/bold] to create one."
        )
        raise typer.Exit(code=1)

    config = load_config(config_path)
    try:
        updated = set_config_value(config, key, value)
    except (KeyError, ValueError) as exc:
        error_console.print(f"[red]Error:[/red] {exc}")
        raise typer.Exit(code=1)

    save_config(updated, config_path)
    console.print(f"[green]OK[/green] Set [bold]{key}[/bold] = [cyan]{value}[/cyan]")


# ---------------------------------------------------------------------------
# productteam forge
# ---------------------------------------------------------------------------


@forge_app.callback(invoke_without_command=True)
def forge_submit(
    ctx: typer.Context,
    concept: Optional[str] = typer.Argument(None, help="Product concept to forge"),
    listen: bool = typer.Option(False, "--listen", help="Start the forge daemon"),
    dashboard: bool = typer.Option(False, "--dashboard", help="Enable status dashboard (with --listen)"),
    lan: bool = typer.Option(False, "--lan", help="Bind dashboard to 0.0.0.0 (accessible from LAN)"),
) -> None:
    """Submit an idea to forge, or start the daemon."""
    if ctx.invoked_subcommand is not None:
        return

    if listen:
        _forge_listen(dashboard, lan=lan)
        return

    if not concept:
        error_console.print("[red]Error:[/red] Provide a concept or use --listen.")
        raise typer.Exit(code=1)

    from productteam.forge.queue import FileQueue

    queue = FileQueue()
    job = queue.enqueue(concept)
    console.print(f"[green]Job submitted:[/green] {job.job_id}")
    console.print(f"[dim]Concept: {concept}[/dim]")
    console.print(f"\nRun [bold]productteam forge --listen[/bold] to process it.")


def _forge_listen(with_dashboard: bool, *, lan: bool = False) -> None:
    """Start the forge daemon."""
    import asyncio

    from productteam.config import find_config, load_config
    from productteam.forge.daemon import ForgeDaemon
    from productteam.forge.queue import FileQueue

    config_path = find_config()
    if config_path is None:
        error_console.print(
            "[yellow]No productteam.toml found.[/yellow] Using defaults."
        )
        from productteam.config import default_config
        config = default_config()
    else:
        config = load_config(config_path)

    queue = FileQueue()

    if with_dashboard:
        from productteam.forge.dashboard import serve_dashboard
        host = "0.0.0.0" if lan else config.forge.status_host
        port = config.forge.status_port
        if lan:
            error_console.print(
                "[yellow]Warning:[/yellow] Dashboard bound to 0.0.0.0 — "
                "accessible to anyone on your network. No authentication."
            )
        serve_dashboard(queue, port=port, host=host)
        if host == "0.0.0.0":
            import socket
            try:
                with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
                    s.connect(("8.8.8.8", 80))
                    local_ip = s.getsockname()[0]
            except OSError:
                local_ip = "your-machine-ip"
            console.print(f"[green]Dashboard:[/green] http://localhost:{port}")
            console.print(f"[green]From phone:[/green] http://{local_ip}:{port}")
        else:
            console.print(f"[green]Dashboard:[/green] http://{host}:{port}")

    console.print("[bold]Forge daemon started.[/bold] Watching for jobs... (Ctrl+C to stop)")

    daemon = ForgeDaemon(config=config, queue=queue)
    try:
        asyncio.run(daemon.run())
    except KeyboardInterrupt:
        daemon.stop()
        console.print("\n[dim]Forge daemon stopped.[/dim]")


@forge_app.command("status")
def forge_status(
    job_id: Optional[str] = typer.Argument(None, help="Job ID for detailed status"),
) -> None:
    """Show forge job status."""
    from productteam.forge.queue import FileQueue

    queue = FileQueue()

    if job_id:
        job = queue.get_job(job_id)
        if job is None:
            error_console.print(f"[red]Job not found:[/red] {job_id}")
            raise typer.Exit(code=1)
        data = job.to_dict()
        for key, val in data.items():
            console.print(f"  [bold]{key}:[/bold] {val}")
        gate = queue.get_gate(job_id)
        if gate:
            console.print(f"\n  [yellow]Gate waiting:[/yellow] {gate.gate_name}")
        return

    jobs = queue.list_jobs()
    if not jobs:
        console.print("[dim]No forge jobs found.[/dim]")
        return

    table = Table(title="Forge Jobs", box=box.ROUNDED)
    table.add_column("ID", style="bold")
    table.add_column("Concept")
    table.add_column("Status")
    table.add_column("Stage")

    status_styles = {
        "queued": "dim",
        "running": "cyan",
        "waiting_gate": "yellow",
        "complete": "green",
        "failed": "red",
    }
    for job in jobs:
        style = status_styles.get(job.status.value, "white")
        table.add_row(
            job.job_id,
            job.concept[:40],
            f"[{style}]{job.status.value}[/{style}]",
            job.current_stage or "-",
        )
    console.print(table)


@forge_app.command("approve")
def forge_approve(
    job_id: str = typer.Argument(..., help="Job ID to approve"),
) -> None:
    """Approve a gate for a forge job."""
    from productteam.forge.queue import FileQueue

    queue = FileQueue()
    job = queue.get_job(job_id)
    if job is None:
        error_console.print(f"[red]Job not found:[/red] {job_id}")
        raise typer.Exit(code=1)
    queue.clear_gate(job_id)
    console.print(f"[green]Approved:[/green] {job_id}")


@forge_app.command("reject")
def forge_reject(
    job_id: str = typer.Argument(..., help="Job ID to reject"),
) -> None:
    """Reject a gate for a forge job."""
    from productteam.forge.queue import FileQueue, JobStatus

    queue = FileQueue()
    job = queue.get_job(job_id)
    if job is None:
        error_console.print(f"[red]Job not found:[/red] {job_id}")
        raise typer.Exit(code=1)
    queue.update_status(job_id, JobStatus.FAILED, error="Rejected by user")
    queue.append_log(job_id, "Job rejected by user.")
    console.print(f"[red]Rejected:[/red] {job_id}")


@forge_app.command("logs")
def forge_logs(
    job_id: str = typer.Argument(..., help="Job ID to view logs for"),
    tail: int = typer.Option(50, "--tail", "-n", help="Number of lines to show"),
) -> None:
    """View logs for a forge job."""
    from productteam.forge.queue import FileQueue

    queue = FileQueue()
    job = queue.get_job(job_id)
    if job is None:
        error_console.print(f"[red]Job not found:[/red] {job_id}")
        raise typer.Exit(code=1)
    log = queue.read_log(job_id, tail=tail)
    if log:
        console.print(log)
    else:
        console.print("[dim]No logs yet.[/dim]")
