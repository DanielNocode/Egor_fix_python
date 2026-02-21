# -*- coding: utf-8 -*-
"""
debug_api.py — Диагностический API для удалённой отладки.

Позволяет смотреть файлы, процессы, порты, логи и статусы сервисов.
Запуск:  python debug_api.py          (порт 5100)
Остановка: Ctrl+C или kill PID

Авторизация: Basic Auth (admin / telethon2026)
"""
import os
import subprocess
import functools

from flask import Flask, request, jsonify, Response

app = Flask(__name__)

AUTH_USER = os.environ.get("DEBUG_USER", "admin")
AUTH_PASS = os.environ.get("DEBUG_PASS", "telethon2026")
DEBUG_PORT = int(os.environ.get("DEBUG_PORT", "5100"))

# Ограничиваем доступ только к рабочим директориям
ALLOWED_ROOTS = ["/root", "/home", "/etc/systemd", "/tmp"]


def check_auth(username, password):
    return username == AUTH_USER and password == AUTH_PASS


def requires_auth(f):
    @functools.wraps(f)
    def decorated(*args, **kwargs):
        auth = request.authorization
        if not auth or not check_auth(auth.username, auth.password):
            return Response(
                "Unauthorized", 401,
                {"WWW-Authenticate": 'Basic realm="Debug API"'},
            )
        return f(*args, **kwargs)
    return decorated


def _safe_path(path: str) -> bool:
    """Проверяем что путь в разрешённых директориях."""
    real = os.path.realpath(path)
    return any(real.startswith(root) for root in ALLOWED_ROOTS)


def _run_cmd(cmd: str, timeout: int = 10) -> str:
    """Выполнить shell-команду и вернуть stdout+stderr."""
    try:
        r = subprocess.run(
            cmd, shell=True, capture_output=True, text=True, timeout=timeout,
        )
        out = r.stdout
        if r.stderr:
            out += "\n--- stderr ---\n" + r.stderr
        return out.strip()
    except subprocess.TimeoutExpired:
        return f"[timeout after {timeout}s]"
    except Exception as e:
        return f"[error: {e}]"


# === Endpoints ================================================================

@app.route("/")
@requires_auth
def index():
    return jsonify({
        "service": "debug_api",
        "endpoints": [
            "GET /ls?path=<dir>",
            "GET /cat?path=<file>&lines=<N>",
            "GET /ps",
            "GET /ports",
            "GET /service?name=<unit>",
            "GET /logs?unit=<name>&lines=<N>",
            "GET /health_check",
            "GET /env",
            "GET /cmd?q=<command>  (ограниченные команды)",
        ],
    })


@app.route("/ls")
@requires_auth
def ls():
    """Список файлов в директории."""
    path = request.args.get("path", "/root/Egor_fix_python")
    if not _safe_path(path):
        return jsonify({"error": "path not allowed"}), 403
    if not os.path.isdir(path):
        return jsonify({"error": "not a directory", "path": path}), 404

    entries = []
    try:
        for name in sorted(os.listdir(path)):
            full = os.path.join(path, name)
            is_dir = os.path.isdir(full)
            size = 0
            if not is_dir:
                try:
                    size = os.path.getsize(full)
                except OSError:
                    pass
            entries.append({"name": name, "is_dir": is_dir, "size": size})
    except PermissionError:
        return jsonify({"error": "permission denied"}), 403

    return jsonify({"path": path, "count": len(entries), "entries": entries})


@app.route("/cat")
@requires_auth
def cat():
    """Прочитать файл (до N строк)."""
    path = request.args.get("path", "")
    lines = int(request.args.get("lines", "200"))
    lines = min(lines, 2000)

    if not path:
        return jsonify({"error": "path is required"}), 400
    if not _safe_path(path):
        return jsonify({"error": "path not allowed"}), 403
    if not os.path.isfile(path):
        return jsonify({"error": "not a file", "path": path}), 404

    try:
        with open(path, "r", errors="replace") as f:
            content = []
            for i, line in enumerate(f):
                if i >= lines:
                    content.append(f"... [truncated at {lines} lines]")
                    break
                content.append(line.rstrip("\n"))
        return jsonify({"path": path, "lines": len(content), "content": "\n".join(content)})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/ps")
