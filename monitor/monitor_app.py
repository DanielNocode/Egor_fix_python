# -*- coding: utf-8 -*-
"""
Telethon Webhook Monitor Dashboard
Flask application for monitoring and controlling send_media and send_text services.
"""
import subprocess
import time
import threading
import os
import json
import re
from datetime import datetime, timedelta
from functools import wraps

from flask import Flask, render_template, jsonify, request, Response
import requests

# -------------------- CONFIG --------------------
MONITOR_PORT = 5099

SERVICES = {
    "send_media": {
        "name": "send-media-rumyantsev",
        "systemd": "send-media-rumyantsev.service",
        "port": 5023,
        "url": "http://127.0.0.1:5023",
    },
    "send_text": {
        "name": "send-text-rumyantsev",
        "systemd": "send-text-rumyantsev.service",
        "port": 5022,
        "url": "http://127.0.0.1:5022",
    },
}

# Basic HTTP auth credentials (change on deployment)
AUTH_USERNAME = os.environ.get("MONITOR_USER", "admin")
AUTH_PASSWORD = os.environ.get("MONITOR_PASS", "telethon2026")

# -------------------- APP -----------------------
app = Flask(__name__)

# -------------------- HEALTH HISTORY ------------
_health_history = {
    "send_media": [],  # list of {"ts": float, "ok": bool}
    "send_text": [],
}
_health_fail_streak = {"send_media": 0, "send_text": 0}
_HEALTH_MAX_HISTORY = 1440  # 24h at 1/min

# -------------------- AUTH ----------------------

def check_auth(username, password):
    return username == AUTH_USERNAME and password == AUTH_PASSWORD


def authenticate():
    return Response(
        "Authentication required", 401,
        {"WWW-Authenticate": 'Basic realm="Telethon Monitor"'},
    )


