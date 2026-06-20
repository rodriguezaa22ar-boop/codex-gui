#!/usr/bin/env python3
"""Atlas Builder web monitor.

Serves a browser UI and JSON endpoint for live builder machine telemetry.
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import subprocess
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any


REMOTE_METRICS_PY = r"""
import glob
import json
import os
import time


def read_bytes(path):
    try:
        with open(path, "r", encoding="utf-8") as handle:
            return int(float(handle.read().strip()))
    except (FileNotFoundError, ValueError, OSError):
        return None


def read_text(path):
    try:
        with open(path, "r", encoding="utf-8") as handle:
            return handle.read().strip()
    except OSError:
        return None


def parse_meminfo():
    data = {}
    with open("/proc/meminfo", "r", encoding="utf-8") as handle:
        for line in handle:
            if ":" not in line:
                continue
            key, raw = line.split(":", 1)
            value = raw.strip().split()[0]
            try:
                data[key.strip()] = int(value)
            except ValueError:
                continue
    return data


def snapshot_mem():
    meminfo = parse_meminfo()
    total_kb = meminfo.get("MemTotal")
    available_kb = meminfo.get("MemAvailable")
    free_kb = meminfo.get("MemFree")
    buffered_kb = meminfo.get("Buffers")
    cached_kb = meminfo.get("Cached")
    if total_kb is None:
        return None
    avail = available_kb or free_kb or 0
    used_kb = total_kb - avail
    percent = (used_kb / total_kb * 100.0) if total_kb else 0.0

    swap_total = meminfo.get("SwapTotal", 0)
    swap_free = meminfo.get("SwapFree", 0)
    swap_used = max(swap_total - swap_free, 0)
    swap_percent = (swap_used / swap_total * 100.0) if swap_total else 0.0

    return {
        "total_mib": total_kb * 1024 // 1024,
        "used_mib": used_kb * 1024 // 1024,
        "available_mib": avail * 1024 // 1024,
        "free_mib": (free_kb or 0) * 1024 // 1024,
        "buffered_mib": (buffered_kb or 0) * 1024 // 1024,
        "cached_mib": (cached_kb or 0) * 1024 // 1024,
        "percent": round(percent, 2),
        "swap_total_mib": swap_total * 1024 // 1024,
        "swap_used_mib": swap_used * 1024 // 1024,
        "swap_percent": round(swap_percent, 2),
    }


def read_cpu_percent():
    def read_cpu_fields():
        with open("/proc/stat", "r", encoding="utf-8") as handle:
            for line in handle:
                if not line.startswith("cpu "):
                    continue
                fields = [int(x) for x in line.split()[1:]]
                user, nice, system, idle, iowait, irq, softirq, steal, *_rest = fields + [0] * 10
                total = sum(fields)
                idle_total = idle + iowait
                return total, idle_total
        raise RuntimeError("/proc/stat missing cpu line")

    first_total, first_idle = read_cpu_fields()
    time.sleep(0.4)
    second_total, second_idle = read_cpu_fields()
    total_delta = max(second_total - first_total, 1)
    idle_delta = max(second_idle - first_idle, 0)
    return 100.0 * (1.0 - idle_delta / total_delta)


def snapshot_disk():
    roots = ("/", "/home")
    mounts = {}
    for path in roots:
        try:
            stat = os.statvfs(path)
            total = stat.f_blocks * stat.f_frsize
            available = stat.f_bavail * stat.f_frsize
            free = stat.f_bfree * stat.f_frsize
            used = total - free
            mounts[path] = {
                "total_gb": round(total / 1024 ** 3, 2),
                "used_gb": round(used / 1024 ** 3, 2),
                "free_gb": round((available if available >= 0 else free) / 1024 ** 3, 2),
                "percent": round((used / total * 100.0) if total else 0.0, 2),
            }
        except OSError:
            continue
    return mounts


def snapshot_loadavg():
    with open("/proc/loadavg", "r", encoding="utf-8") as handle:
        values = handle.read().split()
    return {
        "1m": float(values[0]),
        "5m": float(values[1]),
        "15m": float(values[2]),
        "processes": values[3],
    }


def snapshot_uptime():
    uptime_seconds = float(open("/proc/uptime", "r", encoding="utf-8").read().split()[0])
    return int(uptime_seconds)


