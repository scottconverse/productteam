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

PIPELINE_STEPS = [
    {
        "number": 1,
        "title": "PRD Writer",
        "instructions": [
            'Tell Claude: "Read the PRD Writer skill at .claude/skills/prd-writer/SKILL.md and write a PRD for: [your concept]"',
        ],
        "gate": "Review and approve the PRD before continuing.",
    },
    {
        "number": 2,
        "title": "Planner",
        "instructions": [
            'Tell Claude: "Read the Planner skill at .claude/skills/planner/SKILL.md and create sprint contracts from the PRD at docs/PRD.md"',
        ],
        "gate": "Review and approve the sprint plan before continuing.",
    },
    {
        "number": 3,
        "title": "Builder + Evaluator Loop",
        "instructions": [
            'Tell Claude: "Read the Builder skill at .claude/skills/builder/SKILL.md and implement sprint-001.yaml"',
            'Then: "Read the Evaluator skill at .claude/skills/evaluator/SKILL.md and evaluate sprint 001"',
            "Loop until PASS (max 3 loops).",
            "Repeat for each sprint.",
        ],
        "gate": None,
    },
    {
        "number": 4,
        "title": "Doc Writer",
        "instructions": [
            'Tell Claude: "Read the Doc Writer skill at .claude/skills/doc-writer/SKILL.md and write documentation"',
        ],
        "gate": None,
    },
    {
        "number": 5,
        "title": "Design Review",
        "instructions": [
            'Tell Claude: "Read the Design Evaluator skill at .claude/skills/evaluator-design/SKILL.md and evaluate all visual artifacts"',
        ],
        "gate": None,
    },
    {
        "number": 6,
        "title": "Ship",
        "instructions": [
            "Run the pre-ship checklist. Commit and push.",
        ],
        "gate": None,
    },
]


def _print_step(step: dict) -> None:
    """Print a single pipeline step to the console."""
    console.print(f"\n[bold cyan]Step {step['number']}: {step['title']}[/bold cyan]")
    for line in step["instructions"]:
        console.print(f"  {line}")
    if step["gate"]:
        console.print(f"  [yellow]Gate:[/yellow] {step['gate']}")


@app.command("run")
def run_cmd(
    directory: Optional[Path] = typer.Argument(
        None, help="Project directory (default: current directory)"
    ),
    step: Optional[int] = typer.Option(
        None, "--step", "-s", help="Print instructions for a single step (1-6)"
    ),
) -> None:
    """Print the ProductTeam pipeline steps to follow in Claude Code."""
    from productteam.config import find_config, load_config
    from productteam.scaffold import read_project_state

    target = (directory or Path.cwd()).resolve()

    # 1. Check .productteam/ exists
    pt_dir = target / ".productteam"
    if not pt_dir.exists():
        error_console.print(
            "[red]Error:[/red] .productteam/ not found. "
            "Run [bold]'productteam init'[/bold] first."
        )
        raise typer.Exit(code=1)

    # 2. Check productteam.toml exists and is valid
    config_path = target / "productteam.toml"
    if not config_path.exists():
        error_console.print(
            "[red]Error:[/red] productteam.toml not found. "
            "Run [bold]'productteam init'[/bold] to create one."
        )
        raise typer.Exit(code=1)

    try:
        load_config(config_path)
    except Exception as exc:
        error_console.print(f"[red]Error:[/red] productteam.toml is invalid: {exc}")
        raise typer.Exit(code=1)

    # --step N: print just one step
    if step is not None:
        matching = [s for s in PIPELINE_STEPS if s["number"] == step]
        if not matching:
            error_console.print(
                f"[red]Error:[/red] Invalid step number {step}. Choose 1-{len(PIPELINE_STEPS)}."
            )
            raise typer.Exit(code=1)
        _print_step(matching[0])
        return

    # 3. Print full pipeline header
    console.print("\n[bold]ProductTeam Pipeline[/bold]")
    console.print("=" * 22)

    for s in PIPELINE_STEPS:
        _print_step(s)

    # 4. Show current pipeline status if state exists
    state = read_project_state(target)
    sprints = state["sprints"]
    evaluations = state["evaluations"]

    if sprints or evaluations:
        console.print("\n[bold]Current Pipeline Status[/bold]")
        console.print("-" * 26)

        if sprints:
            sprint_status_styles = {
                "planned": "blue",
                "building": "yellow",
                "evaluating": "cyan",
                "passed": "green",
                "needs_work": "red",
                "unknown": "dim",
            }
            sprint_table = Table(title="Sprints", box=box.ROUNDED)
            sprint_table.add_column("Sprint", style="bold")
            sprint_table.add_column("Status")
            for sprint in sprints:
                s = sprint["status"]
                style = sprint_status_styles.get(s, "white")
                sprint_table.add_row(sprint["name"], f"[{style}]{s}[/{style}]")
            console.print(sprint_table)

        if evaluations:
            verdict_styles = {
                "passed": "green",
                "needs_work": "red",
                "pending": "yellow",
                "unknown": "dim",
            }
            eval_table = Table(title="Evaluations", box=box.ROUNDED)
            eval_table.add_column("Evaluation", style="bold")
            eval_table.add_column("Verdict")
            for ev in evaluations:
                v = ev["verdict"]
                style = verdict_styles.get(v, "white")
                eval_table.add_row(ev["name"], f"[{style}]{v}[/{style}]")
            console.print(eval_table)


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
