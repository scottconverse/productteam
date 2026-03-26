"""Tests for the Forge file queue."""

from __future__ import annotations

import json

import pytest

from productteam.forge.queue import FileQueue, ForgeJob, GateInfo, JobStatus


# ---------------------------------------------------------------------------
# Enqueue / dequeue
# ---------------------------------------------------------------------------


def test_enqueue_creates_job(tmp_path):
    """enqueue creates a job directory with job.json."""
    queue = FileQueue(queue_dir=tmp_path)
    job = queue.enqueue("a cool app idea")
    assert job.job_id
    assert job.concept == "a cool app idea"
    assert job.status == JobStatus.QUEUED
    assert (tmp_path / job.job_id / "job.json").exists()


def test_enqueue_creates_log(tmp_path):
    """enqueue creates an empty log.txt."""
    queue = FileQueue(queue_dir=tmp_path)
    job = queue.enqueue("test")
    assert (tmp_path / job.job_id / "log.txt").exists()


def test_dequeue_returns_first_queued(tmp_path):
    """dequeue returns the oldest queued job."""
    queue = FileQueue(queue_dir=tmp_path)
    job1 = queue.enqueue("first")
    job2 = queue.enqueue("second")
    dequeued = queue.dequeue()
    assert dequeued is not None
    assert dequeued.job_id == job1.job_id


def test_dequeue_empty_returns_none(tmp_path):
    """dequeue returns None when no queued jobs."""
    queue = FileQueue(queue_dir=tmp_path)
    assert queue.dequeue() is None


def test_dequeue_skips_running(tmp_path):
    """dequeue skips jobs that are already running."""
    queue = FileQueue(queue_dir=tmp_path)
    job1 = queue.enqueue("first")
    queue.update_status(job1.job_id, JobStatus.RUNNING)
    job2 = queue.enqueue("second")
    dequeued = queue.dequeue()
    assert dequeued.job_id == job2.job_id


# ---------------------------------------------------------------------------
# Status updates
# ---------------------------------------------------------------------------


def test_update_status(tmp_path):
    """update_status changes job status on disk."""
    queue = FileQueue(queue_dir=tmp_path)
    job = queue.enqueue("test")
    queue.update_status(job.job_id, JobStatus.RUNNING)
    reloaded = queue.get_job(job.job_id)
    assert reloaded.status == JobStatus.RUNNING


def test_update_status_with_kwargs(tmp_path):
    """update_status accepts additional fields."""
    queue = FileQueue(queue_dir=tmp_path)
    job = queue.enqueue("test")
    queue.update_status(job.job_id, JobStatus.FAILED, error="something broke")
    reloaded = queue.get_job(job.job_id)
    assert reloaded.error == "something broke"


def test_update_status_nonexistent_raises(tmp_path):
    """update_status raises for unknown job ID."""
    queue = FileQueue(queue_dir=tmp_path)
    with pytest.raises(ValueError, match="not found"):
        queue.update_status("nonexistent", JobStatus.RUNNING)


# ---------------------------------------------------------------------------
# Job listing
# ---------------------------------------------------------------------------


def test_list_jobs_sorted(tmp_path):
    """list_jobs returns jobs sorted by creation time."""
    queue = FileQueue(queue_dir=tmp_path)
    j1 = queue.enqueue("first")
    j2 = queue.enqueue("second")
    j3 = queue.enqueue("third")
    jobs = queue.list_jobs()
    assert len(jobs) == 3
    assert jobs[0].concept == "first"


def test_list_jobs_empty(tmp_path):
    """list_jobs returns empty list when no jobs."""
    queue = FileQueue(queue_dir=tmp_path)
    assert queue.list_jobs() == []


# ---------------------------------------------------------------------------
# Gate management
# ---------------------------------------------------------------------------


def test_set_gate(tmp_path):
    """set_gate writes gate.json and updates status."""
    queue = FileQueue(queue_dir=tmp_path)
    job = queue.enqueue("test")
    gate = GateInfo(gate_name="PRD Approval", artifact_path="prds/prd.md", stage="prd")
    queue.set_gate(job.job_id, gate)

    reloaded = queue.get_job(job.job_id)
    assert reloaded.status == JobStatus.WAITING_GATE

    gate_info = queue.get_gate(job.job_id)
    assert gate_info is not None
    assert gate_info.gate_name == "PRD Approval"


def test_clear_gate(tmp_path):
    """clear_gate removes gate.json and resumes job."""
    queue = FileQueue(queue_dir=tmp_path)
    job = queue.enqueue("test")
    gate = GateInfo(gate_name="Test", artifact_path="", stage="test")
    queue.set_gate(job.job_id, gate)
    queue.clear_gate(job.job_id)

    reloaded = queue.get_job(job.job_id)
    assert reloaded.status == JobStatus.RUNNING
    assert queue.get_gate(job.job_id) is None


def test_get_gate_returns_none_when_no_gate(tmp_path):
    """get_gate returns None when no gate.json exists."""
    queue = FileQueue(queue_dir=tmp_path)
    job = queue.enqueue("test")
    assert queue.get_gate(job.job_id) is None


# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------


def test_append_and_read_log(tmp_path):
    """append_log adds timestamped lines, read_log retrieves them."""
    queue = FileQueue(queue_dir=tmp_path)
    job = queue.enqueue("test")
    queue.append_log(job.job_id, "Starting build")
    queue.append_log(job.job_id, "Build complete")
    log = queue.read_log(job.job_id)
    assert "Starting build" in log
    assert "Build complete" in log


def test_read_log_tail(tmp_path):
    """read_log respects tail parameter."""
    queue = FileQueue(queue_dir=tmp_path)
    job = queue.enqueue("test")
    for i in range(20):
        queue.append_log(job.job_id, f"Line {i}")
    log = queue.read_log(job.job_id, tail=5)
    lines = log.strip().splitlines()
    assert len(lines) == 5
    assert "Line 19" in lines[-1]


# ---------------------------------------------------------------------------
# Serialization
# ---------------------------------------------------------------------------


def test_job_roundtrip():
    """ForgeJob serializes and deserializes correctly."""
    job = ForgeJob(job_id="abc", concept="test app", status=JobStatus.RUNNING)
    data = job.to_dict()
    restored = ForgeJob.from_dict(data)
    assert restored.job_id == "abc"
    assert restored.concept == "test app"
    assert restored.status == JobStatus.RUNNING


def test_gate_roundtrip():
    """GateInfo serializes and deserializes correctly."""
    gate = GateInfo(gate_name="PRD", artifact_path="prd.md", stage="prd")
    data = gate.to_dict()
    restored = GateInfo.from_dict(data)
    assert restored.gate_name == "PRD"
    assert restored.stage == "prd"
