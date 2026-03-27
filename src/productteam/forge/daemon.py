"""Forge daemon: watches the queue and runs pipelines."""

from __future__ import annotations

import asyncio
import json
from datetime import datetime, timezone
from pathlib import Path

import httpx

from productteam.config import load_config
from productteam.forge.queue import FileQueue, ForgeJob, GateInfo, JobStatus
from productteam.models import ProductTeamConfig
from productteam.providers.factory import get_provider
from productteam.scaffold import init_project
from productteam.supervisor import Supervisor


class ForgeDaemon:
    """Watches the queue and processes jobs."""

    def __init__(self, config: ProductTeamConfig, queue: FileQueue | None = None):
        self.config = config
        self.queue = queue or FileQueue()
        self._running = True

    async def run(self) -> None:
        """Main loop — polls queue, processes jobs."""
        interval = self.config.forge.poll_interval_seconds
        while self._running:
            await self.poll_queue()
            await asyncio.sleep(interval)

    async def poll_queue(self) -> None:
        """Check for new or resumed jobs."""
        # Check for approved gates first
        for job in self.queue.list_jobs():
            if job.status == JobStatus.WAITING_GATE:
                gate = self.queue.get_gate(job.job_id)
                if gate is None:
                    # Gate was cleared externally (approved)
                    self.queue.update_status(job.job_id, JobStatus.RUNNING)

        # Process next queued job
        job = self.queue.dequeue()
        if job:
            await self.process_job(job)

    async def process_job(self, job: ForgeJob) -> None:
        """Run the full pipeline for a job."""
        self.queue.update_status(job.job_id, JobStatus.RUNNING)
        self.queue.append_log(job.job_id, f"Starting pipeline for: {job.concept}")

        # Create project directory
        projects_dir = Path.home() / ".productteam" / "forge" / "projects"
        project_dir = projects_dir / job.job_id
        project_dir.mkdir(parents=True, exist_ok=True)

        # Initialize project
        init_project(project_dir, force=True)
        self.queue.update_status(
            job.job_id, JobStatus.RUNNING, project_dir=str(project_dir)
        )

        # Create provider
        try:
            provider = get_provider(
                provider=self.config.pipeline.provider,
                model=self.config.pipeline.model,
                api_base=self.config.pipeline.api_base,
            )
        except Exception as e:
            self.queue.update_status(
                job.job_id, JobStatus.FAILED, error=str(e)
            )
            self.queue.append_log(job.job_id, f"FAILED: {e}")
            await self._notify(job, "job_failed", str(e))
            return

        # Run supervisor with auto-approve
        supervisor = Supervisor(
            project_dir=project_dir,
            config=self.config,
            provider=provider,
            auto_approve=True,
        )

        def _stage_callback(stage: str) -> None:
            self.queue.update_status(job.job_id, JobStatus.RUNNING, current_stage=stage)
            self.queue.append_log(job.job_id, f"Stage: {stage}")

        try:
            result = await supervisor.run(concept=job.concept, stage_callback=_stage_callback)
        except Exception as e:
            self.queue.update_status(
                job.job_id, JobStatus.FAILED, error=str(e)
            )
            self.queue.append_log(job.job_id, f"FAILED: {e}")
            await self._notify(job, "job_failed", str(e))
            return

        if result.status == "complete":
            self.queue.update_status(job.job_id, JobStatus.COMPLETE)
            self.queue.append_log(job.job_id, "Pipeline complete.")
            await self._notify(job, "job_complete", "Pipeline finished successfully.")
        else:
            self.queue.update_status(
                job.job_id, JobStatus.FAILED,
                error=f"Pipeline ended with status: {result.status}",
            )
            self.queue.append_log(
                job.job_id, f"Pipeline ended: {result.status}"
            )
            await self._notify(job, "job_failed", result.status)

    async def _notify(self, job: ForgeJob, event: str, message: str) -> None:
        """Send a notification if configured."""
        backend = self.config.forge.notification_backend
        url = self.config.forge.notification_url

        if backend == "none" or not url:
            return

        payload = {
            "job_id": job.job_id,
            "event": event,
            "stage": job.current_stage,
            "concept": job.concept,
            "message": message,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }

        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                await client.post(url, json=payload)
        except Exception:
            self.queue.append_log(
                job.job_id, f"Notification failed: {backend} -> {url}"
            )

    def stop(self) -> None:
        """Stop the daemon loop."""
        self._running = False
