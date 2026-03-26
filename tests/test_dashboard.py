"""Tests for the Forge dashboard HTTP endpoints.

Tests the DashboardHandler endpoints:
  GET  /             — HTML dashboard
  GET  /api/jobs     — Job listing
  GET  /api/log/:id  — Job log
  POST /api/submit   — Job submission
  POST /api/approve  — Gate approval
  POST /api/reject   — Gate rejection
"""

from __future__ import annotations

import json
from http.server import HTTPServer
from io import BytesIO
from unittest.mock import MagicMock, patch

import pytest

from productteam.forge.dashboard import DashboardHandler, serve_dashboard
from productteam.forge.queue import FileQueue, JobStatus


# ---------------------------------------------------------------------------
# Helpers — build fake HTTP requests without a real socket
# ---------------------------------------------------------------------------


class _FakeRequest(BytesIO):
    """BytesIO that also acts as makefile() return value."""

    def makefile(self, *args, **kwargs):
        return self


class _ResponseCapture(BytesIO):
    """Captures HTTP response bytes written by the handler."""

    def makefile(self, *args, **kwargs):
        return self


def _make_handler(queue: FileQueue, method: str, path: str, body: bytes = b"", headers: dict | None = None) -> tuple[DashboardHandler, _ResponseCapture]:
    """Build a DashboardHandler with a fake request and capture the response."""
    headers = headers or {}
    # Build raw HTTP request
    request_line = f"{method} {path} HTTP/1.1\r\n"
    header_lines = ""
    if body:
        headers.setdefault("Content-Length", str(len(body)))
    for k, v in headers.items():
        header_lines += f"{k}: {v}\r\n"
    raw = (request_line + header_lines + "\r\n").encode("utf-8") + body

    request_io = _FakeRequest(raw)
    response_io = _ResponseCapture()

    # Patch the handler to avoid socket operations
    DashboardHandler.queue = queue
    handler = DashboardHandler.__new__(DashboardHandler)
    handler.rfile = BytesIO(body)
    handler.wfile = response_io
    handler.path = path
    handler.command = method
    handler.headers = {}
    handler.requestline = request_line.strip()
    handler.request_version = "HTTP/1.1"
    handler.client_address = ("127.0.0.1", 0)

    # Parse headers into a simple dict-like object
    from http.client import HTTPMessage
    from email.parser import Parser
    header_str = "\r\n".join(f"{k}: {v}" for k, v in headers.items()) + "\r\n\r\n"
    handler.headers = Parser().parsestr(header_str)

    # Capture response code and headers
    handler._response_code = None
    handler._response_headers = {}
    handler._response_body = b""

    original_respond = DashboardHandler._respond

    def capture_respond(self, code, content_type, body_str):
        handler._response_code = code
        handler._response_headers["Content-Type"] = content_type
        handler._response_body = body_str.encode("utf-8")

    handler._respond = lambda code, ct, body_str: capture_respond(handler, code, ct, body_str)

    return handler, response_io


# ---------------------------------------------------------------------------
# GET / — Dashboard HTML
# ---------------------------------------------------------------------------


def test_get_root_returns_html(tmp_path):
    """GET / returns 200 with HTML dashboard."""
    queue = FileQueue(queue_dir=tmp_path)
    handler, _ = _make_handler(queue, "GET", "/")
    handler.do_GET()
    assert handler._response_code == 200
    assert handler._response_headers["Content-Type"] == "text/html"
    assert b"ProductTeam Forge" in handler._response_body


def test_get_index_html_returns_dashboard(tmp_path):
    """GET /index.html returns same dashboard."""
    queue = FileQueue(queue_dir=tmp_path)
    handler, _ = _make_handler(queue, "GET", "/index.html")
    handler.do_GET()
    assert handler._response_code == 200
    assert b"ProductTeam Forge" in handler._response_body


# ---------------------------------------------------------------------------
# GET /api/jobs — Job listing
# ---------------------------------------------------------------------------


def test_get_jobs_empty(tmp_path):
    """GET /api/jobs returns empty list when no jobs exist."""
    queue = FileQueue(queue_dir=tmp_path)
    handler, _ = _make_handler(queue, "GET", "/api/jobs")
    handler.do_GET()
    assert handler._response_code == 200
    assert handler._response_headers["Content-Type"] == "application/json"
    data = json.loads(handler._response_body)
    assert data == []