def snapshot_battery():
    candidates = sorted(glob.glob("/sys/class/power_supply/BAT*"))
    if not candidates:
        return {"present": False}
    bat = candidates[0]
    charge_now = read_text(f"{bat}/charge_now")
    charge_full = read_text(f"{bat}/charge_full")
    energy_now = read_text(f"{bat}/energy_now")
    energy_full = read_text(f"{bat}/energy_full")
    capacity = read_text(f"{bat}/capacity")

    unit = ""
    if charge_now is not None and charge_full is not None:
        numerator = float(charge_now)
        denominator = float(charge_full)
        unit = "charge"
    elif energy_now is not None and energy_full is not None:
        numerator = float(energy_now)
        denominator = float(energy_full)
        unit = "energy"
    elif capacity is not None:
        numerator = float(capacity)
        denominator = 100.0
        unit = "capacity"
    else:
        numerator = None
        denominator = None

    percent = None
    if numerator is not None and denominator:
        percent = round(numerator / denominator * 100.0, 2)

    return {
        "present": True,
        "path": bat,
        "status": read_text(f"{bat}/status"),
        "model": read_text(f"{bat}/model_name") or read_text(f"{bat}/type"),
        "capacity_percent": percent,
        "unit": unit,
    }


def snapshot_temps():
    temps = []
    for path in glob.glob("/sys/class/thermal/thermal_zone*/temp"):
        zone = path.split("/")[-2]
        value = read_text(path)
        if value is None:
            continue
        milli = int(float(value))
        celsius = round(milli / 1000.0, 1)
        name_path = path.replace("temp", "type")
        name = read_text(name_path) or zone
        if celsius < -100 or celsius > 200:
            continue
        temps.append({"name": name, "celsius": celsius})
    return temps[:8]


def snapshot_network():
    lines = []
    with open("/proc/net/dev", "r", encoding="utf-8") as handle:
        raw = handle.read().splitlines()
    for line in raw[2:]:
        if ":" not in line:
            continue
        iface, data = line.split(":", 1)
        iface = iface.strip()
        fields = data.split()
        if iface == "lo" or len(fields) < 16:
            continue
        lines.append({
            "iface": iface,
            "rx_bytes": int(fields[0]),
            "tx_bytes": int(fields[8]),
        })
    return lines


def snapshot_processes():
    import subprocess as sp

    try:
        output = sp.check_output(
            [
                "ps",
                "-eo",
                "pid,user,%cpu,%mem,etime,time,comm",
                "--sort=-%cpu",
            ],
            text=True,
            stderr=sp.DEVNULL,
            timeout=2,
        )
    except (sp.CalledProcessError, FileNotFoundError, OSError):
        return []

    rows = []
    for line in output.splitlines()[1:11]:
        parts = line.split(None, 6)
        if len(parts) < 7:
            continue
        pid, user, cpu, mem, etime, ctime, cmd = parts
        rows.append(
            {
                "pid": int(pid) if pid.isdigit() else pid,
                "user": user,
                "cpu": float(cpu),
                "mem": float(mem),
                "elapsed": etime,
                "time": ctime,
                "command": cmd,
            }
        )
    return rows


payload = {
    "ts": int(time.time()),
    "uptime_sec": snapshot_uptime(),
    "cpu": {
        "percent": round(max(min(read_cpu_percent(), 100.0), 0.0), 2),
        "cores": os.cpu_count() or 0,
    },
    "memory": snapshot_mem(),
    "disk": snapshot_disk(),
    "loadavg": snapshot_loadavg(),
    "battery": snapshot_battery(),
    "temperatures": snapshot_temps(),
    "network": snapshot_network(),
    "top_processes": snapshot_processes(),
}

