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
from typing import Any

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
    ):
        self.stage = stage
        self.status = status  # "complete" | "stuck" | "failed" | "skipped"
        self.artifact_path = artifact_path
        self.raw_response = raw_response
        self.error = error


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


def _load_skill(project_dir: Path, skill_name: str) -> str:
    """Load a SKILL.md file content."""
    skill_path = project_dir / ".claude" / "skills" / skill_name / "SKILL.md"
    if not skill_path.exists():
        raise FileNotFoundError(f"Skill not found: {skill_path}")
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

    async def run(
        self,
        concept: str = "",
        step: str | None = None,
        sprint: str | None = None,
        rebuild: bool = False,
        dry_run: bool = False,
    ) -> SupervisorResult:
        """Run the full pipeline or a single step.

        Args:
            concept: Product concept string. Required for fresh run.
            step: If set, run only this stage.
            sprint: Target sprint (with step=build or evaluate).
            rebuild: Force rebuild even if passed.
            dry_run: Show what would happen without calling LLM.
        """
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
            console.print("[dim]Dry run — no LLM calls will be made[/dim]")
            for stage_name in ["prd", "plan", "build", "evaluate", "document", "ship"]:
                console.print(f"  Would run: {stage_name}")
            return SupervisorResult(concept=concept, stages=[], status="complete")

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
            result = await self._run_tool_loop_stage(
                PipelineStage.DOCUMENT, "doc-writer",
                f"Write documentation for the project. Concept: {concept}",
            )
            stages.append(result)
            if result.status != "complete":
                return SupervisorResult(concept=concept, stages=stages, status="stuck")

        # 4b. Design Evaluation (single pass — no retry loop because there is
        # no mechanism to route back to Doc Writer/UI Builder to fix issues)
        if self.config.pipeline.require_design_review:
            if not _is_stage_complete(self.state, "evaluate-design") or rebuild:
                result = await self._run_tool_loop_stage(
                    PipelineStage.EVALUATE_DESIGN, "evaluator-design",
                    f"Evaluate design quality. Read docs/index.html, docs/terms.html, "
                    f"and README.md. Concept: {concept}",
                )
                stages.append(result)
                if result.status != "complete":
                    return SupervisorResult(concept=concept, stages=stages, status="stuck")

                verdict = self._parse_verdict(result.raw_response)
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
            return await self._run_tool_loop_stage(
                stage, "doc-writer",
                f"Write documentation for the project. Concept: {concept}",
            )
        elif stage == PipelineStage.EVALUATE_DESIGN:
            return await self._run_tool_loop_stage(
                stage, "evaluator-design",
                f"Evaluate design quality. Read docs/index.html, docs/terms.html, "
                f"and README.md. Concept: {concept}",
            )
        else:
            return StageResult(stage=stage, status="skipped")

    async def _run_thinker_stage(
        self,
        stage: PipelineStage,
        skill_name: str,
        context: str,
    ) -> StageResult:
        """Run a thinker stage (single LLM call)."""
        console.print(f"\n[bold cyan]Running: {stage.value}[/bold cyan]")

        try:
            system_prompt = _load_skill(self.project_dir, skill_name)
        except FileNotFoundError as e:
            return StageResult(stage=stage, status="failed", error=str(e))

        self.state["pipeline_phase"] = stage.value
        self.state.setdefault("stages", {})[stage.value] = {"status": "running"}
        _save_state(self.project_dir, self.state)

        try:
            response = await asyncio.wait_for(
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
        )

    async def _run_tool_loop_stage(
        self,
        stage: PipelineStage,
        skill_name: str,
        context: str,
        timeout_seconds: float | None = None,
    ) -> StageResult:
        """Run a doer stage (tool loop with file access)."""
        console.print(f"\n[bold cyan]Running: {stage.value} (tool loop)[/bold cyan]")

        try:
            system_prompt = _load_skill(self.project_dir, skill_name)
        except FileNotFoundError as e:
            return StageResult(stage=stage, status="failed", error=str(e))

        self.state["pipeline_phase"] = stage.value
        self.state.setdefault("stages", {})[stage.value] = {"status": "running"}
        _save_state(self.project_dir, self.state)

        effective_timeout = timeout_seconds or self.config.pipeline.builder_timeout_seconds

        result = await run_tool_loop(
            provider=self.provider,
            system_prompt=system_prompt,
            initial_user_message=context,
            project_dir=self.project_dir,
            max_tool_calls=self.config.pipeline.builder_max_tool_calls,
            timeout_seconds=effective_timeout,
        )

        if result.status in ("stuck", "max_calls"):
            self.state["stages"][stage.value] = {"status": "stuck"}
            _save_state(self.project_dir, self.state)
            console.print(f"[red]Stage {stage.value} stuck: {result.final_text}[/red]")
            return StageResult(
                stage=stage,
                status="stuck",
                error=result.final_text,
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
        )

    async def _build_evaluate_loop(self, sprint_name: str) -> StageResult:
        """Run build-evaluate loop for a sprint."""
        max_loops = self.config.pipeline.max_loops
        console.print(f"\n[bold yellow]Build-Evaluate: {sprint_name}[/bold yellow]")

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
                system_prompt = _load_skill(self.project_dir, "builder")
            except FileNotFoundError as e:
                return StageResult(
                    stage=PipelineStage.BUILD, status="failed", error=str(e)
                )

            build_prompt = (
                f"Implement the following sprint contract:\n\n"
                f"{sprint_contract}\n\n"
                f"This is loop {loop_num} of {max_loops}."
            )

            build_result = await run_tool_loop(
                provider=self.provider,
                system_prompt=system_prompt,
                initial_user_message=build_prompt,
                project_dir=self.project_dir,
                max_tool_calls=self.config.pipeline.builder_max_tool_calls,
                timeout_seconds=self.config.pipeline.builder_timeout_seconds,
            )

            if build_result.status == "stuck":
                console.print(f"  [red]Builder stuck: {build_result.final_text}[/red]")
                self.state["stages"]["build"]["status"] = "stuck"
                _save_state(self.project_dir, self.state)
                return StageResult(
                    stage=PipelineStage.BUILD,
                    status="stuck",
                    error=build_result.final_text,
                )

            if build_result.status == "max_calls":
                console.print(f"  [red]Builder exceeded max tool calls[/red]")
                self.state["stages"]["build"]["status"] = "stuck"
                _save_state(self.project_dir, self.state)
                return StageResult(
                    stage=PipelineStage.BUILD,
                    status="stuck",
                    error="Max tool calls exceeded",
                )

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
                )

            # Evaluate
            self.state["stages"]["evaluate"] = {
                "status": "running",
                "sprint": sprint_name,
                "loop": loop_num,
            }
            _save_state(self.project_dir, self.state)

            try:
                eval_system = _load_skill(self.project_dir, "evaluator")
            except FileNotFoundError as e:
                return StageResult(
                    stage=PipelineStage.EVALUATE, status="failed", error=str(e)
                )

            eval_prompt = (
                f"Evaluate sprint {sprint_name} (loop {loop_num}/{max_loops}).\n\n"
                f"Sprint contract:\n{sprint_contract}\n\n"
                f"Builder output:\n{build_result.final_text}"
            )

            eval_result = await run_tool_loop(
                provider=self.provider,
                system_prompt=eval_system,
                initial_user_message=eval_prompt,
                project_dir=self.project_dir,
                max_tool_calls=self.config.pipeline.builder_max_tool_calls,
                timeout_seconds=self.config.pipeline.builder_timeout_seconds,
            )

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
            verdict = self._parse_verdict(eval_response)
            if verdict == "needs_work":
                # The Evaluator may have written a structured YAML via write_file
                # that has a clearer verdict than its text response
                eval_dir = self.project_dir / ".productteam" / "evaluations"
                # Check files the Evaluator wrote via write_file (eval-NNN.yaml)
                # Scope to the current sprint number to avoid cross-sprint leaks
                sprint_num = sprint_name.split("-")[-1]  # "001" from "sprint-001"
                candidates = list(eval_dir.glob(f"eval-{sprint_num}*.yaml"))
                # Also check supervisor-written files for this sprint
                candidates += list(eval_dir.glob(f"{sprint_name}-eval-*.yaml"))
                # Exclude the file we just wrote (it has the same text we already parsed)
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
                )

            # NEEDS_WORK — continue loop with summarized feedback
            sprint_contract += "\n\n" + self._summarize_eval_feedback(eval_response, loop_num)

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

        # Fallback: scan for the exact YAML key on its own line
        for line in eval_response.lower().splitlines():
            stripped = line.strip()
            if stripped.startswith("evaluator_verdict:") or stripped.startswith("verdict:"):
                if "pass" in stripped:
                    return "pass"
                if "fail" in stripped:
                    return "fail"
                if "needs_work" in stripped:
                    return "needs_work"

        return "needs_work"  # safe default
