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

config_app = typer.Typer(help="Manage productteam.toml configuration.")
app.add_typer(config_app, name="config")

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
        None, "--step", help="Run only a specific stage (prd|plan|build|evaluate|document|ship)"
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