print(json.dumps(payload, sort_keys=True))
"""


def run_ssh_metrics(host: str, user: str = "ao", timeout: float = 8.0) -> dict[str, Any]:
    """Fetch latest metrics from a remote machine via SSH."""
    command = (
        "tmp=\"${TMPDIR:-/tmp}/atlas_builder_metrics_$$.py\"\n"
        "cat > \"$tmp\" <<'PY'\n"
        + REMOTE_METRICS_PY
        + "\nPY\n"
        "if command -v python3 >/dev/null 2>&1; then\n"
        "  python3 \"$tmp\"\n"
        "elif command -v nix-shell >/dev/null 2>&1; then\n"
        "  nix-shell -p python3 --run \"python3 $tmp\"\n"
        "else\n"
        "  echo '{\"error\":\"python3 unavailable\"}' >&2\n"
        "  rm -f \"$tmp\"\n"
        "  exit 127\n"
        "fi\n"
        "status=$?\n"
        "rm -f \"$tmp\"\n"
        "exit \"$status\"\n"
    )
    target = f"{user}@{host}" if user else host
    result = subprocess.run(
        [
            "ssh",
            "-o",
            "BatchMode=yes",
            "-o",
            f"ConnectTimeout={int(max(1, timeout))}",
            "-o",
            "StrictHostKeyChecking=accept-new",
            target,
            command,
        ],
        check=False,
        capture_output=True,
        text=True,
        timeout=timeout,
    )

    if result.returncode != 0:
        stderr = (result.stderr or "").strip()
        stdout = (result.stdout or "").strip()
        raise RuntimeError(stderr or stdout or "SSH command failed")

    text = (result.stdout or "").strip()
    if not text:
        raise RuntimeError("empty metrics output")
    try:
        payload_start = text.find("{")
        payload_end = text.rfind("}")
        if payload_start == -1 or payload_end <= payload_start:
            raise RuntimeError(f"invalid remote metrics payload: {text[:200]}")
        text = text[payload_start : payload_end + 1]
        return json.loads(text)
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"invalid remote metrics payload: {text[:200]}") from exc


class MetricSnapshot:
    def __init__(self, host: str, user: str, interval: float, timeout: float) -> None:
        self.host = host
        self.user = user
        self.interval = interval
        self.timeout = timeout
        self.lock = threading.Lock()
        self.last_refresh: int = 0
        self.payload: dict[str, Any] = {
            "status": "pending",
            "detail": "Collecting initial sample",
            "ts": int(time.time()),
        }
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._loop, daemon=True)

    def start(self) -> None:
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        if self._thread.is_alive():
            self._thread.join(timeout=1.0)

    def _loop(self) -> None:
        while not self._stop.is_set():
            self.refresh(force=True)
            if self._stop.wait(self.interval):
                break

    def refresh(self, force: bool = False) -> dict[str, Any]:
        now = time.time()
        with self.lock:
            if not force and now - self.last_refresh < self.interval * 0.8:
                return self.payload

        try:
            metrics = run_ssh_metrics(self.host, self.user, timeout=self.timeout)
            snapshot = {
                "status": "ok",
                "detail": "",
                "host": self.host,
                "user": self.user,
                **metrics,
            }
        except Exception as exc:
            snapshot = {
                "status": "error",
                "detail": str(exc),
                "host": self.host,
                "user": self.user,
                "ts": int(time.time()),
            }

        with self.lock:
            self.payload = snapshot
            self.payload["refreshed_at"] = dt.datetime.utcnow().isoformat() + "Z"
            self.last_refresh = now
        return self.payload

    def current(self) -> dict[str, Any]:
        return self.refresh(force=False)


class MonitorHandler(BaseHTTPRequestHandler):
    page: str = ""
    snapshot: MetricSnapshot | None = None

    def _json(self, payload: dict[str, Any], status: int = 200) -> None:
        text = json.dumps(payload)
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(text.encode("utf-8"))

    def do_GET(self) -> None:
        if not self.snapshot:
            self._json({"error": "monitor not initialized"}, status=500)
            return

        if self.path in {"/", "/index.html", ""}:
            self._render_index()
            return

        if self.path.startswith("/api/metrics"):
            self._json(self.snapshot.current())
            return

        self._json({"error": "not found"}, status=404)

    def _render_index(self) -> None:
        page = self.page or PAGE
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.end_headers()
        self.wfile.write(page.encode("utf-8"))

    def log_message(self, fmt: str, *args: object) -> None:
        return





PAGE = """<!doctype html>
<html lang=\"en\">
<head>
  <meta charset=\"utf-8\" />
  <meta name=\"viewport\" content=\"width=device-width, initial-scale=1\" />
  <title>Atlas Builder Monitor</title>
  <style>
    :root {
      --bg: #060a13;
      --bg-soft: #0d1322;
      --panel: rgba(17, 26, 45, 0.88);
      --panel-alt: rgba(24, 36, 60, 0.75);
      --line: rgba(136, 160, 214, 0.28);
      --text: #edf3ff;
      --muted: #96a5bf;
      --accent: #4dd3b0;
      --accent-2: #5eb5ff;
      --warn: #f5a524;
      --bad: #ff6b6b;
      --good: #5fe3ad;
    }

    * { box-sizing: border-box; }
    html, body {
      margin: 0;
      padding: 0;
      min-height: 100%;
      background:
        radial-gradient(circle at 14% 8%, rgba(93, 183, 255, 0.14), transparent 32%),
        radial-gradient(circle at 86% 0%, rgba(77, 211, 176, 0.12), transparent 38%),
        linear-gradient(160deg, var(--bg-soft), var(--bg));
      color: var(--text);
      font: 14px/1.45 ui-sans-serif, system-ui, -apple-system, Segoe UI, Roboto, Ubuntu, sans-serif;
    }
    body::before {
      content: '';
      position: fixed;
      inset: 0;
      background:
        repeating-linear-gradient(
          120deg,
          rgba(255, 255, 255, 0.025),
          rgba(255, 255, 255, 0.025) 1px,
          transparent 1px,
          transparent 3px
        );
      opacity: 0.3;
      pointer-events: none;
      z-index: -1;
    }
    .wrap {
      max-width: 1300px;
      margin: 0 auto;
      padding: 24px;
    }
    .header {
      display: flex;
      justify-content: space-between;
      align-items: flex-end;
      gap: 12px;
      flex-wrap: wrap;
    }
    .eyebrow {
      margin: 0;
      font-size: 0.72rem;
      letter-spacing: 0.12em;
      text-transform: uppercase;
      color: var(--muted);
    }
    h1 {
      margin: 4px 0 0;
      font-size: 1.58rem;
      letter-spacing: 0.01em;
    }
    .header-right {
      display: flex;
      gap: 10px;
      align-items: center;
      flex-wrap: wrap;
      justify-content: flex-end;
    }
    .status, .metric-chip {
      padding: 7px 11px;
      border: 1px solid rgba(255, 255, 255, 0.22);
      border-radius: 999px;
      color: var(--muted);
      font-weight: 600;
      font-size: 0.85rem;
      letter-spacing: 0.01em;
      backdrop-filter: blur(4px);
      background: rgba(255, 255, 255, 0.03);
      display: inline-flex;
      align-items: center;
      gap: 8px;
    }
    .status:before,
    .metric-chip:before {
      content: '';
      width: 8px;
      height: 8px;
      border-radius: 99px;
      background: var(--muted);
    }
    .ok { color: var(--good); }
    .ok:before { background: var(--good); }
    .bad { color: var(--bad); }
    .bad:before { background: var(--bad); }
    .warn { color: var(--warn); }
    .warn:before { background: var(--warn); }
    .metric-chip.ok:before { background: var(--good); }

    .grid {
      margin-top: 16px;
      display: grid;
      grid-template-columns: repeat(auto-fit, minmax(220px, 1fr));
      gap: 14px;
    }
    .card {
      background: linear-gradient(160deg, var(--panel), var(--panel-alt));
      border: 1px solid var(--line);
      border-radius: 16px;
      padding: 14px;
      min-height: 132px;
      box-shadow: 0 20px 40px rgba(0, 0, 0, 0.32);
      position: relative;
      overflow: hidden;
    }
    .metric-head {
      display: flex;
      justify-content: space-between;
      align-items: center;
      gap: 8px;
    }
    .label {
      color: var(--muted);
      font-size: 0.8rem;
      text-transform: uppercase;
      letter-spacing: 0.07em;
    }
    .trend {
      color: var(--muted);
      font-size: 0.77rem;
      white-space: nowrap;
    }
    .value {
      font-size: 1.52rem;
      font-weight: 700;
      margin: 8px 0 5px;
      letter-spacing: -0.01em;
    }
    .meta {
      color: var(--muted);
      font-size: 0.88rem;
      line-height: 1.35;
    }
    .bar {
      margin-top: 10px;
      height: 10px;
      border-radius: 99px;
      background: rgba(255, 255, 255, 0.12);
      border: 1px solid rgba(255, 255, 255, 0.18);
      overflow: hidden;
    }
    .bar > i {
      display: block;
      height: 100%;
      width: 0;
      border-radius: 99px;
      background: linear-gradient(90deg, var(--accent), var(--accent-2));
      transition: width 260ms ease, filter 260ms ease;
    }
    .sparkline {
      margin-top: 8px;
      display: flex;
      align-items: end;
      gap: 3px;
      height: 24px;
    }
    .spark {
      flex: 1;
      min-height: 3px;
      border-radius: 4px;
      background: linear-gradient(180deg, rgba(94, 181, 255, 0.96), rgba(77, 211, 176, 0.96));
      opacity: 0.9;
    }
    .layout {
      margin-top: 14px;
      display: grid;
      grid-template-columns: minmax(320px, 2fr) minmax(320px, 2fr);
      gap: 14px;
    }
    .wide { grid-column: 1 / -1; }
    .table-wrap {
      margin-top: 8px;
      border: 1px solid var(--line);
      border-radius: 12px;
      background: rgba(255, 255, 255, 0.02);
      overflow: hidden;
    }
    table {
      width: 100%;
      border-collapse: collapse;
      font-size: 0.9rem;
    }
    th, td {
      border-bottom: 1px solid var(--line);
      padding: 9px 8px;
      text-align: left;
    }
    th { color: var(--muted); font-weight: 600; background: rgba(255, 255, 255, 0.02); }
    .muted { color: var(--muted); }
    .muted-small { color: var(--muted); font-size: 0.82rem; }
    .temp-item {
      display: flex;
      justify-content: space-between;
      gap: 10px;
      padding: 8px 0;
      align-items: center;
    }
    .temp-item + .temp-item { border-top: 1px dashed var(--line); }
    .temp-pill {
      color: var(--text);
      padding: 3px 7px;
      border-radius: 999px;
      font-size: 0.76rem;
      background: rgba(255, 255, 255, 0.05);
      border: 1px solid rgba(255,255,255,0.14);
    }
    .footer {
      margin-top: 16px;
      color: var(--muted);
      font-size: 0.82rem;
      padding-bottom: 20px;
    }
    pre {
      white-space: pre-wrap;
      margin: 0;
      font-size: 0.84rem;
      color: var(--muted);
      border: 1px solid var(--line);
      padding: 8px;
      border-radius: 10px;
      background: rgba(255, 255, 255, 0.02);
      max-height: 280px;
      overflow: auto;
    }

    @media (max-width: 860px) {
      .layout { grid-template-columns: 1fr; }
      .wrap { padding: 14px; }
      h1 { font-size: 1.29rem; }
      .header-right { width: 100%; justify-content: flex-start; }
    }
  </style>