@requires_auth
def ps():
    """Список процессов (python, gunicorn, telethon)."""
    out = _run_cmd("ps aux | head -1; ps aux | grep -E 'python|gunicorn|telethon|flask' | grep -v grep")
    return jsonify({"processes": out})


@app.route("/ports")
@requires_auth
def ports():
    """Какие порты слушают."""
    out = _run_cmd("ss -tlnp 2>/dev/null || netstat -tlnp 2>/dev/null")
    return jsonify({"listening": out})


@app.route("/service")
@requires_auth
def service_status():
    """Статус systemd-сервиса."""
    name = request.args.get("name", "telethon-platform")
    # Только буквы, цифры, дефис, подчёркивание
    if not all(c.isalnum() or c in "-_." for c in name):
        return jsonify({"error": "invalid service name"}), 400
    status = _run_cmd(f"systemctl status {name} 2>&1 | head -30")
    return jsonify({"service": name, "status": status})


@app.route("/logs")
@requires_auth
def logs():
    """Логи systemd-юнита."""
    unit = request.args.get("unit", "telethon-platform")
    lines = int(request.args.get("lines", "100"))
    lines = min(lines, 500)
    if not all(c.isalnum() or c in "-_." for c in unit):
        return jsonify({"error": "invalid unit name"}), 400
    out = _run_cmd(f"journalctl -u {unit} --no-pager -n {lines} 2>&1", timeout=15)
    return jsonify({"unit": unit, "lines": lines, "logs": out})


@app.route("/health_check")
@requires_auth
def health_check():
    """Проверить все сервисные порты."""
    results = {}
    for port in [5021, 5022, 5023, 5024, 5099]:
        code = _run_cmd(
            f'curl -s -o /dev/null -w "%{{http_code}}" http://localhost:{port}/health 2>/dev/null || echo "000"',
            timeout=5,
        )
        results[str(port)] = code.strip()
    return jsonify({"health": results})


@app.route("/env")
@requires_auth
def env():
    """Показать рабочее окружение."""
    return jsonify({
        "cwd": os.getcwd(),
        "python": _run_cmd("python3 --version 2>&1"),
        "hostname": _run_cmd("hostname"),
        "uptime": _run_cmd("uptime"),
        "disk": _run_cmd("df -h / | tail -1"),
        "memory": _run_cmd("free -h | head -2"),
    })


@app.route("/cmd")
@requires_auth
def cmd():
    """Выполнить ограниченный набор команд."""
    q = request.args.get("q", "")
    if not q:
        return jsonify({"error": "q is required"}), 400

    # Белый список безопасных команд
    ALLOWED_PREFIXES = [
        "ls", "cat", "head", "tail", "wc", "df", "free", "uptime",
        "ps", "ss", "netstat", "systemctl status", "systemctl is-active",
        "journalctl", "pip list", "pip show", "python3 -c",
        "find", "grep", "du", "file", "stat", "whoami", "id",
        "curl http://localhost",
    ]
    allowed = any(q.strip().startswith(p) for p in ALLOWED_PREFIXES)
    if not allowed:
        return jsonify({"error": "command not in whitelist", "allowed": ALLOWED_PREFIXES}), 403

    # Блокируем опасные паттерны
    BLOCKED = ["rm ", "mv ", "cp ", "chmod", "chown", "mkfs", "dd ", "> ", ">>", "|bash", "|sh", "eval", "exec"]
    if any(b in q for b in BLOCKED):
        return jsonify({"error": "blocked pattern detected"}), 403

    out = _run_cmd(q, timeout=15)
    return jsonify({"command": q, "output": out})


if __name__ == "__main__":
    print(f"Debug API starting on port {DEBUG_PORT}")
    print(f"Auth: {AUTH_USER} / {'*' * len(AUTH_PASS)}")
    app.run(host="0.0.0.0", port=DEBUG_PORT, debug=False)