def requires_auth(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        auth = request.authorization
        if not auth or not check_auth(auth.username, auth.password):
            return authenticate()
        return f(*args, **kwargs)
    return decorated


# -------------------- HELPERS -------------------

def _run_cmd(cmd, timeout=15):
    """Run a shell command and return (returncode, stdout, stderr)."""
    try:
        r = subprocess.run(
            cmd, shell=True, capture_output=True, text=True, timeout=timeout
        )
        return r.returncode, r.stdout.strip(), r.stderr.strip()
    except subprocess.TimeoutExpired:
        return -1, "", "timeout"
    except Exception as e:
        return -1, "", str(e)


def _systemctl_status(service_name):
    """Get systemd service status dict."""
    code, out, err = _run_cmd(f"systemctl is-active {service_name}")
    state = out.strip() if code == 0 else out.strip() or "unknown"

    info = {"state": state, "uptime": "", "memory": "", "cpu": "", "pid": ""}

    code2, out2, _ = _run_cmd(
        f"systemctl show {service_name} "
        "--property=ActiveState,SubState,ExecMainStartTimestamp,"
        "MemoryCurrent,MainPID,CPUUsageNSec"
    )
    if code2 == 0:
        props = {}
        for line in out2.splitlines():
            if "=" in line:
                k, v = line.split("=", 1)
                props[k.strip()] = v.strip()

        info["state"] = props.get("ActiveState", state)
        info["pid"] = props.get("MainPID", "")

        mem_bytes = props.get("MemoryCurrent", "")
        if mem_bytes and mem_bytes != "[not set]":
            try:
                mb = int(mem_bytes) / (1024 * 1024)
                info["memory"] = f"{mb:.1f} MB"
            except ValueError:
                info["memory"] = mem_bytes

        cpu_ns = props.get("CPUUsageNSec", "")
        if cpu_ns and cpu_ns != "[not set]":
            try:
                info["cpu"] = f"{int(cpu_ns) / 1e9:.1f}s"
            except ValueError:
                info["cpu"] = cpu_ns

        ts = props.get("ExecMainStartTimestamp", "")
        if ts and ts != "n/a" and ts != "":
            try:
                dt = datetime.strptime(ts.split(";")[0].strip(), "%a %Y-%m-%d %H:%M:%S %Z")
                delta = datetime.now() - dt
                hours, remainder = divmod(int(delta.total_seconds()), 3600)
                mins, secs = divmod(remainder, 60)
                info["uptime"] = f"{hours}h {mins}m {secs}s"
            except Exception:
                info["uptime"] = ts

    return info


def _fetch_json(url, timeout=5):
    """Fetch JSON from a service endpoint."""
    try:
        r = requests.get(url, timeout=timeout)
        return r.json()
    except Exception:
        return None


def _post_json(url, timeout=30):
    """POST to a service endpoint and return JSON."""
    try:
        r = requests.post(url, timeout=timeout)
        return r.status_code, r.json()
    except Exception as e:
        return 500, {"error": str(e)}


def _get_journalctl_logs(service_name, lines=100, errors_only=False,
                         since=None, until=None, search=None):
    """Fetch logs from journalctl."""
    cmd = f"journalctl -u {service_name} --no-pager -o short-iso"
    if errors_only:
        cmd += " -p err..warning"
    if since:
        cmd += f' --since "{since}"'
    if until:
        cmd += f' --until "{until}"'
    cmd += f" -n {lines}"

    code, out, err = _run_cmd(cmd, timeout=10)
    if code != 0:
        return []

    log_lines = out.splitlines()
    if search:
        search_lower = search.lower()
        log_lines = [l for l in log_lines if search_lower in l.lower()]

    return log_lines


# -------------------- HEALTH CHECK BACKGROUND ---

def _health_check_loop():
    """Background thread: ping /health every 60s, record results."""
    while True:
        for key, svc in SERVICES.items():
            ok = False
            try:
                r = requests.get(f"{svc['url']}/health", timeout=5)
                data = r.json()
                ok = data.get("status") == "ok"
            except Exception:
                ok = False

            _health_history[key].append({"ts": time.time(), "ok": ok})
            if len(_health_history[key]) > _HEALTH_MAX_HISTORY:
                _health_history[key] = _health_history[key][-_HEALTH_MAX_HISTORY:]

            if ok:
                _health_fail_streak[key] = 0
            else:
                _health_fail_streak[key] += 1

        time.sleep(60)


threading.Thread(target=_health_check_loop, daemon=True).start()


# -------------------- ROUTES --------------------

@app.route("/")
@requires_auth
def index():
    return render_template("index.html")


@app.route("/api/status")
@requires_auth
def api_status():
    """Return status of both services."""
    result = {}
    for key, svc in SERVICES.items():
        sys_info = _systemctl_status(svc["systemd"])
        stats = _fetch_json(f"{svc['url']}/stats")
        health = _fetch_json(f"{svc['url']}/health")

        result[key] = {
            "systemd": sys_info,
            "port": svc["port"],
            "health": health,
            "stats": stats,
            "alert": _health_fail_streak.get(key, 0) >= 3,
            "fail_streak": _health_fail_streak.get(key, 0),
        }
    return jsonify(result)


@app.route("/api/logs")
@requires_auth
def api_logs():
    """Fetch logs. Query params: service, lines, errors_only, since, until, search."""
    service = request.args.get("service", "both")
    lines = int(request.args.get("lines", 100))
    errors_only = request.args.get("errors_only", "false") == "true"
    since = request.args.get("since")
    until = request.args.get("until")
    search = request.args.get("search")

    all_logs = []
    services_to_query = []
    if service == "both" or service == "send_media":
        services_to_query.append(("send_media", SERVICES["send_media"]["systemd"]))
    if service == "both" or service == "send_text":
        services_to_query.append(("send_text", SERVICES["send_text"]["systemd"]))

    for svc_key, svc_name in services_to_query:
        log_lines = _get_journalctl_logs(
            svc_name, lines=lines, errors_only=errors_only,
            since=since, until=until, search=search,
        )
        for line in log_lines:
            all_logs.append({"service": svc_key, "line": line})

    return jsonify({"logs": all_logs})


@app.route("/api/control", methods=["POST"])
@requires_auth
def api_control():
    """Control services. Body: {action, service}."""
    data = request.get_json(force=True) or {}
    action = data.get("action")
    service = data.get("service")

    if service not in SERVICES:
        return jsonify({"error": "unknown service"}), 400

    svc_name = SERVICES[service]["systemd"]

    if action in ("start", "stop", "restart"):
        code, out, err = _run_cmd(f"systemctl {action} {svc_name}", timeout=30)
        return jsonify({
            "status": "ok" if code == 0 else "error",
            "output": out,
            "error": err,
        })
    elif action == "reload_cache":
        url = f"{SERVICES[service]['url']}/reload_cache"
        status_code, resp = _post_json(url, timeout=120)
        return jsonify(resp), 200 if status_code < 400 else status_code
    else:
        return jsonify({"error": "unknown action"}), 400


@app.route("/api/clear_flood_wait", methods=["POST"])
@requires_auth
def api_clear_flood_wait():
    """Stop both services, wait 5 min, start them with 60s gap."""
    def _do_clear():
        results = []
        # Stop both
        for key in SERVICES:
            code, out, err = _run_cmd(f"systemctl stop {SERVICES[key]['systemd']}")
            results.append(f"Stop {key}: code={code}")
        # Wait 5 minutes
        time.sleep(300)
        # Start first service
        first = "send_text"
        code, out, err = _run_cmd(f"systemctl start {SERVICES[first]['systemd']}")
        results.append(f"Start {first}: code={code}")
        # Wait 60 seconds
        time.sleep(60)
        # Start second service
        second = "send_media"
        code, out, err = _run_cmd(f"systemctl start {SERVICES[second]['systemd']}")
        results.append(f"Start {second}: code={code}")
        return results

    # Run in background thread
    threading.Thread(target=_do_clear, daemon=True).start()
    return jsonify({
        "status": "ok",
        "message": "Clear flood wait started. Both services stopped. "
                   "Will restart in ~6 minutes.",
    })


@app.route("/api/diagnostics", methods=["POST"])
@requires_auth
def api_diagnostics():
    """Run full diagnostics."""
    report = []

    # 1. Systemctl status
    for key, svc in SERVICES.items():
        code, out, err = _run_cmd(f"systemctl status {svc['systemd']} --no-pager -l")
        report.append({
            "check": f"systemctl status {svc['name']}",
            "output": out or err,
            "ok": "active (running)" in (out or ""),
        })

    # 2. Port check
    code, out, err = _run_cmd("ss -tlnp | grep -E '5022|5023'")
    report.append({
        "check": "Port check (5022, 5023)",
        "output": out or "No ports found listening",
        "ok": bool(out),
    })

    # 3. Last 10 errors from journalctl
    for key, svc in SERVICES.items():
        logs = _get_journalctl_logs(svc["systemd"], lines=10, errors_only=True)
        report.append({
            "check": f"Last 10 errors: {svc['name']}",
            "output": "\n".join(logs) if logs else "No errors",
            "ok": len(logs) == 0,
        })

    # 4. Health endpoints
    for key, svc in SERVICES.items():
        health = _fetch_json(f"{svc['url']}/health")
        report.append({
            "check": f"Health: {svc['name']}",
            "output": json.dumps(health) if health else "No response",
            "ok": health is not None and health.get("status") == "ok",
        })

    # 5. Cache size
    for key, svc in SERVICES.items():
        stats = _fetch_json(f"{svc['url']}/stats")
        if stats:
            report.append({
                "check": f"Cache: {svc['name']}",
                "output": f"cache_size={stats.get('cache_size', '?')}, "
                          f"errors={stats.get('error_count', '?')}, "
                          f"uptime={stats.get('uptime_seconds', '?')}s",
                "ok": (stats.get("cache_size", 0) or 0) > 0,
            })
        else:
            report.append({
                "check": f"Cache: {svc['name']}",
                "output": "Cannot reach /stats endpoint",
                "ok": False,
            })

    return jsonify({"report": report})


@app.route("/api/health_history")
@requires_auth
def api_health_history():
    """Return health check history for both services."""
    result = {}
    for key in SERVICES:
        result[key] = _health_history.get(key, [])[-1440:]
    result["alerts"] = {
        k: _health_fail_streak.get(k, 0) >= 3 for k in SERVICES
    }
    return jsonify(result)


# -------------------- MAIN ---------------------
if __name__ == "__main__":
    app.run(host="0.0.0.0", port=MONITOR_PORT, debug=False)