</head>
<body>
  <div class="wrap">
    <div class="header">
      <div>
        <p class="eyebrow">Atlas Builder Command Node</p>
        <h1>Builder Monitor</h1>
      </div>
      <div class="header-right">
        <div id="health" class="metric-chip">Health: n/a</div>
        <div id="status" class="status">initializing…</div>
      </div>
    </div>

    <div class="grid">
      <div class="card">
        <div class="metric-head">
          <div class="label">CPU Utilization</div>
          <div class="trend" id="cpu-trend">n/a</div>
        </div>
        <div class="value" id="cpu">n/a</div>
        <div class="meta" id="cpu-meta">cores: n/a · load 0m/5m/15m: n/a</div>
        <div class="bar"><i id="cpu-bar"></i></div>
        <div class="sparkline" id="cpu-spark"></div>
      </div>
      <div class="card">
        <div class="metric-head">
          <div class="label">Memory</div>
          <div class="trend" id="mem-trend">n/a</div>
        </div>
        <div class="value" id="mem">n/a</div>
        <div class="meta" id="mem-meta">swap: n/a</div>
        <div class="bar"><i id="mem-bar"></i></div>
        <div class="sparkline" id="mem-spark"></div>
      </div>
      <div class="card">
        <div class="metric-head">
          <div class="label">Battery</div>
          <div class="trend" id="bat-trend">n/a</div>
        </div>
        <div class="value" id="bat">n/a</div>
        <div class="meta" id="bat-meta">state: n/a</div>
        <div class="bar"><i id="bat-bar"></i></div>
      </div>
      <div class="card">
        <div class="metric-head">
          <div class="label">Uptime</div>
          <div class="trend">live</div>
        </div>
        <div class="value" id="uptime">n/a</div>
        <div class="meta" id="uptime-meta">host: n/a</div>
      </div>
      <div class="card">
        <div class="metric-head">
          <div class="label">Load</div>
          <div class="trend" id="load-trend">n/a</div>
        </div>
        <div class="value" id="load">n/a</div>
        <div class="meta" id="load-meta">processes: n/a</div>
        <div class="bar"><i id="load-bar"></i></div>
        <div class="sparkline" id="load-spark"></div>
      </div>
      <div class="card">
        <div class="metric-head">
          <div class="label">Disk / Home</div>
          <div class="trend">usage</div>
        </div>
        <div class="value" id="disk-home">n/a</div>
        <div class="meta" id="disk-root">/ root: n/a</div>
        <div class="meta" id="disk-meta">/home: n/a</div>
      </div>
    </div>

    <div class="layout">
      <div class="card wide">
        <div class="label">Temperatures</div>
        <div class="meta" id="temp-empty">no temperature sensors detected</div>
        <div id="temp-grid"></div>
      </div>
      <div class="card wide">
        <div class="label">Network (bytes)</div>
        <div class="meta">counters are cumulative since node boot</div>
        <div class="table-wrap">
          <table>
            <thead><tr><th>Interface</th><th>RX</th><th>TX</th></tr></thead>
            <tbody id="network"></tbody>
          </table>
        </div>
      </div>
      <div class="card wide">
        <div class="label">Top Processes</div>
        <div class="meta">CPU + memory leaders (top 10)</div>
        <div class="table-wrap">
          <table>
            <thead><tr><th>pid</th><th>user</th><th>%CPU</th><th>%MEM</th><th>elapsed</th><th>cmd</th></tr></thead>
            <tbody id="processes"></tbody>
          </table>
        </div>
      </div>
      <div class="card wide">
        <div class="label">Raw payload</div>
        <pre id="raw"></pre>
      </div>
    </div>

    <div class="footer">Live polling every %%INTERVAL%%s · SSH target: %%TARGET%%</div>
  </div>

  <script>
    const INTERVAL_MS = %%INTERVAL_MS%%;
    const statusEl = document.getElementById('status');
    const healthEl = document.getElementById('health');
    const history = {
      cpu: [],
      mem: [],
      load: [],
      battery: [],
    };
    const HISTORY_SIZE = 18;

    function clamp(value, min, max) {
      const number = Number(value);
      if (!Number.isFinite(number)) return min;
      return Math.min(max, Math.max(min, number));
    }

    function setBar(id, pct) {
      const normalized = clamp(pct, 0, 100);
      const el = document.getElementById(id);
      if (!el) return;
      el.style.width = `${normalized}%`;
    }

    function setText(id, value, fallback = 'n/a') {
      const el = document.getElementById(id);
      if (!el) return;
      const text = value === null || value === undefined || value === '' ? fallback : value;
      el.textContent = String(text);
    }

    function setClass(id, klass) {
      const el = document.getElementById(id);
      if (!el) return;
      el.className = `trend${klass ? ` ${klass}` : ''}`;
    }

    function pushHistory(key, value) {
      const list = history[key];
      if (!Array.isArray(list)) return;
      list.push(clamp(value, 0, 100));
      if (list.length > HISTORY_SIZE) {
        list.shift();
      }
    }

    function renderSparkline(id, values) {
      const el = document.getElementById(id);
      if (!el) return;

      const sanitized = (values || []).filter((v) => Number.isFinite(v));
      if (!sanitized.length) {
        el.innerHTML = '';
        return;
      }

      el.innerHTML = sanitized
        .map((value) => {
          const height = Math.max(12, Math.round(clamp(value, 0, 100)));
          return `<span class="spark" style="height:${height}%"></span>`;
        })
        .join('');
    }

    function trendText(current, previous, biggerIsBetter) {
      if (!Number.isFinite(current)) {
        return {text: 'n/a', klass: ''};
      }
      if (!Number.isFinite(previous)) {
        return {text: 'new', klass: ''};
      }

      const delta = current - previous;
      if (Math.abs(delta) < 0.15) {
        return {text: `→ ${current.toFixed(1)}%`, klass: ''};
      }

      const arrow = delta > 0 ? '↑' : '↓';
      const value = Math.abs(delta).toFixed(1);
      const text = `${arrow} ${value}%`;

      if (biggerIsBetter) {
        if (delta >= 8) return {text, klass: 'ok'};
        if (delta <= -8) return {text, klass: 'bad'};
        return {text, klass: 'warn'};
      }

      if (delta <= -8) return {text, klass: 'ok'};
      if (delta >= 8) return {text, klass: 'bad'};
      return {text, klass: 'warn'};
    }

    function renderTrend(id, current, previous, biggerIsBetter = false) {
      const {text, klass} = trendText(current, previous, biggerIsBetter);
      setText(id, text);
      setClass(id, klass);
    }

    function updateHealth(cpuPercent, memPercent, loadNormalized, tempPeak, batteryPercent) {
      if (!healthEl) return;
      if (!Number.isFinite(cpuPercent) || !Number.isFinite(memPercent) || !Number.isFinite(loadNormalized)) {
        healthEl.textContent = 'Health: n/a (error)';
        healthEl.className = 'metric-chip bad';
        return;
      }

      let score = 100;
      score -= clamp(cpuPercent * 0.35, 0, 35);
      score -= clamp(memPercent * 0.30, 0, 30);
      score -= clamp(loadNormalized * 0.25, 0, 20);
      if (Number.isFinite(tempPeak)) {
        score -= clamp((tempPeak - 75) * 0.6, 0, 25);
      }
      if (batteryPercent !== null && Number.isFinite(batteryPercent)) {
        score -= clamp((100 - batteryPercent) * 0.08, 0, 8);
      }

      const normalized = clamp(Math.round(score), 0, 100);
      if (normalized >= 85) {
        healthEl.className = 'metric-chip ok';
      } else if (normalized >= 65) {
        healthEl.className = 'metric-chip warn';
      } else {
        healthEl.className = 'metric-chip bad';
      }

      let label = 'degraded';
      if (normalized >= 85) {
        label = 'excellent';
      } else if (normalized >= 72) {
        label = 'healthy';
      } else if (normalized >= 55) {
        label = 'watch';
      }

      healthEl.textContent = `Health: ${normalized}% · ${label}`;
    }

    function render(d) {
      const stateOk = d.status === 'ok';
      statusEl.textContent = `${stateOk ? 'online' : 'error'} · ${d.detail || 'ok'} · last: ${d.refreshed_at || ''}`;
      statusEl.className = stateOk ? 'status ok' : 'status bad';

      const cpu = d.cpu || {};
      const mem = d.memory || {};
      const bat = d.battery || {};
      const load = d.loadavg || {};
      const net = d.network || [];
      const procs = d.top_processes || [];
      const disks = d.disk || {};
      const temps = d.temperatures || [];

      const cpuPercent = Number(cpu.percent || 0);
      const memPercent = Number(mem.percent || 0);
      const batPercent = bat.present ? Number(bat.capacity_percent || 0) : null;
      const loadValue = Number(load['1m'] || 0) / Math.max(Number(cpu.cores || 1), 1) * 100;
      const loadNormalized = Number.isFinite(loadValue) ? loadValue : 0;
      const lastTemp = temps.length ? Math.max(...temps.map((item) => Number(item.celsius || -Infinity)).filter(Number.isFinite)) : null;
      const cpuPrev = history.cpu[history.cpu.length - 1];
      const memPrev = history.mem[history.mem.length - 1];
      const loadPrev = history.load[history.load.length - 1];
      const batteryPrev = history.battery[history.battery.length - 1];

      pushHistory('cpu', cpuPercent);
      pushHistory('mem', memPercent);
      pushHistory('load', loadNormalized);
      if (bat.present && Number.isFinite(batPercent)) {
        pushHistory('battery', batPercent);
      } else {
        pushHistory('battery', 0);
      }

      const cpuTrendPrev = history.cpu.length > 1 ? history.cpu[history.cpu.length - 2] : cpuPrev;
      const memTrendPrev = history.mem.length > 1 ? history.mem[history.mem.length - 2] : memPrev;
      const loadTrendPrev = history.load.length > 1 ? history.load[history.load.length - 2] : loadPrev;
      const batTrendPrev = history.battery.length > 1 ? history.battery[history.battery.length - 2] : batteryPrev;

      setText('cpu', `${cpuPercent.toFixed(1)}%`);
      setText('cpu-meta', `cores: ${cpu.cores || 'n/a'} · load 0m/5m/15m: ${load['1m'] || 'n/a'} / ${load['5m'] || 'n/a'} / ${load['15m'] || 'n/a'}`);
      setBar('cpu-bar', cpuPercent);
      renderSparkline('cpu-spark', history.cpu);
      renderTrend('cpu-trend', cpuPercent, cpuTrendPrev, false);

      setText('mem', `${memPercent.toFixed(1)}% (${humanBytes((mem.total_mib || 0) * 1024 * 1024)})`);
      setText(
        'mem-meta',
        `used ${humanBytes((mem.used_mib || 0) * 1024 * 1024)} free ${humanBytes((mem.available_mib || 0) * 1024 * 1024)} | swap ${humanBytes((mem.swap_used_mib || 0) * 1024 * 1024)} / ${humanBytes((mem.swap_total_mib || 0) * 1024 * 1024)} (${Number(mem.swap_percent || 0).toFixed(1)}%)`
      );
      setBar('mem-bar', memPercent);
      renderSparkline('mem-spark', history.mem);
      renderTrend('mem-trend', memPercent, memTrendPrev, false);

      if (bat.present) {
        setText('bat', batPercent == null || Number.isNaN(batPercent) ? 'n/a' : `${batPercent.toFixed(0)}%`);
        setText('bat-meta', `status: ${bat.status || 'n/a'} · model: ${bat.model || 'n/a'} · source: ${bat.unit || 'n/a'}`);
        setBar('bat-bar', batPercent);
        renderTrend('bat-trend', batPercent, batTrendPrev, true);
      } else {
        setText('bat', 'no battery');
        setText('bat-meta', 'AC-powered desktop or headless node.');
        setBar('bat-bar', 0);
        setText('bat-trend', 'n/a');
        setClass('bat-trend', '');
      }

      setText('uptime', humanSeconds(d.uptime_sec || 0));
      setText('uptime-meta', `host: ${d.host || ''} · user: ${d.user || ''}`);

      setText('load', `${Number(load['1m'] || 0).toFixed(2)} / ${Number(load['5m'] || 0).toFixed(2)} / ${Number(load['15m'] || 0).toFixed(2)}`);
      setText('load-meta', `load-1 normalized: ${humanPercent(loadNormalized)}`);
      setBar('load-bar', Math.min(loadNormalized, 100));
      renderSparkline('load-spark', history.load);
      renderTrend('load-trend', loadNormalized, loadTrendPrev, false);

      const root = disks['/'] || {};
      const home = disks['/home'] || {};
      setText('disk-root', `/ root: ${humanBytes((root.total_gb || 0) * 1024 * 1024 * 1024)} total · ${humanPercent(root.percent || 0)} used`);
      setText('disk-meta', `/home: ${humanBytes((home.total_gb || 0) * 1024 * 1024 * 1024)} total · ${humanPercent(home.percent || 0)} used`);
      setText('disk-home', `${humanPercent(home.percent || 0)} (${humanBytes((home.used_gb || 0) * 1024 * 1024 * 1024)} used)`);

      const tempArea = document.getElementById('temp-grid');
      if (!temps.length) {
        tempArea.innerHTML = '<div class="muted-small">No /sys/class/thermal temperature endpoints available.</div>';
      } else {
        tempArea.innerHTML = temps
          .map((item) => {
            const celsius = Number(item.celsius);
            const level = clamp((celsius + 20) * 1.25, 0, 100);
            return `<div class="temp-item"><span>${escapeHtml(item.name)}</span><span class="temp-pill">${celsius}°C</span><span class="bar"><i style="width:${level}%"></i></span></div>`;
          })
          .join('');
      }

      const nbody = document.getElementById('network');
      nbody.innerHTML = (net || []).map((item) => {
        return `<tr><td>${escapeHtml(item.iface)}</td><td>${humanBytes(item.rx_bytes || 0)}</td><td>${humanBytes(item.tx_bytes || 0)}</td></tr>`;
      }).join('') || '<tr><td colspan="3">No interfaces</td></tr>';

      const pbody = document.getElementById('processes');
      pbody.innerHTML = (procs || []).map((item) => {
        return `<tr><td>${item.pid}</td><td>${escapeHtml(item.user || '')}</td><td>${Number(item.cpu || 0).toFixed(2)}</td><td>${Number(item.mem || 0).toFixed(2)}</td><td>${escapeHtml(item.elapsed || '')}</td><td>${escapeHtml(item.command || '')}</td></tr>`;
      }).join('') || '<tr><td colspan="6">No process snapshot</td></tr>';

      updateHealth(cpuPercent, memPercent, loadNormalized, lastTemp, batPercent);
      setText('raw', JSON.stringify(d, null, 2));
    }

    function humanPercent(v) {
      return `${Number(v || 0).toFixed(1)}%`;
    }

    function humanBytes(v) {
      const units = ['B', 'KB', 'MB', 'GB', 'TB'];
      let val = Number(v || 0);
      let unitIndex = 0;
      while (val >= 1024 && unitIndex < units.length - 1) {
        val /= 1024;
        unitIndex += 1;
      }
      return `${val.toFixed(1)} ${units[unitIndex]}`;
    }

    function humanSeconds(sec) {
      const total = Math.floor(Number(sec || 0));
      const d = Math.floor(total / 86400);
      const h = Math.floor((total % 86400) / 3600);
      const m = Math.floor((total % 3600) / 60);
      const s = total % 60;
      const parts = [];
      if (d) parts.push(`${d}d`);
      if (h) parts.push(`${h}h`);
      if (m) parts.push(`${m}m`);
      parts.push(`${s}s`);
      return parts.join(' ');
    }

    function escapeHtml(text) {
      if (text === null || text === undefined) return '';
      return String(text)
        .replaceAll('&', '&amp;')
        .replaceAll('<', '&lt;')
        .replaceAll('>', '&gt;')
        .replaceAll('"', '&quot;')
        .replaceAll("'", '&#39;');
    }

    async function refresh() {
      try {
        const result = await fetch('/api/metrics', {cache: 'no-store'});
        if (!result.ok) throw new Error(`http ${result.status}`);
        const data = await result.json();
        render(data);
      } catch (err) {
        statusEl.textContent = `request failed: ${err.message}`;
        statusEl.className = 'status bad';
      }
    }

    refresh();
    setInterval(refresh, INTERVAL_MS);
  </script>
