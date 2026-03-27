"""Supervisor: orchestrates the ProductTeam pipeline.

Launches each stage in sequence, enforces approval gates,
manages the build-evaluate loop, writes state, and detects stuck agents.
"""

from __future__ import annotations

import asyncio
import json
import os
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Any, Callable

import yaml

from rich.console import Console
from rich.panel import Panel
from rich.prompt import Prompt

from productteam.models import ProductTeamConfig
from productteam.providers.base import LLMProvider
from productteam.tool_loop import ToolLoopResult, run_tool_loop

console = Console()


class PipelineStage(str, Enum):
    PRD = "prd"
    PLAN = "plan"
    BUILD = "build"
    EVALUATE = "evaluate"
    EVALUATE_DESIGN = "evaluate-design"
    DOCUMENT = "document"
    SHIP = "ship"


class StageResult:
    """Result of running a single pipeline stage."""

    def __init__(
        self,
        stage: PipelineStage,
        status: str,
        artifact_path: str = "",
        raw_response: str = "",
        error: str = "",
        input_tokens: int = 0,
        output_tokens: int = 0,
        cache_creation_input_tokens: int = 0,
        cache_read_input_tokens: int = 0,
    ):
        self.stage = stage
        self.status = status  # "complete" | "stuck" | "failed" | "skipped"
        self.artifact_path = artifact_path
        self.raw_response = raw_response
        self.error = error
        self.input_tokens = input_tokens
        self.output_tokens = output_tokens
        self.cache_creation_input_tokens = cache_creation_input_tokens
        self.cache_read_input_tokens = cache_read_input_tokens


# Pricing per million tokens (update as providers change pricing)
_PROVIDER_PRICING = {
    "claude-haiku-4-5-20251001": {"input": 0.80, "output": 4.00},
    "claude-sonnet-4-6":         {"input": 3.00, "output": 15.00},
    "claude-sonnet-4-20250514":  {"input": 3.00, "output": 15.00},
    "gpt-4o":                    {"input": 2.50, "output": 10.00},
    "gpt-4o-mini":               {"input": 0.15, "output": 0.60},
}


class SupervisorResult:
    """Result of a full pipeline run."""

    def __init__(
        self,
        concept: str,
        stages: list[StageResult],
        status: str,
    ):
        self.concept = concept
        self.stages = stages
        self.status = status  # "complete" | "stuck" | "failed" | "partial"

    def token_summary(self, model_id: str = "") -> dict:
        """Return token usage and estimated cost across all stages."""
        total_input = sum(s.input_tokens for s in self.stages)
        total_output = sum(s.output_tokens for s in self.stages)
        total_cache_creation = sum(s.cache_creation_input_tokens for s in self.stages)
        total_cache_read = sum(s.cache_read_input_tokens for s in self.stages)

        pricing = _PROVIDER_PRICING.get(model_id, {})
        est_cost = None
        if pricing:
            est_cost = (
                total_input / 1_000_000 * pricing["input"]
                + total_output / 1_000_000 * pricing["output"]
            )

        return {
            "total_input_tokens": total_input,
            "total_output_tokens": total_output,
            "cache_creation_input_tokens": total_cache_creation,
            "cache_read_input_tokens": total_cache_read,
            "est_cost_usd": round(est_cost, 4) if est_cost is not None else None,
            "by_stage": [
                {
                    "stage": s.stage.value,
                    "input_tokens": s.input_tokens,
                    "output_tokens": s.output_tokens,
                    "cache_creation_input_tokens": s.cache_creation_input_tokens,
                    "cache_read_input_tokens": s.cache_read_input_tokens,
                }
                for s in self.stages
            ],
        }


SCHEMA_VERSION = 1


def _load_state(project_dir: Path) -> dict:
    """Load state.json or return default state."""
    state_path = project_dir / ".productteam" / "state.json"
    if state_path.exists():
        state = json.loads(state_path.read_text(encoding="utf-8"))
        version = state.get("schema_version", 0)
        if version != SCHEMA_VERSION:
            raise ValueError(
                f"state.json schema version {version} is not supported (expected {SCHEMA_VERSION}). "
                "Delete .productteam/state.json to start fresh."
            )
        return state
    return {
        "schema_version": 1,
        "pipeline_phase": "planning",
        "concept": "",
        "created_at": "",
        "updated_at": "",
        "stages": {},
    }


def _save_state(project_dir: Path, state: dict) -> None:
    """Write state.json."""
    state["updated_at"] = datetime.now(timezone.utc).isoformat()
    state_path = project_dir / ".productteam" / "state.json"
    state_path.parent.mkdir(parents=True, exist_ok=True)
    state_path.write_text(json.dumps(state, indent=2), encoding="utf-8")


def _load_skill(project_dir: Path, skill_name: str, skills_dir: str = ".claude/skills") -> str:
    """Load a SKILL.md file content."""
    skill_path = project_dir / skills_dir / skill_name / "SKILL.md"
    if not skill_path.exists():
        raise FileNotFoundError(
            f"Skill not found: {skill_path}\n"
            f"Check that skills are installed (run 'productteam init') "
            f"or update 'skills_dir' in productteam.toml."
        )
    return skill_path.read_text(encoding="utf-8")


