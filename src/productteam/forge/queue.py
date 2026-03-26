"""File-based job queue for Forge.

Queue lives at ~/.productteam/forge/queue/. Each job is a directory
containing job.json, gate.json (optional), and log.txt.
"""

from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path


class JobStatus(str, Enum):
    QUEUED = "queued"
    RUNNING = "running"
    WAITING_GATE = "waiting_gate"
    COMPLETE = "complete"
    FAILED = "failed"


class ForgeJob:
    """Represents a single Forge job."""

    def __init__(
        self,
        job_id: str,
        concept: str,
        status: JobStatus = JobStatus.QUEUED,
        created_at: str = "",
        updated_at: str = "",
        project_dir: str = "",
        current_stage: str = "",
        error: str = "",
    ):
        self.job_id = job_id
        self.concept = concept
        self.status = status
        self.created_at = created_at or datetime.now(timezone.utc).isoformat()
        self.updated_at = updated_at or self.created_at
        self.project_dir = project_dir
        self.current_stage = current_stage
        self.error = error

    def to_dict(self) -> dict:
        return {
            "job_id": self.job_id,
            "concept": self.concept,
            "status": self.status.value,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "project_dir": self.project_dir,
            "current_stage": self.current_stage,
            "error": self.error,
        }

    @classmethod
    def from_dict(cls, data: dict) -> ForgeJob:
        return cls(
            job_id=data["job_id"],
            concept=data["concept"],
            status=JobStatus(data.get("status", "queued")),
            created_at=data.get("created_at", ""),
            updated_at=data.get("updated_at", ""),
            project_dir=data.get("project_dir", ""),
            current_stage=data.get("current_stage", ""),
            error=data.get("error", ""),
        )


class GateInfo:
    """Gate waiting for approval."""

    def __init__(self, gate_name: str, artifact_path: str, stage: str):
        self.gate_name = gate_name
        self.artifact_path = artifact_path
        self.stage = stage

    def to_dict(self) -> dict:
        return {
            "gate_name": self.gate_name,
            "artifact_path": self.artifact_path,
            "stage": self.stage,
        }

    @classmethod
    def from_dict(cls, data: dict) -> GateInfo:
        return cls(
            gate_name=data["gate_name"],
            artifact_path=data.get("artifact_path", ""),
            stage=data.get("stage", ""),
        )


def _queue_root() -> Path:
    """Return the forge queue root directory."""
    return Path.home() / ".productteam" / "forge" / "queue"


class FileQueue:
    """File-based job queue."""

    def __init__(self, queue_dir: Path | None = None):
        self.queue_dir = queue_dir or _queue_root()
        self.queue_dir.mkdir(parents=True, exist_ok=True)

    def enqueue(self, concept: str) -> ForgeJob:
        """Add a new job to the queue. Returns the job."""
        job_id = uuid.uuid4().hex[:8]
        job = ForgeJob(job_id=job_id, concept=concept)
        job_dir = self.queue_dir / job_id
        job_dir.mkdir(parents=True, exist_ok=True)
        self._write_job(job)
        # Create empty log
        (job_dir / "log.txt").write_text("", encoding="utf-8")
        return job

    def dequeue(self) -> ForgeJob | None:
        """Get the next queued job, or None if empty."""
        for job in self.list_jobs():
            if job.status == JobStatus.QUEUED:
                return job
        return None

    def get_job(self, job_id: str) -> ForgeJob | None:
        """Get a specific job by ID."""
        job_path = self.queue_dir / job_id / "job.json"
        if not job_path.exists():
            return None
        data = json.loads(job_path.read_text(encoding="utf-8"))
        return ForgeJob.from_dict(data)

    def list_jobs(self) -> list[ForgeJob]:
        """List all jobs, sorted by creation time."""
        jobs = []
        if not self.queue_dir.exists():
            return jobs
        for item in self.queue_dir.iterdir():
            if item.is_dir() and (item / "job.json").exists():
                data = json.loads((item / "job.json").read_text(encoding="utf-8"))
                jobs.append(ForgeJob.from_dict(data))
        jobs.sort(key=lambda j: j.created_at)
        return jobs

    def update_status(self, job_id: str, status: JobStatus, **kwargs) -> None:
        """Update a job's status and optional fields."""
        job = self.get_job(job_id)
        if job is None:
            raise ValueError(f"Job not found: {job_id}")
        job.status = status
        job.updated_at = datetime.now(timezone.utc).isoformat()
        for key, value in kwargs.items():
            if hasattr(job, key):
                setattr(job, key, value)
        self._write_job(job)

    def set_gate(self, job_id: str, gate: GateInfo) -> None:
        """Write a gate file for a job."""
        gate_path = self.queue_dir / job_id / "gate.json"
        gate_path.write_text(json.dumps(gate.to_dict(), indent=2), encoding="utf-8")
        self.update_status(job_id, JobStatus.WAITING_GATE, current_stage=gate.stage)

    def get_gate(self, job_id: str) -> GateInfo | None:
        """Read the gate file for a job, if any."""
        gate_path = self.queue_dir / job_id / "gate.json"
        if not gate_path.exists():
            return None
        data = json.loads(gate_path.read_text(encoding="utf-8"))
        return GateInfo.from_dict(data)

    def clear_gate(self, job_id: str) -> None:
        """Remove the gate file and resume the job."""
        gate_path = self.queue_dir / job_id / "gate.json"
        if gate_path.exists():
            gate_path.unlink()
        self.update_status(job_id, JobStatus.RUNNING)

    def append_log(self, job_id: str, message: str) -> None:
        """Append a line to the job's log file."""
        log_path = self.queue_dir / job_id / "log.txt"
        timestamp = datetime.now(timezone.utc).strftime("%H:%M:%S")
        with log_path.open("a", encoding="utf-8") as f:
            f.write(f"[{timestamp}] {message}\n")

    def read_log(self, job_id: str, tail: int = 50) -> str:
        """Read the last N lines of a job's log."""
        log_path = self.queue_dir / job_id / "log.txt"
        if not log_path.exists():
            return ""
        lines = log_path.read_text(encoding="utf-8").splitlines()
        return "\n".join(lines[-tail:])

    def _write_job(self, job: ForgeJob) -> None:
        """Write job.json to disk."""
        job_dir = self.queue_dir / job.job_id
        job_dir.mkdir(parents=True, exist_ok=True)
        (job_dir / "job.json").write_text(
            json.dumps(job.to_dict(), indent=2), encoding="utf-8"
        )