</body>
</html>
"""


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Atlas Builder web monitor")
    parser.add_argument("--host", default="atlas-builder", help="SSH target host")
    parser.add_argument("--user", default="ao", help="SSH user")
    parser.add_argument("--bind", default="127.0.0.1", help="Local bind host")
    parser.add_argument("--port", type=int, default=9760, help="Local listen port")
    parser.add_argument("--interval", type=float, default=4.0, help="Poll interval in seconds")
    parser.add_argument("--timeout", type=float, default=10.0, help="SSH timeout in seconds")
    return parser.parse_args()


def run_server(args: argparse.Namespace) -> None:
    status_target = f"{args.user}@{args.host}"
    page = PAGE.replace("%%INTERVAL%%", f"{args.interval}")
    page = page.replace("%%INTERVAL_MS%%", f"{int(max(1.0, args.interval) * 1000)}")
    page = page.replace("%%TARGET%%", f"{status_target}")

    snapshot = MetricSnapshot(args.host, args.user, args.interval, args.timeout)
    snapshot.start()

    MonitorHandler.snapshot = snapshot
    MonitorHandler.page = page

    server = ThreadingHTTPServer((args.bind, args.port), MonitorHandler)
    try:
        print(f"Atlas Builder Monitor listening on http://{args.bind}:{args.port}")
        print(f"Tracking host: {status_target}")
        print("Press Ctrl+C to stop")
        server.serve_forever(poll_interval=0.5)
    except KeyboardInterrupt:
        pass
    finally:
        server.shutdown()
        snapshot.stop()
        print("Monitor stopped.")


def main() -> None:
    args = parse_args()
    run_server(args)


if __name__ == "__main__":
    main()