def test_get_jobs_lists_submitted(tmp_path):
    """GET /api/jobs returns jobs after submission."""
    queue = FileQueue(queue_dir=tmp_path)
    job = queue.enqueue("Test concept")

    handler, _ = _make_handler(queue, "GET", "/api/jobs")
    handler.do_GET()
    data = json.loads(handler._response_body)
    assert len(data) == 1
    assert data[0]["job_id"] == job.job_id
    assert data[0]["concept"] == "Test concept"


# ---------------------------------------------------------------------------
# GET /api/log/:id — Job log
# ---------------------------------------------------------------------------


def test_get_log_for_job(tmp_path):
    """GET /api/log/:id returns log content."""
    queue = FileQueue(queue_dir=tmp_path)
    job = queue.enqueue("log test")
    queue.append_log(job.job_id, "Line 1")
    queue.append_log(job.job_id, "Line 2")

    handler, _ = _make_handler(queue, "GET", f"/api/log/{job.job_id}")
    handler.do_GET()
    assert handler._response_code == 200
    body = handler._response_body.decode()
    assert "Line 1" in body
    assert "Line 2" in body


def test_get_log_nonexistent_job(tmp_path):
    """GET /api/log/:id returns empty for nonexistent job."""
    queue = FileQueue(queue_dir=tmp_path)
    handler, _ = _make_handler(queue, "GET", "/api/log/nonexistent")
    handler.do_GET()
    assert handler._response_code == 200
    assert handler._response_body == b""


# ---------------------------------------------------------------------------
# GET 404 — Unknown paths
# ---------------------------------------------------------------------------


def test_get_unknown_path_returns_404(tmp_path):
    """GET on unknown path returns 404."""
    queue = FileQueue(queue_dir=tmp_path)
    handler, _ = _make_handler(queue, "GET", "/nonexistent")
    handler.do_GET()
    assert handler._response_code == 404


# ---------------------------------------------------------------------------
# POST /api/submit — Job submission
# ---------------------------------------------------------------------------


def test_submit_happy_path(tmp_path):
    """POST /api/submit with valid concept creates a job."""
    queue = FileQueue(queue_dir=tmp_path)
    body = json.dumps({"concept": "Build a calculator"}).encode()
    handler, _ = _make_handler(queue, "POST", "/api/submit",
                                body=body,
                                headers={"Content-Type": "application/json"})
    handler.do_POST()

    assert handler._response_code == 200
    data = json.loads(handler._response_body)
    assert data["ok"] is True
    assert data["concept"] == "Build a calculator"
    assert data["job_id"]

    # Verify job exists in queue
    jobs = queue.list_jobs()
    assert len(jobs) == 1
    assert jobs[0].concept == "Build a calculator"


def test_submit_empty_concept(tmp_path):
    """POST /api/submit with empty concept returns 400."""
    queue = FileQueue(queue_dir=tmp_path)
    body = json.dumps({"concept": ""}).encode()
    handler, _ = _make_handler(queue, "POST", "/api/submit",
                                body=body,
                                headers={"Content-Type": "application/json"})
    handler.do_POST()

    assert handler._response_code == 400
    data = json.loads(handler._response_body)
    assert data["ok"] is False
    assert "required" in data["error"]


def test_submit_whitespace_only_concept(tmp_path):
    """POST /api/submit with whitespace-only concept returns 400."""
    queue = FileQueue(queue_dir=tmp_path)
    body = json.dumps({"concept": "   "}).encode()
    handler, _ = _make_handler(queue, "POST", "/api/submit",
                                body=body,
                                headers={"Content-Type": "application/json"})
    handler.do_POST()

    assert handler._response_code == 400
    data = json.loads(handler._response_body)
    assert data["ok"] is False


def test_submit_missing_concept_key(tmp_path):
    """POST /api/submit with no concept key returns 400."""
    queue = FileQueue(queue_dir=tmp_path)
    body = json.dumps({"idea": "something"}).encode()
    handler, _ = _make_handler(queue, "POST", "/api/submit",
                                body=body,
                                headers={"Content-Type": "application/json"})
    handler.do_POST()

    assert handler._response_code == 400
    data = json.loads(handler._response_body)
    assert data["ok"] is False


