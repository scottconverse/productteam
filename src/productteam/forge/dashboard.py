"""Minimal status dashboard for Forge.

Serves a single-page dashboard at http://<host>:<port> using
stdlib http.server. No dependencies, no framework, no build step.
Accessible from any device on your local network when bound to 0.0.0.0.
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
  h1 { font-family:var(--mono); font-size:20px; margin-bottom:16px; }

  /* Submit form */
  .submit-form { display:flex; gap:8px; margin-bottom:24px; }
  .submit-input {
    flex:1; padding:10px 14px; background:var(--surface); border:1px solid var(--border);
    border-radius:6px; color:var(--text); font-size:14px; font-family:inherit;
    outline:none; transition:border-color 0.15s;
  }
  .submit-input:focus { border-color:var(--accent); }
  .submit-input::placeholder { color:var(--muted); }
  .submit-btn {
    padding:10px 20px; background:var(--accent); color:#0e1117; border:none;
    border-radius:6px; font-size:14px; font-weight:600; cursor:pointer;
    font-family:inherit; white-space:nowrap; transition:opacity 0.15s;
  }
  .submit-btn:hover { opacity:0.9; }
  .submit-btn:disabled { opacity:0.5; cursor:not-allowed; }
  .submit-msg { font-size:12px; margin-top:4px; }
  .submit-msg.ok { color:var(--green); }
  .submit-msg.err { color:var(--red); }

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

  /* Responsive */
  @media (max-width: 600px) {
    .container { padding:16px; }
    .submit-form { flex-direction:column; }
    .submit-btn { width:100%; }
    td, th { padding:6px 8px; font-size:13px; }
  }
</style>
</head>
<body>
<div class="container">
  <h1>ProductTeam Forge</h1>

  <!-- Submit form -->
  <form class="submit-form" id="submit-form" onsubmit="submitIdea(event)">
    <input class="submit-input" id="concept-input" type="text" placeholder="Describe your product idea..." autocomplete="off" required maxlength="500">
    <button class="submit-btn" type="submit" id="submit-btn">Forge it</button>
  </form>
  <div class="submit-msg" id="submit-msg"></div>

  <!-- Jobs table -->
  <table id="jobs">
    <thead><tr><th>Job</th><th>Concept</th><th>Status</th><th>Stage</th><th>Actions</th></tr></thead>
    <tbody id="job-rows"></tbody>
  </table>
  <h2 style="font-size:14px;margin-bottom:8px;color:var(--muted);">Log</h2>
  <div class="log-panel" id="log-panel">Select a job to view logs.</div>
</div>
<script>
let selectedJob = null;

function escapeHtml(str) {
  return String(str)
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;')
    .replace(/'/g, '&#39;');
}

async function submitIdea(e) {
  e.preventDefault();
  const input = document.getElementById('concept-input');
  const btn = document.getElementById('submit-btn');
  const msg = document.getElementById('submit-msg');
  const concept = input.value.trim();
  if (!concept) return;

  btn.disabled = true;
  btn.textContent = 'Submitting...';
  msg.textContent = '';
  msg.className = 'submit-msg';

  try {
    const resp = await fetch('/api/submit', {
      method: 'POST',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({concept: concept})
    });
    const data = await resp.json();
    if (data.ok) {
      msg.textContent = 'Submitted: ' + escapeHtml(data.job_id);
      msg.className = 'submit-msg ok';
      input.value = '';
      refresh();
    } else {
      msg.textContent = 'Error: ' + (data.error || 'unknown');
      msg.className = 'submit-msg err';
    }
  } catch(err) {
    msg.textContent = 'Failed to submit: ' + err.message;
    msg.className = 'submit-msg err';
  }
  btn.disabled = false;
  btn.textContent = 'Forge it';
}

async function refresh() {
  try {
    const resp = await fetch('/api/jobs');
    const jobs = await resp.json();
    const tbody = document.getElementById('job-rows');
    tbody.innerHTML = '';
    for (const job of jobs) {
      const tr = document.createElement('tr');
      const eid = escapeHtml(job.job_id);
      const actions = job.status === 'waiting_gate'
        ? `<a class="btn btn-approve" href="#" onclick="approve('${eid}');return false;">Approve</a><a class="btn btn-reject" href="#" onclick="reject('${eid}');return false;">Reject</a>`
        : '';
      tr.innerHTML = `<td style="font-family:var(--mono)">${eid}</td><td>${escapeHtml(job.concept)}</td><td class="status-${escapeHtml(job.status)}">${escapeHtml(job.status)}</td><td>${escapeHtml(job.current_stage||'-')}</td><td>${actions}</td>`;
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
        if self.path == "/api/submit":
            MAX_BODY = 4096
            try:
                content_length = int(self.headers.get("Content-Length", 0))
            except (TypeError, ValueError):
                self._respond(400, "application/json", '{"ok":false,"error":"invalid content-length"}')
                return
            if content_length > MAX_BODY:
                self._respond(413, "application/json", '{"ok":false,"error":"concept too long"}')
                return
            body = self.rfile.read(content_length).decode("utf-8") if content_length else "{}"
            try:
                data = json.loads(body)
                concept = data.get("concept", "").strip()
                if not concept:
                    self._respond(400, "application/json", '{"ok":false,"error":"concept is required"}')
                    return
                job = self.queue.enqueue(concept)
                self._respond(200, "application/json", json.dumps({
                    "ok": True,
                    "job_id": job.job_id,
                    "concept": job.concept,
                }))
            except Exception as e:
                self._respond(500, "application/json", json.dumps({"ok": False, "error": str(e)}))
        elif self.path.startswith("/api/approve/"):
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


def serve_dashboard(
    queue: FileQueue,
    port: int = 7654,
    host: str = "0.0.0.0",
) -> HTTPServer:
    """Start the dashboard server in a background thread.

    Args:
        queue: The file queue to serve.
        port: Port to listen on (default: 7654).
        host: Host to bind to. '0.0.0.0' = accessible from LAN.
              '127.0.0.1' = localhost only.
    """
    DashboardHandler.queue = queue
    server = HTTPServer((host, port), DashboardHandler)
    thread = Thread(target=server.serve_forever, daemon=True)
    thread.start()
    return server
