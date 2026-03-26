"""Tests for the Forge daemon."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from productteam.forge.daemon import ForgeDaemon
from productteam.forge.queue import FileQueue, JobStatus
from productteam.models import ProductTeamConfig


def _make_config() -> ProductTeamConfig:
    return ProductTeamConfig.model_validate({
        "project": {"name": "test", "version": "1.0.0"},
        "pipeline": {
            "provider": "anthropic",
            "model": "test-model",
            "max_loops": 1,
            "stage_timeout_seconds": 5,
            "builder_timeout_seconds": 10,
            "builder_max_tool_calls": 3,
            "auto_approve": True,
        },
        "gates": {},
        "forge": {
            "enabled": True,
            "poll_interval_seconds": 1,
            "notification_backend": "none",
        },
    })


# ---------------------------------------------------------------------------
# Daemon basics
# ---------------------------------------------------------------------------


def test_daemon_creates(tmp_path):
    """ForgeDaemon instantiates with config and queue."""
    config = _make_config()
    queue = FileQueue(queue_dir=tmp_path)
    daemon = ForgeDaemon(config=config, queue=queue)
    assert daemon._running is True


def test_daemon_stop(tmp_path):
    """stop() sets _running to False."""
    config = _make_config()
    queue = FileQueue(queue_dir=tmp_path)
    daemon = ForgeDaemon(config=config, queue=queue)
    daemon.stop()
    assert daemon._running is False


# ---------------------------------------------------------------------------
# Job processing
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_daemon_processes_queued_job(tmp_path):
    """Daemon picks up and processes a queued job."""
    config = _make_config()
    queue = FileQueue(queue_dir=tmp_path)
    job = queue.enqueue("test app")

    # Mock the provider and supervisor
    with patch("productteam.forge.daemon.get_provider") as mock_get_provider, \
         patch("productteam.forge.daemon.Supervisor") as MockSupervisor:

        mock_provider = AsyncMock()
        mock_get_provider.return_value = mock_provider

        mock_supervisor = AsyncMock()
        mock_result = MagicMock()
        mock_result.status = "complete"
        mock_supervisor.run = AsyncMock(return_value=mock_result)
        MockSupervisor.return_value = mock_supervisor

        daemon = ForgeDaemon(config=config, queue=queue)
        await daemon.process_job(job)

    reloaded = queue.get_job(job.job_id)
    assert reloaded.status == JobStatus.COMPLETE


@pytest.mark.asyncio
async def test_daemon_marks_failed_on_provider_error(tmp_path):
    """Daemon marks job failed when provider creation fails."""
    config = _make_config()
    queue = FileQueue(queue_dir=tmp_path)
    job = queue.enqueue("test app")

    with patch("productteam.forge.daemon.get_provider") as mock_get_provider:
        mock_get_provider.side_effect = Exception("No API key")

        daemon = ForgeDaemon(config=config, queue=queue)
        await daemon.process_job(job)

    reloaded = queue.get_job(job.job_id)
    assert reloaded.status == JobStatus.FAILED
    assert "No API key" in reloaded.error


@pytest.mark.asyncio
async def test_daemon_poll_queue_picks_up_job(tmp_path):
    """poll_queue finds and processes the next queued job."""
    config = _make_config()
    queue = FileQueue(queue_dir=tmp_path)
    job = queue.enqueue("poll test")

    with patch("productteam.forge.daemon.get_provider") as mock_get_provider, \
         patch("productteam.forge.daemon.Supervisor") as MockSupervisor:

        mock_provider = AsyncMock()
        mock_get_provider.return_value = mock_provider

        mock_supervisor = AsyncMock()
        mock_result = MagicMock()
        mock_result.status = "complete"
        mock_supervisor.run = AsyncMock(return_value=mock_result)
        MockSupervisor.return_value = mock_supervisor

        daemon = ForgeDaemon(config=config, queue=queue)
        await daemon.poll_queue()

    reloaded = queue.get_job(job.job_id)
    assert reloaded.status == JobStatus.COMPLETE


@pytest.mark.asyncio
async def test_daemon_poll_empty_queue(tmp_path):
    """poll_queue does nothing when queue is empty."""
    config = _make_config()
    queue = FileQueue(queue_dir=tmp_path)
    daemon = ForgeDaemon(config=config, queue=queue)
    await daemon.poll_queue()  # Should not raise


# ---------------------------------------------------------------------------
# Notification tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_daemon_notification_none(tmp_path):
    """No notification sent when backend is 'none'."""
    config = _make_config()
    queue = FileQueue(queue_dir=tmp_path)
    job = queue.enqueue("test")

    daemon = ForgeDaemon(config=config, queue=queue)
    # Should not raise even though there's no webhook URL
    await daemon._notify(job, "job_complete", "Done")


@pytest.mark.asyncio
async def test_daemon_webhook_notification(tmp_path):
    """Webhook notification sends POST to configured URL."""
    config = ProductTeamConfig.model_validate({
        "project": {"name": "test", "version": "1.0.0"},
        "pipeline": {"provider": "anthropic", "model": "test"},
        "gates": {},
        "forge": {
            "notification_backend": "webhook",
            "notification_url": "https://example.com/hook",
        },
    })
    queue = FileQueue(queue_dir=tmp_path)
    job = queue.enqueue("test")

    with patch("productteam.forge.daemon.httpx") as mock_httpx:
        mock_client = AsyncMock()
        mock_client.post = AsyncMock()
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        mock_httpx.AsyncClient = MagicMock(return_value=mock_client)

        daemon = ForgeDaemon(config=config, queue=queue)
        await daemon._notify(job, "job_complete", "Done")

        mock_client.post.assert_called_once()