def test_submit_oversized_body(tmp_path):
    """POST /api/submit with body > 4KB returns 413."""
    queue = FileQueue(queue_dir=tmp_path)
    handler, _ = _make_handler(queue, "POST", "/api/submit",
                                body=b"",  # body won't be read due to early rejection
                                headers={
                                    "Content-Type": "application/json",
                                    "Content-Length": "10000",
                                })
    handler.do_POST()

    assert handler._response_code == 413
    data = json.loads(handler._response_body)
    assert data["ok"] is False
    assert "too long" in data["error"]


def test_submit_malformed_content_length(tmp_path):
    """POST /api/submit with non-numeric Content-Length returns 400."""
    queue = FileQueue(queue_dir=tmp_path)
    handler, _ = _make_handler(queue, "POST", "/api/submit",
                                body=b"",
                                headers={
                                    "Content-Type": "application/json",
                                    "Content-Length": "abc",
                                })
    handler.do_POST()

    assert handler._response_code == 400
    data = json.loads(handler._response_body)
    assert data["ok"] is False
    assert "content-length" in data["error"].lower()


def test_submit_malformed_json(tmp_path):
    """POST /api/submit with invalid JSON returns 500."""
    queue = FileQueue(queue_dir=tmp_path)
    body = b"not json at all"
    handler, _ = _make_handler(queue, "POST", "/api/submit",
                                body=body,
                                headers={"Content-Type": "application/json"})
    handler.do_POST()

    assert handler._response_code == 500
    data = json.loads(handler._response_body)
    assert data["ok"] is False


def test_submit_empty_body(tmp_path):
    """POST /api/submit with no body returns 400 (concept required)."""
    queue = FileQueue(queue_dir=tmp_path)
    handler, _ = _make_handler(queue, "POST", "/api/submit",
                                body=b"",
                                headers={"Content-Type": "application/json"})
    handler.do_POST()

    # Empty body → parsed as {} → no concept → 400
    assert handler._response_code == 400


# ---------------------------------------------------------------------------
# POST /api/approve/:id — Gate approval
# ---------------------------------------------------------------------------


def test_approve_clears_gate(tmp_path):
    """POST /api/approve/:id clears the gate."""
    queue = FileQueue(queue_dir=tmp_path)
    job = queue.enqueue("approval test")
    from productteam.forge.queue import GateInfo
    queue.set_gate(job.job_id, GateInfo(gate_name="PRD Approval", artifact_path="", stage="prd"))

    handler, _ = _make_handler(queue, "POST", f"/api/approve/{job.job_id}")
    handler.do_POST()

    assert handler._response_code == 200
    data = json.loads(handler._response_body)
    assert data["ok"] is True

    # Gate should be cleared
    assert queue.get_gate(job.job_id) is None


# ---------------------------------------------------------------------------
# POST /api/reject/:id — Gate rejection
# ---------------------------------------------------------------------------


def test_reject_marks_failed(tmp_path):
    """POST /api/reject/:id marks job as FAILED."""
    queue = FileQueue(queue_dir=tmp_path)
    job = queue.enqueue("rejection test")

    handler, _ = _make_handler(queue, "POST", f"/api/reject/{job.job_id}")
    handler.do_POST()

    assert handler._response_code == 200
    data = json.loads(handler._response_body)
    assert data["ok"] is True

    # Job should be failed
    updated = queue.get_job(job.job_id)
    assert updated.status == JobStatus.FAILED


# ---------------------------------------------------------------------------
# POST 404 — Unknown paths
# ---------------------------------------------------------------------------


def test_post_unknown_path_returns_404(tmp_path):
    """POST on unknown path returns 404."""
    queue = FileQueue(queue_dir=tmp_path)
    handler, _ = _make_handler(queue, "POST", "/nonexistent")
    handler.do_POST()
    assert handler._response_code == 404


# ---------------------------------------------------------------------------
# serve_dashboard integration
# ---------------------------------------------------------------------------


def test_serve_dashboard_starts_server(tmp_path):
    """serve_dashboard returns an HTTPServer that is listening."""
    queue = FileQueue(queue_dir=tmp_path)
    server = serve_dashboard(queue, port=0, host="127.0.0.1")  # port 0 = OS picks
    try:
        assert isinstance(server, HTTPServer)
        host, port = server.server_address
        assert port > 0
    finally:
        server.shutdown()