def _is_stage_complete(state: dict, stage_name: str) -> bool:
    """Check if a stage is already complete in state."""
    stage_info = state.get("stages", {}).get(stage_name, {})
    return stage_info.get("status") == "complete"


def _is_sprint_passed(state: dict, sprint_name: str) -> bool:
    """Check if a sprint has already passed evaluation."""
    eval_info = state.get("stages", {}).get("evaluate", {})
    if eval_info.get("sprint") == sprint_name and eval_info.get("status") == "complete":
        return True
    # Also check for per-sprint status
    sprint_info = state.get("stages", {}).get(f"build:{sprint_name}", {})
    return sprint_info.get("status") == "passed"


class Supervisor:
    """Orchestrates the ProductTeam pipeline."""

    def __init__(
        self,
        project_dir: Path,
        config: ProductTeamConfig,
        provider: LLMProvider | None,
        auto_approve: bool = False,
    ):
        self.project_dir = project_dir
        self.config = config
        self.provider = provider
        self.auto_approve = auto_approve
        self.state = _load_state(project_dir)

    def _setup_project_env(self) -> None:
        """Create venv and install project dependencies before agent stages run.

        Runs once per pipeline invocation. Agents should not need to install
        dependencies — that wastes tool calls. This method does it for them.
        Does not raise — failures are logged but do not stop the pipeline,
        since the project may not have installable dependencies yet.
        """
        import subprocess
        import sys

        venv_dir = self.project_dir / ".venv"

        # Create venv if it doesn't exist
        if not venv_dir.exists():
            console.print("[dim]Creating virtual environment...[/dim]")
            try:
                subprocess.run(
                    [sys.executable, "-m", "venv", str(venv_dir)],
                    cwd=str(self.project_dir),
                    capture_output=True,
                    timeout=60,
                )
            except Exception as e:
                console.print(f"[dim]venv creation failed (non-fatal): {e}[/dim]")
                return

        # Determine pip executable
        if os.name == "nt":
            pip = venv_dir / "Scripts" / "pip"
        else:
            pip = venv_dir / "bin" / "pip"

        if not pip.exists():
            return

        # Install from pyproject.toml if present
        if (self.project_dir / "pyproject.toml").exists():
            console.print("[dim]Installing project dependencies (pip install -e .)...[/dim]")
            try:
                result = subprocess.run(
                    [str(pip), "install", "-e", ".", "--quiet"],
                    cwd=str(self.project_dir),
                    capture_output=True,
                    text=True,
                    timeout=120,
                )
                if result.returncode == 0:
                    console.print("[dim]Dependencies installed.[/dim]")
                else:
                    console.print(f"[dim]pip install failed (non-fatal): {result.stderr[:200]}[/dim]")
            except Exception as e:
                console.print(f"[dim]pip install failed (non-fatal): {e}[/dim]")
            return

        # Fall back to requirements.txt
        req_file = self.project_dir / "requirements.txt"
        if req_file.exists():
            console.print("[dim]Installing requirements.txt...[/dim]")
            try:
                subprocess.run(
                    [str(pip), "install", "-r", "requirements.txt", "--quiet"],
                    cwd=str(self.project_dir),
                    capture_output=True,
                    timeout=120,
                )
            except Exception as e:
                console.print(f"[dim]pip install -r failed (non-fatal): {e}[/dim]")

    async def run(
        self,
        concept: str = "",
        step: str | None = None,
        sprint: str | None = None,
        rebuild: bool = False,
        dry_run: bool = False,
        stage_callback: "Callable[[str], None] | None" = None,
    ) -> SupervisorResult:
        """Run the full pipeline or a single step.

        Args:
            concept: Product concept string. Required for fresh run.
            step: If set, run only this stage.
            sprint: Target sprint (with step=build or evaluate).
            rebuild: Force rebuild even if passed.
            dry_run: Show what would happen without calling LLM.
            stage_callback: Called with stage name when each stage starts.
        """
        self._stage_callback = stage_callback
        stages: list[StageResult] = []

        # Resume or fresh start
        if concept:
            self.state["concept"] = concept
            self.state["created_at"] = datetime.now(timezone.utc).isoformat()
            _save_state(self.project_dir, self.state)
        elif not self.state.get("concept"):
            return SupervisorResult(
                concept="",
                stages=[],
                status="failed",
            )

        concept = self.state["concept"]

        if dry_run:
            # Estimate based on typical token usage per stage
            STAGE_ESTIMATES = {
                "prd":              {"input": 15_000,  "output": 3_000},
                "plan":             {"input": 40_000,  "output": 8_000},
                "build_per_sprint": {"input": 120_000, "output": 15_000},
                "eval_per_sprint":  {"input": 60_000,  "output": 8_000},
                "document":         {"input": 80_000,  "output": 10_000},
                "evaluate_design":  {"input": 40_000,  "output": 5_000},
            }

            concept_words = len(concept.split())
            est_sprints = max(1, min(6, concept_words // 30))

            total_input = (
                STAGE_ESTIMATES["prd"]["input"]
                + STAGE_ESTIMATES["plan"]["input"]
                + (STAGE_ESTIMATES["build_per_sprint"]["input"] * est_sprints)
                + (STAGE_ESTIMATES["eval_per_sprint"]["input"] * est_sprints)
                + STAGE_ESTIMATES["document"]["input"]
                + STAGE_ESTIMATES["evaluate_design"]["input"]
            )
            total_output = (
                STAGE_ESTIMATES["prd"]["output"]
                + STAGE_ESTIMATES["plan"]["output"]
                + (STAGE_ESTIMATES["build_per_sprint"]["output"] * est_sprints)
                + (STAGE_ESTIMATES["eval_per_sprint"]["output"] * est_sprints)
                + STAGE_ESTIMATES["document"]["output"]
                + STAGE_ESTIMATES["evaluate_design"]["output"]
            )

            console.print("[dim]Dry run — no LLM calls will be made[/dim]")
            console.print(f"\n[bold]Estimated pipeline for:[/bold] {concept[:60]}...")
            console.print(f"  Estimated sprints: {est_sprints}")
            console.print(f"  Estimated tokens:  {total_input:,} input / {total_output:,} output")
            console.print()
            console.print("  [bold]Estimated cost by model:[/bold]")
            for model_name, pricing in _PROVIDER_PRICING.items():
                cost = (total_input / 1e6 * pricing["input"]) + (total_output / 1e6 * pricing["output"])
                console.print(f"    {model_name:<40} ${cost:.3f}")
            console.print()
            console.print("  [dim]Note: Estimates are rough. Complex concepts cost more.[/dim]")
            console.print("  [dim]Use quality=standard (default) to minimize cost.[/dim]")

            return SupervisorResult(concept=concept, stages=[], status="complete")

        # Set up project environment once for the whole pipeline
        self._setup_project_env()

        # Single step mode
        if step:
            result = await self._run_single_step(step, sprint, rebuild)
            stages.append(result)
            return SupervisorResult(
                concept=concept,
                stages=stages,
                status=result.status,
            )

        # Full pipeline
        # 1. PRD
        if not _is_stage_complete(self.state, "prd") or rebuild:
            result = await self._run_thinker_stage(
                PipelineStage.PRD, "prd-writer", concept
            )
            stages.append(result)
            if result.status != "complete":
                return SupervisorResult(concept=concept, stages=stages, status="stuck")

            # PRD gate
            if self.config.gates.prd_approval:
                if not await self._gate("PRD Approval", result.artifact_path):
                    return SupervisorResult(concept=concept, stages=stages, status="partial")

        # 2. Plan (doer — writes sprint YAML files to .productteam/sprints/)
        if not _is_stage_complete(self.state, "plan") or rebuild:
            prd_content = self._read_artifact("prd")
            max_sprints = self.config.pipeline.max_sprints
            plan_context = (
                f"{prd_content}\n\n"
                f"--- Pipeline constraint ---\n"
                f"Produce at most {max_sprints} sprint contracts. "
                f"If the PRD describes more work than fits in {max_sprints} sprints, "
                f"prioritize the most critical features and note what was deferred."
            )
            result = await self._run_tool_loop_stage(
                PipelineStage.PLAN, "planner", plan_context,
                timeout_seconds=self.config.pipeline.planner_timeout_seconds,
            )
            stages.append(result)
            if result.status != "complete":
                return SupervisorResult(concept=concept, stages=stages, status="stuck")

            # Sprint plan gate
            if self.config.gates.sprint_approval:
                if not await self._gate("Sprint Plan Approval", result.artifact_path):
                    return SupervisorResult(concept=concept, stages=stages, status="partial")

        # 3. Build + Evaluate loop
        sprints = self._find_sprints()
        if not sprints:
            if _is_stage_complete(self.state, "plan"):
                console.print(
                    "[bold red]Pipeline error:[/bold red] Plan stage completed but no sprint "
                    "contract YAML files were found in .productteam/sprints/. "
                    "The Planner did not write sprint files to disk. "
                    "Check .productteam/plan.md for what the Planner produced."
                )
                return SupervisorResult(concept=concept, stages=stages, status="failed")
            else:
                console.print("[yellow]No sprints found and plan not complete — skipping build.[/yellow]")
        for sprint_name in sprints:
            if _is_sprint_passed(self.state, sprint_name) and not rebuild:
                console.print(f"[dim]{sprint_name}: already passed, skipping[/dim]")
                continue

            result = await self._build_evaluate_loop(sprint_name)
            stages.append(result)
            if result.status not in ("complete", "skipped"):
                return SupervisorResult(concept=concept, stages=stages, status="stuck")

        # Only run Doc Writer if at least one sprint passed
        passed_sprints = [s for s in sprints if _is_sprint_passed(self.state, s)]
        if not passed_sprints:
            console.print(
                "[yellow]Skipping documentation — no sprints have passed evaluation.[/yellow]"
            )
            return SupervisorResult(concept=concept, stages=stages, status="stuck")

        # 4. Document
        if not _is_stage_complete(self.state, "document") or rebuild:
            file_listing = self._project_file_listing()
            doc_context = (
                f"Write documentation for the project.\n\n"
                f"Concept: {concept}\n\n"
                f"All tools operate relative to the project root. "
                f"Use relative paths (e.g., 'src/main.py', not '/tmp/src/main.py'). "
                f"Start by reading existing source files listed below.\n\n"
                f"Project files:\n{file_listing}"
            )
            result = await self._run_tool_loop_stage(
                PipelineStage.DOCUMENT, "doc-writer",
                doc_context,
                max_tool_calls=self.config.pipeline.doc_writer_max_tool_calls,
            )
            stages.append(result)

        # 4b. Design Evaluation (single pass — no retry loop because there is
        # no mechanism to route back to Doc Writer/UI Builder to fix issues)
        if self.config.pipeline.require_design_review:
            if not _is_stage_complete(self.state, "evaluate-design") or rebuild:
                result = await self._run_tool_loop_stage(
                    PipelineStage.EVALUATE_DESIGN, "evaluator-design",
                    f"Quality level: {self.config.pipeline.quality}\n\n"
                    f"Evaluate design quality. Read docs/index.html, docs/terms.html, "
                    f"and README.md. Concept: {concept}",
                )
                stages.append(result)

                verdict = self._parse_verdict(result.raw_response or "")
                if verdict == "needs_work":
                    # Fallback: check eval YAML files written to disk by the
                    # design evaluator via write_file (same pattern as build eval)
                    eval_dir = self.project_dir / ".productteam" / "evaluations"
                    for eval_file in sorted(eval_dir.glob("eval-*-design.yaml"), reverse=True):
                        try:
                            file_verdict = self._parse_verdict(
                                eval_file.read_text(encoding="utf-8")
                            )
                            if file_verdict in ("pass", "fail"):
                                verdict = file_verdict
                                console.print(f"  [dim](verdict from {eval_file.name})[/dim]")
                                break
                        except Exception:
                            continue
                console.print(f"  Design verdict: [{'green' if verdict == 'pass' else 'red'}]{verdict}[/]")
                if verdict != "pass":
                    console.print(
                        f"[red]Design evaluation returned {verdict.upper()}.[/red] "
                        "Re-run doc-writer (--step document) then re-run design eval."
                    )
                    return SupervisorResult(concept=concept, stages=stages, status="stuck")

        # 5. Ship gate
        if self.config.gates.ship_approval:
            if not await self._gate("Ship Approval", ""):
                return SupervisorResult(concept=concept, stages=stages, status="partial")

        self.state["pipeline_phase"] = "shipping"
        _save_state(self.project_dir, self.state)

        return SupervisorResult(concept=concept, stages=stages, status="complete")

    async def _run_single_step(
        self, step: str, sprint: str | None, rebuild: bool
    ) -> StageResult:
        """Run a single pipeline step."""
        stage = PipelineStage(step)
        concept = self.state.get("concept", "")

        if stage == PipelineStage.PRD:
            return await self._run_thinker_stage(stage, "prd-writer", concept)
        elif stage == PipelineStage.PLAN:
            prd_content = self._read_artifact("prd")
            return await self._run_tool_loop_stage(
                stage, "planner", prd_content,
                timeout_seconds=self.config.pipeline.planner_timeout_seconds,
            )
        elif stage == PipelineStage.BUILD:
            sprints = self._find_sprints()
            sprint_name = sprint or (sprints[0] if sprints else "sprint-001")
            return await self._build_evaluate_loop(sprint_name)
        elif stage == PipelineStage.EVALUATE:
            sprints = self._find_sprints()
            sprint_name = sprint or (sprints[-1] if sprints else "sprint-001")
            return await self._run_tool_loop_stage(
                stage, "evaluator",
                f"Evaluate sprint {sprint_name}",
            )
        elif stage == PipelineStage.DOCUMENT:
            file_listing = self._project_file_listing()
            doc_context = (
                f"Write documentation for the project.\n\n"
                f"Concept: {concept}\n\n"
                f"All tools operate relative to the project root. "
                f"Use relative paths (e.g., 'src/main.py', not '/tmp/src/main.py'). "
                f"Start by reading existing source files listed below.\n\n"
                f"Project files:\n{file_listing}"
            )
            return await self._run_tool_loop_stage(
                stage, "doc-writer",
                doc_context,
                max_tool_calls=self.config.pipeline.doc_writer_max_tool_calls,
            )
        elif stage == PipelineStage.EVALUATE_DESIGN:
            return await self._run_tool_loop_stage(
                stage, "evaluator-design",
                f"Quality level: {self.config.pipeline.quality}\n\n"
                f"Evaluate design quality. Read docs/index.html, docs/terms.html, "
                f"and README.md. Concept: {concept}",
                max_tool_calls=self.config.pipeline.evaluator_max_tool_calls,
            )
        else:
            return StageResult(stage=stage, status="skipped")

    def _project_file_listing(self, max_files: int = 100) -> str:
        """Return a compact listing of project files for context."""
        lines = []
        count = 0
        for item in sorted(self.project_dir.rglob("*")):
            if count >= max_files:
                lines.append(f"... ({count}+ files, truncated)")
                break
            rel = item.relative_to(self.project_dir)
            parts = rel.parts
            # Skip hidden dirs (except .productteam/sprints), __pycache__, .venv
            if any(p.startswith(".") and p not in (".productteam",) for p in parts):
                continue
            if any(p in ("__pycache__", ".venv", "node_modules", ".git") for p in parts):
                continue
            if item.is_file():
                lines.append(str(rel))
                count += 1
        return "\n".join(lines) if lines else "(empty project)"

    def _notify_stage(self, stage_name: str) -> None:
        """Fire the stage callback if one was set."""
        cb = getattr(self, "_stage_callback", None)
        if cb:
            cb(stage_name)

    async def _run_thinker_stage(
        self,
        stage: PipelineStage,
        skill_name: str,
        context: str,
    ) -> StageResult:
        """Run a thinker stage (single LLM call)."""
        self._notify_stage(stage.value)
        console.print(f"\n[bold cyan]Running: {stage.value}[/bold cyan]")

        try:
            system_prompt = _load_skill(self.project_dir, skill_name, self.config.pipeline.skills_dir)
        except FileNotFoundError as e:
            return StageResult(stage=stage, status="failed", error=str(e))

        self.state["pipeline_phase"] = stage.value
        self.state.setdefault("stages", {})[stage.value] = {"status": "running"}
        _save_state(self.project_dir, self.state)

        try:
            response, usage = await asyncio.wait_for(
                self.provider.complete(
                    system=system_prompt,
                    messages=[{"role": "user", "content": context}],
                ),
                timeout=self.config.pipeline.stage_timeout_seconds,
            )
        except asyncio.TimeoutError:
            self.state["stages"][stage.value] = {"status": "stuck"}
            _save_state(self.project_dir, self.state)
            console.print(f"[red]Stage {stage.value} timed out[/red]")
            return StageResult(stage=stage, status="stuck", error="Timed out")
        except Exception as e:
            self.state["stages"][stage.value] = {"status": "failed"}
            _save_state(self.project_dir, self.state)
            return StageResult(stage=stage, status="failed", error=str(e))

        # Write artifact
        artifact_path = self._write_artifact(stage, response)

        self.state["stages"][stage.value] = {
            "status": "complete",
            "artifact": artifact_path,
        }
        _save_state(self.project_dir, self.state)

        console.print(f"[green]Stage {stage.value} complete[/green]")
        return StageResult(
            stage=stage,
            status="complete",
            artifact_path=artifact_path,
            raw_response=response,
            input_tokens=usage.get("input_tokens", 0),
            output_tokens=usage.get("output_tokens", 0),
        )

    async def _run_tool_loop_stage(
        self,
        stage: PipelineStage,
        skill_name: str,
        context: str,
        timeout_seconds: float | None = None,
        max_tool_calls: int | None = None,
    ) -> StageResult:
        """Run a doer stage (tool loop with file access)."""
        self._notify_stage(stage.value)
        console.print(f"\n[bold cyan]Running: {stage.value} (tool loop)[/bold cyan]")

        try:
            system_prompt = _load_skill(self.project_dir, skill_name, self.config.pipeline.skills_dir)
        except FileNotFoundError as e:
            return StageResult(stage=stage, status="failed", error=str(e))

        self.state["pipeline_phase"] = stage.value
        self.state.setdefault("stages", {})[stage.value] = {"status": "running"}
        _save_state(self.project_dir, self.state)

        effective_timeout = timeout_seconds or self.config.pipeline.builder_timeout_seconds
        effective_max_calls = max_tool_calls or self.config.pipeline.builder_max_tool_calls

        # Per-stage loop detection windows:
        # - Doc writer reads many files, needs wider window to avoid false positives
        # - Evaluator is structured — 3 identical calls genuinely means stuck
        # - Default of 5 for builder and other stages
        if stage == PipelineStage.DOCUMENT:
            window = 8
        elif stage in (PipelineStage.EVALUATE, PipelineStage.EVALUATE_DESIGN):
            window = 3
        else:
            window = 5

        result = await run_tool_loop(
            provider=self.provider,
            system_prompt=system_prompt,
            initial_user_message=context,
            project_dir=self.project_dir,
            max_tool_calls=effective_max_calls,
            timeout_seconds=effective_timeout,
            loop_detection_window=window,
        )

        if result.status in ("stuck", "max_calls"):
            self.state["stages"][stage.value] = {"status": "stuck"}
            _save_state(self.project_dir, self.state)
            console.print(f"[red]Stage {stage.value} stuck: {result.final_text}[/red]")
            return StageResult(
                stage=stage,
                status="stuck",
                error=result.final_text,
                input_tokens=result.input_tokens,
                output_tokens=result.output_tokens,
                cache_creation_input_tokens=result.cache_creation_input_tokens,
                cache_read_input_tokens=result.cache_read_input_tokens,
            )

        # Write artifact
        artifact_path = self._write_artifact(stage, result.final_text)

        self.state["stages"][stage.value] = {
            "status": "complete",
            "artifact": artifact_path,
        }
        _save_state(self.project_dir, self.state)

        console.print(f"[green]Stage {stage.value} complete[/green]")
        return StageResult(
            stage=stage,
            status="complete",
            artifact_path=artifact_path,
            raw_response=result.final_text,
            input_tokens=result.input_tokens,
            output_tokens=result.output_tokens,
            cache_creation_input_tokens=result.cache_creation_input_tokens,
            cache_read_input_tokens=result.cache_read_input_tokens,
        )

    async def _build_evaluate_loop(self, sprint_name: str) -> StageResult:
        """Run build-evaluate loop for a sprint."""
        max_loops = self.config.pipeline.max_loops
        console.print(f"\n[bold yellow]Build-Evaluate: {sprint_name}[/bold yellow]")

        # Set up project environment before agents run
        self._setup_project_env()

        total_input_tokens = 0
        total_output_tokens = 0
        total_cache_creation = 0
        total_cache_read = 0

        # Load sprint contract
        sprint_path = self.project_dir / ".productteam" / "sprints" / f"{sprint_name}.yaml"
        if not sprint_path.exists():
            # Try as directory
            sprint_path = self.project_dir / ".productteam" / "sprints" / sprint_name / "sprint-contract.yaml"
        if not sprint_path.exists():
            return StageResult(
                stage=PipelineStage.BUILD,
                status="failed",
                error=f"Sprint contract not found: {sprint_name}",
            )

        sprint_contract = sprint_path.read_text(encoding="utf-8")
        last_eval_feedback: str = ""

        for loop_num in range(1, max_loops + 1):
            console.print(f"  [dim]Loop {loop_num}/{max_loops}[/dim]")

            # Build
            self.state.setdefault("stages", {})["build"] = {
                "status": "running",
                "sprint": sprint_name,
                "loop": loop_num,
            }
            _save_state(self.project_dir, self.state)

            try:
                system_prompt = _load_skill(self.project_dir, "builder", self.config.pipeline.skills_dir)
            except FileNotFoundError as e:
                return StageResult(
                    stage=PipelineStage.BUILD, status="failed", error=str(e)
                )

            build_prompt = (
                f"Implement the following sprint contract:\n\n"
                f"{sprint_contract}\n\n"
                f"This is loop {loop_num} of {max_loops}."
            )
            if last_eval_feedback:
                build_prompt += (
                    f"\n\n--- EVALUATOR FEEDBACK FROM PREVIOUS LOOP ---\n"
                    f"Fix these issues:\n\n{last_eval_feedback}"
                )

            build_result = await run_tool_loop(
                provider=self.provider,
                system_prompt=system_prompt,
                initial_user_message=build_prompt,
                project_dir=self.project_dir,
                max_tool_calls=self.config.pipeline.builder_max_tool_calls,
                timeout_seconds=self.config.pipeline.builder_timeout_seconds,
            )

            total_input_tokens += build_result.input_tokens
            total_output_tokens += build_result.output_tokens
            total_cache_creation += build_result.cache_creation_input_tokens
            total_cache_read += build_result.cache_read_input_tokens

            if build_result.status in ("stuck", "max_calls"):
                # Don't terminate — let the evaluator assess what was built.
                # The builder may have written enough code before hitting the limit.
                console.print(f"  [yellow]Builder {build_result.status}: proceeding to evaluation[/yellow]")

            # Write build artifact
            artifact_dir = self.project_dir / ".productteam" / "sprints" / sprint_name
            artifact_dir.mkdir(parents=True, exist_ok=True)
            build_artifact = artifact_dir / "build-artifact.md"
            build_artifact.write_text(build_result.final_text, encoding="utf-8")

            # Skip evaluation if disabled
            if not self.config.pipeline.require_evaluator:
                console.print("  [dim]Evaluator disabled — auto-passing[/dim]")
                self.state["stages"][f"build:{sprint_name}"] = {"status": "passed"}
                _save_state(self.project_dir, self.state)
                return StageResult(
                    stage=PipelineStage.BUILD,
                    status="complete",
                    artifact_path=str(build_artifact),
                    input_tokens=total_input_tokens,
                    output_tokens=total_output_tokens,
                    cache_creation_input_tokens=total_cache_creation,
                    cache_read_input_tokens=total_cache_read,
                )

            # Evaluate
            self.state["stages"]["evaluate"] = {
                "status": "running",
                "sprint": sprint_name,
                "loop": loop_num,
            }
            _save_state(self.project_dir, self.state)

            try:
                eval_system = _load_skill(self.project_dir, "evaluator", self.config.pipeline.skills_dir)
            except FileNotFoundError as e:
                return StageResult(
                    stage=PipelineStage.EVALUATE, status="failed", error=str(e)
                )

            eval_prompt = (
                f"Quality level: {self.config.pipeline.quality}\n\n"
                f"Evaluate sprint {sprint_name} (loop {loop_num}/{max_loops}).\n\n"
                f"Sprint contract:\n{sprint_contract}\n\n"
                f"Builder output:\n{build_result.final_text}"
            )

            eval_result = await run_tool_loop(
                provider=self.provider,
                system_prompt=eval_system,
                initial_user_message=eval_prompt,
                project_dir=self.project_dir,
                max_tool_calls=self.config.pipeline.evaluator_max_tool_calls,
                timeout_seconds=self.config.pipeline.builder_timeout_seconds,
            )

            total_input_tokens += eval_result.input_tokens
            total_output_tokens += eval_result.output_tokens
            total_cache_creation += eval_result.cache_creation_input_tokens
            total_cache_read += eval_result.cache_read_input_tokens

            if eval_result.status == "stuck":
                console.print(f"  [red]Evaluator stuck: {eval_result.final_text}[/red]")
                continue

            eval_response = eval_result.final_text

            # Write evaluation
            eval_path = (
                self.project_dir / ".productteam" / "evaluations"
                / f"{sprint_name}-eval-{loop_num:03d}.yaml"
            )
            eval_path.parent.mkdir(parents=True, exist_ok=True)
            eval_path.write_text(eval_response, encoding="utf-8")

            # Check verdict — try the model's text response first,
            # then check eval YAML files the Evaluator wrote via write_file
            # Parse verdict: check evaluator-written YAML files first,
            # then fall back to the evaluator's text response.
            # The evaluator often writes NEEDS_WORK in early YAML during analysis
            # but concludes PASS in its final text. The text response is the
            # final conclusion; YAML files are working documents.
            verdict = "needs_work"

            # 1. Check evaluator-written YAML files on disk
            eval_dir = self.project_dir / ".productteam" / "evaluations"
            sprint_num = sprint_name.split("-")[-1]  # "001" from "sprint-001"
            candidates = list(eval_dir.glob(f"eval-{sprint_num}*.yaml"))
            candidates += list(eval_dir.glob(f"{sprint_name}-eval-*.yaml"))
            candidates = [f for f in candidates if f != eval_path]
            for eval_file in sorted(candidates, reverse=True):
                try:
                    file_content = eval_file.read_text(encoding="utf-8")
                    file_verdict = self._parse_verdict(file_content)
                    if file_verdict in ("pass", "fail"):
                        verdict = file_verdict
                        console.print(f"  [dim](verdict from {eval_file.name})[/dim]")
                        break
                except Exception:
                    continue

            # 2. Text response overrides YAML if it contains a clear verdict.
            # This handles the case where the evaluator writes NEEDS_WORK
            # in its YAML early, then concludes PASS in its final text.
            text_verdict = self._parse_verdict(eval_response)
            if text_verdict in ("pass", "fail"):
                verdict = text_verdict
            console.print(f"  Verdict: [{'green' if verdict == 'pass' else 'red'}]{verdict}[/]")

            if verdict == "pass":
                self.state["stages"]["evaluate"] = {
                    "status": "complete",
                    "sprint": sprint_name,
                    "loop": loop_num,
                }
                self.state["stages"][f"build:{sprint_name}"] = {"status": "passed"}
                _save_state(self.project_dir, self.state)
                return StageResult(
                    stage=PipelineStage.BUILD,
                    status="complete",
                    artifact_path=str(build_artifact),
                    input_tokens=total_input_tokens,
                    output_tokens=total_output_tokens,
                    cache_creation_input_tokens=total_cache_creation,
                    cache_read_input_tokens=total_cache_read,
                )

            if verdict == "fail":
                console.print(f"  [red]Sprint {sprint_name} FAILED — escalating[/red]")
                self.state["stages"]["evaluate"]["status"] = "failed"
                _save_state(self.project_dir, self.state)
                return StageResult(
                    stage=PipelineStage.BUILD,
                    status="failed",
                    error=f"Evaluator returned FAIL on loop {loop_num}",
                    raw_response=eval_response,
                    input_tokens=total_input_tokens,
                    output_tokens=total_output_tokens,
                    cache_creation_input_tokens=total_cache_creation,
                    cache_read_input_tokens=total_cache_read,
                )

            # NEEDS_WORK — continue loop with feedback for builder
            last_eval_feedback = eval_response[-3000:]  # Last 3KB of evaluator output

        # Exhausted all loops
        console.print(f"  [red]Max loops ({max_loops}) exhausted for {sprint_name}[/red]")
        self.state["stages"]["evaluate"] = {
            "status": "needs_work",
            "sprint": sprint_name,
            "loop": max_loops,
        }
        _save_state(self.project_dir, self.state)
        return StageResult(
            stage=PipelineStage.BUILD,
            status="stuck",
            error=f"Max loops ({max_loops}) exhausted",
            input_tokens=total_input_tokens,
            output_tokens=total_output_tokens,
            cache_creation_input_tokens=total_cache_creation,
            cache_read_input_tokens=total_cache_read,
        )

    async def _gate(self, gate_name: str, artifact_path: str) -> bool:
        """Request gate approval. Returns True if approved."""
        if self.auto_approve:
            console.print(f"[dim]Auto-approved: {gate_name}[/dim]")
            return True

        console.print(
            Panel(
                f"[bold]{gate_name}[/bold]\n"
                + (f"Artifact: {artifact_path}" if artifact_path else ""),
                border_style="yellow",
            )
        )

        while True:
            choice = Prompt.ask("Approve?", choices=["y", "n", "edit"], default="y")
            if choice == "y":
                return True
            elif choice == "n":
                console.print("[yellow]Pipeline paused. State saved.[/yellow]")
                _save_state(self.project_dir, self.state)
                return False
            elif choice == "edit":
                if artifact_path:
                    editor = os.environ.get("EDITOR", "notepad" if os.name == "nt" else "vi")
                    proc = await asyncio.create_subprocess_exec(editor, artifact_path)
                    await proc.wait()
                    console.print("[dim]Re-read artifact after editing[/dim]")
                else:
                    console.print("[dim]No artifact to edit[/dim]")

    def _write_artifact(self, stage: PipelineStage, content: str) -> str:
        """Write a stage artifact to the appropriate directory."""
        pt_dir = self.project_dir / ".productteam"

        if stage == PipelineStage.PRD:
            path = pt_dir / "prds" / "prd-v1.md"
        elif stage == PipelineStage.PLAN:
            path = pt_dir / "plan.md"
        elif stage == PipelineStage.DOCUMENT:
            path = pt_dir / "docs" / "documentation.md"
        elif stage == PipelineStage.EVALUATE:
            path = pt_dir / "evaluations" / f"eval-{stage.value}.yaml"
        else:
            path = pt_dir / f"{stage.value}-output.md"

        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
        return str(path.relative_to(self.project_dir))

    def _read_artifact(self, stage_name: str) -> str:
        """Read a previously written artifact."""
        stage_info = self.state.get("stages", {}).get(stage_name, {})
        artifact_rel = stage_info.get("artifact", "")
        if not artifact_rel:
            console.print(f"[yellow]Warning: no artifact path recorded for stage '{stage_name}'[/yellow]")
            return ""
        artifact_path = self.project_dir / artifact_rel
        if not artifact_path.exists():
            console.print(f"[yellow]Warning: artifact file missing: {artifact_path}[/yellow]")
            return ""
        return artifact_path.read_text(encoding="utf-8")

    def _find_sprints(self) -> list[str]:
        """Find all sprint contract files."""
        sprints_dir = self.project_dir / ".productteam" / "sprints"
        if not sprints_dir.exists():
            return []
        sprints = []
        for item in sorted(sprints_dir.iterdir()):
            if item.suffix in (".yaml", ".yml"):
                sprints.append(item.stem)
        return sprints

    def _summarize_eval_feedback(self, eval_response: str, loop_num: int) -> str:
        """Extract actionable findings from an evaluation report.

        Returns failed acceptance criteria and CRITICAL/HIGH/MEDIUM findings
        to keep the Builder's context window focused on what needs fixing.
        LOW findings are excluded — they rarely drive a NEEDS_WORK verdict.
        """
        try:
            data = yaml.safe_load(eval_response)
            if isinstance(data, dict):
                lines = [f"--- Evaluator feedback (loop {loop_num}) ---"]
                for crit in data.get("acceptance_criteria", []):
                    if str(crit.get("status", "")).upper() == "FAIL":
                        lines.append(
                            f"FAIL: {crit.get('criterion', '')} — {crit.get('evidence', '')}"
                        )
                for finding in data.get("additional_findings", []):
                    if finding.get("severity", "") in ("CRITICAL", "HIGH", "MEDIUM"):
                        lines.append(
                            f"{finding['severity']}: {finding.get('finding', '')} "
                            f"— {finding.get('suggestion', '')}"
                        )
                if data.get("summary"):
                    lines.append(f"Summary: {data['summary'].strip()}")
                if len(lines) > 1:  # more than just the header
                    return "\n".join(lines)
        except Exception:
            pass
        # Fallback: truncate raw response to 2000 chars
        return f"--- Evaluator feedback (loop {loop_num}) ---\n{eval_response[:2000]}"

    def _parse_verdict(self, eval_response: str) -> str:
        """Parse evaluator verdict from response YAML."""
        # Primary: try structured YAML parse
        try:
            data = yaml.safe_load(eval_response)
            if isinstance(data, dict):
                verdict = str(data.get("evaluator_verdict", "")).lower()
                if verdict in ("pass", "needs_work", "fail"):
                    return verdict
        except yaml.YAMLError:
            pass

        # Fallback: scan for verdict indicators on their own line.
        # The evaluator may use "evaluator_verdict: PASS", "VERDICT: PASS",
        # or "Verdict: pass" formats.
        for line in eval_response.lower().splitlines():
            stripped = line.strip()
            if "verdict" in stripped and ":" in stripped:
                after_colon = stripped.split(":", 1)[1].strip()
                if after_colon.startswith("pass"):
                    return "pass"
                if after_colon.startswith("fail"):
                    return "fail"
                if after_colon.startswith("needs_work"):
                    return "needs_work"

        return "needs_work"  # safe default
