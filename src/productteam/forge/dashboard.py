"""Minimal status dashboard for Forge.

Serves a single-page dashboard at http://127.0.0.1:<port> using
stdlib http.server. No dependencies, no framework, no build step.
"""

from __future__ import annotations

import json
from http.server import HTTPServer, BaseHTTPRequestHandler
from pathlib import Path
from threading import Thread

from productteam.forge.queue import FileQueue, JobStatus


_DASHBOARD_HTML = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>ProductTeam Forge</title>
<style>
  :root { --bg:#0e1117; --surface:#161b22; --border:#30363d; --text:#e6edf3; --muted:#8b949e; --accent:#58a6ff; --green:#3fb950; --red:#f85149; --yellow:#d29922; --mono:'SF Mono','Fira Code',monospace; }
  * { margin:0; padding:0; box-sizing:border-box; }
  body { background:var(--bg); color:var(--text); font-family:-apple-system,sans-serif; font-size:14px; }
  .container { max-width:960px; margin:0 auto; padding:24px; }
  h1 { font-family:var(--mono); font-size:20px; margin-bottom:24px; }
  table { width:100%; border-collapse:collapse; margin-bottom:24px; }
  th { text-align:left; padding:8px 12px; border-bottom:2px solid var(--border); color:var(--muted); font-size:12px; text-transform:uppercase; }
  td { padding:8px 12px; border-bottom:1px solid var(--border); }
  .status-queued { color:var(--muted); }
  .status-running { color:var(--accent); }
  .status-waiting_gate { color:var(--yellow); }
  .status-complete { color:var(--green); }
  .status-failed { color:var(--red); }
  .log-panel { background:var(--surface); border:1px solid var(--border); border-radius:8px; padding:16px; font-family:var(--mono); font-size:12px; white-space:pre-wrap; max-height:400px; overflow-y:auto; color:var(--muted); }
  .btn { display:inline-block; padding:4px 12px; border:1px solid var(--border); border-radius:4px; color:var(--text); background:var(--surface); cursor:pointer; font-size:12px; text-decoration:none; margin:0 4px; }
  .btn:hover { border-color:var(--accent); }
  .btn-approve { border-color:var(--green); color:var(--green); }
  .btn-reject { border-color:var(--red); color:var(--red); }
</style>
</head>
<body>
<div class="container">
  <h1>ProductTeam Forge</h1>
  <table id="jobs">
    <thead><tr><th>Job</th><th>Concept</th><th>Status</th><th>Stage</th><th>Actions</th></tr></thead>
    <tbody id="job-rows"></tbody>
  </table>
  <h2 style="font-size:14px;margin-bottom:8px;color:var(--muted);">Log</h2>
  <div class="log-panel" id="log-panel">Select a job to view logs.</div>
</div>
<script>
let selectedJob = null;
async function refresh() {
  try {
    const resp = await fetch('/api/jobs');
    const jobs = await resp.json();
    const tbody = document.getElementById('job-rows');
    tbody.innerHTML = '';
    for (const job of jobs) {
      const tr = document.createElement('tr');
      const actions = job.status === 'waiting_gate'
        ? `<a class="btn btn-approve" href="#" onclick="approve('${job.job_id}');return false;">Approve</a><a class="btn btn-reject" href="#" onclick="reject('${job.job_id}');return false;">Reject</a>`
        : '';
      tr.innerHTML = `<td style="font-family:var(--mono)">${job.job_id}</td><td>${job.concept}</td><td class="status-${job.status}">${job.status}</td><td>${job.current_stage||'-'}</td><td>${actions}</td>`;
      tr.style.cursor = 'pointer';
      tr.onclick = () => { selectedJob = job.job_id; loadLog(job.job_id); };
      tbody.appendChild(tr);
    }
    if (selectedJob) loadLog(selectedJob);
  } catch(e) {}
}
async function loadLog(jobId) {
  try {
    const resp = await fetch('/api/log/' + jobId);
    const text = await resp.text();
    document.getElementById('log-panel').textContent = text || '(empty)';
  } catch(e) {}
}
async function approve(jobId) { await fetch('/api/approve/' + jobId, {method:'POST'}); refresh(); }
async function reject(jobId) { await fetch('/api/reject/' + jobId, {method:'POST'}); refresh(); }
refresh();
setInterval(refresh, 5000);
</script>
</body>
</html>"""


class DashboardHandler(BaseHTTPRequestHandler):
    """HTTP handler for the Forge dashboard."""

    queue: FileQueue  # Set by serve_dashboard

    def do_GET(self) -> None:
        if self.path == "/" or self.path == "/index.html":
            self._respond(200, "text/html", _DASHBOARD_HTML)
        elif self.path == "/api/jobs":
            jobs = self.queue.list_jobs()
            data = json.dumps([j.to_dict() for j in jobs])
            self._respond(200, "application/json", data)
        elif self.path.startswith("/api/log/"):
            job_id = self.path.split("/")[-1]
            log = self.queue.read_log(job_id, tail=100)
            self._respond(200, "text/plain", log)
        else:
            self._respond(404, "text/plain", "Not found")

    def do_POST(self) -> None:
        if self.path.startswith("/api/approve/"):
            job_id = self.path.split("/")[-1]
            self.queue.clear_gate(job_id)
            self._respond(200, "application/json", '{"ok":true}')
        elif self.path.startswith("/api/reject/"):
            job_id = self.path.split("/")[-1]
            self.queue.update_status(job_id, JobStatus.FAILED, error="Rejected by user")
            self.queue.append_log(job_id, "Job rejected by user.")
            self._respond(200, "application/json", '{"ok":true}')
        else:
            self._respond(404, "text/plain", "Not found")

    def _respond(self, code: int, content_type: str, body: str) -> None:
        self.send_response(code)
        self.send_header("Content-Type", content_type)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()
        self.wfile.write(body.encode("utf-8"))

    def log_message(self, format, *args) -> None:
        pass  # Suppress default logging


def serve_dashboard(queue: FileQueue, port: int = 7654) -> HTTPServer:
    """Start the dashboard server in a background thread."""
    DashboardHandler.queue = queue
    server = HTTPServer(("127.0.0.1", port), DashboardHandler)
    thread = Thread(target=server.serve_forever, daemon=True)
    thread.start()
    return server
