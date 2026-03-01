#!/usr/bin/env python3
"""Minimal FastAPI status server.

Shows live worker heartbeats and job registry in the browser.

Usage::

    pip install fastapi uvicorn
    python -m lab.status_server
    # or: uvicorn lab.status_server:app --host 0.0.0.0 --port 8420

Endpoints::

    GET /              → HTML dashboard
    GET /api/workers   → JSON worker heartbeats
    GET /api/jobs      → JSON job list (?status=running)
    GET /api/costs     → today's total cost
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

from . import config as cfg
from .registry import Registry

try:
    from fastapi import FastAPI, Query
    from fastapi.responses import HTMLResponse
except ImportError:
    raise SystemExit(
        "FastAPI is required for the status server.\n"
        "Install it:  pip install fastapi uvicorn"
    )

app = FastAPI(title="Home AI Lab", version="1.0")


def _registry() -> Registry:
    cfg.ensure_lab_dirs()
    return Registry(cfg.REGISTRY_DB)


# ------------------------------------------------------------------
# API endpoints
# ------------------------------------------------------------------


@app.get("/api/workers")
def api_workers() -> list[dict]:
    """Return heartbeat data for all workers."""
    workers = []
    if cfg.HEARTBEATS_DIR.exists():
        for hb in sorted(cfg.HEARTBEATS_DIR.glob("*.json")):
            try:
                with open(hb) as f:
                    data = json.load(f)
                # Mark stale if heartbeat older than 30s.
                ts = data.get("timestamp", "")
                if ts:
                    age = (
                        datetime.now(timezone.utc)
                        - datetime.fromisoformat(ts)
                    ).total_seconds()
                    data["stale"] = age > 30
                workers.append(data)
            except (json.JSONDecodeError, OSError):
                continue
    return workers


@app.get("/api/jobs")
def api_jobs(status: str | None = Query(None)) -> list[dict]:
    reg = _registry()
    rows = reg.list_all(status=status)
    reg.close()
    return rows


@app.get("/api/costs")
def api_costs() -> dict:
    reg = _registry()
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    cost = reg.daily_cost(today)
    reg.close()
    return {"date": today, "total_cost_gbp": round(cost, 4)}


# ------------------------------------------------------------------
# HTML dashboard
# ------------------------------------------------------------------


@app.get("/", response_class=HTMLResponse)
def dashboard() -> str:
    return """\
<!DOCTYPE html>
<html>
<head>
<meta charset="utf-8">
<title>Home AI Lab</title>
<meta http-equiv="refresh" content="10">
<style>
  body { font-family: -apple-system, system-ui, sans-serif; margin: 2em; background: #0d1117; color: #c9d1d9; }
  h1 { color: #58a6ff; }
  table { border-collapse: collapse; width: 100%; margin-top: 1em; }
  th, td { border: 1px solid #30363d; padding: 6px 12px; text-align: left; }
  th { background: #161b22; }
  .stale { color: #f85149; }
  .active { color: #3fb950; }
  .badge { padding: 2px 8px; border-radius: 4px; font-size: 0.85em; }
  .pending { background: #1f6feb33; color: #58a6ff; }
  .running { background: #3fb95033; color: #3fb950; }
  .completed { background: #23883833; color: #238838; }
  .failed { background: #f8514933; color: #f85149; }
  .blocked { background: #d2992233; color: #d29922; }
  #cost { font-size: 1.2em; margin: 1em 0; }
</style>
</head>
<body>
<h1>Home AI Lab</h1>
<div id="cost">Loading costs...</div>

<h2>Workers</h2>
<table id="workers"><tr><th>ID</th><th>Host</th><th>Caps</th><th>Job</th><th>Status</th><th>Last Seen</th></tr></table>

<h2>Jobs</h2>
<table id="jobs"><tr><th>ID</th><th>Status</th><th>Type</th><th>Worker</th><th>Created</th><th>Cost</th></tr></table>

<script>
async function load() {
  const [workers, jobs, costs] = await Promise.all([
    fetch('/api/workers').then(r=>r.json()),
    fetch('/api/jobs').then(r=>r.json()),
    fetch('/api/costs').then(r=>r.json()),
  ]);
  document.getElementById('cost').textContent = `Today: £${costs.total_cost_gbp.toFixed(4)}`;

  const wt = document.getElementById('workers');
  wt.innerHTML = '<tr><th>ID</th><th>Host</th><th>Caps</th><th>Job</th><th>Status</th><th>Last Seen</th></tr>';
  workers.forEach(w => {
    const cls = w.stale ? 'stale' : 'active';
    wt.innerHTML += `<tr><td>${w.worker_id}</td><td>${w.hostname||''}</td><td>${(w.capabilities||[]).join(', ')}</td><td>${w.current_job||'-'}</td><td class="${cls}">${w.stale?'stale':'alive'}</td><td>${(w.timestamp||'').slice(0,19)}</td></tr>`;
  });

  const jt = document.getElementById('jobs');
  jt.innerHTML = '<tr><th>ID</th><th>Status</th><th>Type</th><th>Worker</th><th>Created</th><th>Cost</th></tr>';
  jobs.forEach(j => {
    const cls = j.status || '';
    jt.innerHTML += `<tr><td>${j.job_id}</td><td><span class="badge ${cls}">${j.status}</span></td><td>${j.task_type||''}</td><td>${j.worker_id||'-'}</td><td>${(j.created_at||'').slice(0,19)}</td><td>${j.cost_estimate!=null?'£'+j.cost_estimate.toFixed(4):'-'}</td></tr>`;
  });
}
load();
</script>
</body>
</html>"""


if __name__ == "__main__":
    import uvicorn

    cfg.ensure_lab_dirs()
    uvicorn.run(app, host="0.0.0.0", port=8420)
