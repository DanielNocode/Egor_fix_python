# -*- coding: utf-8 -*-
"""
dashboard/routes.py — Flask-дашборд для Егора.

Показывает:
  - Статус каждого сервиса (Создание чатов, Отправка текста, и т.д.)
  - Статус каждого аккаунта
  - Распределение нагрузки по аккаунтам
  - Список чатов, лог операций, лог фейловеров
  - Системные логи (journalctl)
  - Управление: перезагрузка кэша, сброс ошибок, перезапуск платформы
"""
import asyncio
import json
import os
import subprocess
import time
import logging
from functools import wraps
from typing import Optional

import requests as http_requests
from flask import Flask, render_template, jsonify, request, Response

import config
from core.pool import AccountPool
from core.registry import ChatRegistry
from core.router import AccountRouter

logger = logging.getLogger("dashboard")

_pool: Optional[AccountPool] = None
_registry: Optional[ChatRegistry] = None
_router: Optional[AccountRouter] = None
_loop: Optional[asyncio.AbstractEventLoop] = None


def _run(coro, timeout=60):
    return asyncio.run_coroutine_threadsafe(coro, _loop).result(timeout=timeout)


# === Auth =====================================================================

def _check_auth(username, password):
    return username == config.DASHBOARD_USER and password == config.DASHBOARD_PASS


def _authenticate():
    return Response(
        "Authentication required", 401,
        {"WWW-Authenticate": 'Basic realm="Telethon Platform"'},
    )


def requires_auth(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        auth = request.authorization
        if not auth or not _check_auth(auth.username, auth.password):
            return _authenticate()
        return f(*args, **kwargs)
    return decorated


# === App factory ==============================================================

def create_dashboard_app(pool, registry, router, loop) -> Flask:
    global _pool, _registry, _router, _loop
    _pool = pool
    _registry = registry
    _router = router
    _loop = loop

    _dir = os.path.dirname(os.path.abspath(__file__))
    app = Flask(
        "dashboard",
        template_folder=os.path.join(_dir, "templates"),
        static_folder=os.path.join(_dir, "static"),
        static_url_path="/static",
    )

    # --- Pages ---

    @app.route("/")
    @requires_auth
    def index():
        return render_template("dashboard.html")

    # --- API: accounts ---

    @app.route("/api/accounts")
    @requires_auth
    def api_accounts():
        statuses = _pool.all_statuses()
        # Подтягиваем last_active из БД если в памяти 0 (после рестарта)
        last_times = _registry.get_last_active_times()
        for acc in statuses:
            if not acc.get("last_active") and acc["account_name"] in last_times:
                acc["last_active"] = last_times[acc["account_name"]]
        return jsonify({"accounts": statuses})

    # --- API: services (сводка по каждому типу сервиса) ---

    @app.route("/api/services")
    @requires_auth
    def api_services():
        services = {}
        for svc in config.SERVICE_TYPES:
            bridges = _pool.service_statuses(svc)
            healthy = sum(1 for b in bridges if b.get("is_healthy"))
            total = len(bridges)
            services[svc] = {
                "healthy": healthy,
                "total": total,
                "status": "ok" if healthy > 0 else "down",
            }
        return jsonify({"services": services})

    # --- API: status (общая сводка) ---

    @app.route("/api/status")
    @requires_auth
    def api_status():
        db_stats = _registry.get_stats()
        healthy = sum(1 for b in _pool.bridges.values() if b.is_healthy)
        total = len(_pool.bridges)
        return jsonify({
            "healthy_bridges": healthy,
            "total_bridges": total,
            "active_chats": db_stats["active_chats"],
            "total_operations": db_stats["total_operations"],
            "total_errors": db_stats["total_errors"],
            "total_failovers": db_stats["total_failovers"],
            "pending_retries": _registry.get_failed_requests_count(),
        })

    # --- API: load distribution ---

    @app.route("/api/load")
    @requires_auth
    def api_load():
        counts = _registry.get_account_chat_counts()
        all_accounts = set()
        for b in _pool.bridges.values():
            all_accounts.add(b.account_name)
        result = {}
        for acc in sorted(all_accounts):
            result[acc] = counts.get(acc, 0)
        return jsonify({"load": result})

    # --- API: chats ---

    @app.route("/api/chats")
    @requires_auth
    def api_chats():
        limit = int(request.args.get("limit", 200))
        chats = _registry.get_all_assignments(limit=limit)
        return jsonify({"chats": chats})

    # --- API: operations log ---

    @app.route("/api/operations")
    @requires_auth
    def api_operations():
        limit = int(request.args.get("limit", 100))
        ops = _registry.get_recent_operations(limit=limit)
        # Тянем titles только для chat_id из текущей порции операций
        chat_ids = list({op.get("chat_id", "") for op in ops if op.get("chat_id")})
        titles = _registry.get_chat_titles(chat_ids) if chat_ids else {}
        for op in ops:
            op["chat_title"] = titles.get(op.get("chat_id", ""), "")
        return jsonify({"operations": ops})

    # --- API: failover log ---

    @app.route("/api/failovers")
    @requires_auth
    def api_failovers():
        limit = int(request.args.get("limit", 50))
        fos = _registry.get_failover_log(limit=limit)
        return jsonify({"failovers": fos})

    # --- API: system logs ---

    @app.route("/api/logs")
    @requires_auth
    def api_logs():
        n = min(int(request.args.get("n", 80)), 500)
        try:
            result = subprocess.run(
                ["journalctl", "-u", "telethon-platform",
                 "--no-pager", "-n", str(n), "--output", "short-iso"],
                capture_output=True, text=True, timeout=5,
            )
            lines = result.stdout.strip().split("\n") if result.stdout.strip() else []
            return jsonify({"logs": lines})
        except Exception as e:
            return jsonify({"logs": [], "error": str(e)})

    # --- API: control ---

    @app.route("/api/control", methods=["POST"])
    @requires_auth
    def api_control():
        data = request.get_json(force=True) or {}
        action = data.get("action")
        account = data.get("account")

        if action == "reload_cache":
            if account:
                bridge = _pool.get(account)
                if not bridge:
                    return jsonify({"error": f"unknown bridge: {account}"}), 400
                try:
                    _run(bridge.warmup_cache(), timeout=120)
                    return jsonify({"status": "ok", "cache_size": len(bridge._dialogs)})
                except Exception as e:
                    return jsonify({"error": str(e)}), 500
            else:
                try:
                    _run(_pool.reload_all_caches(), timeout=120)
                    return jsonify({"status": "ok"})
                except Exception as e:
                    return jsonify({"error": str(e)}), 500

        elif action == "reset_errors":
            if account:
                bridge = _pool.get(account)
                if bridge:
                    bridge.error_count = 0
                    bridge.last_error = None
                    if bridge.status == bridge.STATUS_ERROR:
                        bridge.status = bridge.STATUS_HEALTHY
                    return jsonify({"status": "ok"})
            return jsonify({"error": "unknown bridge"}), 400

        elif action == "clear_flood":
            if account:
                bridge = _pool.get(account)
                if bridge and bridge.status == bridge.STATUS_FLOOD:
                    bridge.status = bridge.STATUS_HEALTHY
                    bridge.flood_until = 0
                    return jsonify({"status": "ok"})
            return jsonify({"error": "unknown bridge or not in flood"}), 400

        elif action == "restart":
            try:
                subprocess.Popen(
                    ["systemctl", "restart", "telethon-platform"],
                    stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                )
                return jsonify({"status": "ok"})
            except Exception as e:
                return jsonify({"error": str(e)}), 500

        return jsonify({"error": "unknown action"}), 400

    # --- API: failed requests ---

    @app.route("/api/failed_requests")
    @requires_auth
    def api_failed_requests():
        limit = int(request.args.get("limit", 200))
        items = _registry.get_failed_requests(limit=limit)
        return jsonify({"failed_requests": items})

    @app.route("/api/retry_request", methods=["POST"])
    @requires_auth
    def api_retry_request():
        data = request.get_json(force=True) or {}
        req_id = data.get("id")
        if not req_id:
            return jsonify({"error": "id is required"}), 400

        item = _registry.get_failed_request_by_id(int(req_id))
        if not item:
            return jsonify({"error": "request not found"}), 404

        # Если передан отредактированный payload — используем его и сохраняем
        edited_payload = data.get("payload")
        if edited_payload is not None:
            try:
                # Валидируем JSON
                if isinstance(edited_payload, str):
                    payload = json.loads(edited_payload)
                else:
                    payload = edited_payload
                # Сохраняем в БД
                _registry.update_failed_request_payload(
                    int(req_id), json.dumps(payload, ensure_ascii=False),
                )
            except (json.JSONDecodeError, TypeError) as e:
                return jsonify({"error": f"invalid JSON: {e}"}), 400
        else:
            try:
                payload = json.loads(item["request_payload"])
            except Exception:
                return jsonify({"error": "invalid payload"}), 400

        service = item["service"]
        direction = item["direction"]

        # Исходящий запрос (salebot) — просто переотправляем
        if direction == "outbound":
            try:
                resp = http_requests.post(
                    item["endpoint"], json=payload, timeout=15,
                )
                if resp.status_code < 400:
                    _registry.update_failed_request(int(req_id), "retried")
                    return jsonify({"status": "ok", "response_code": resp.status_code})
                else:
                    _registry.update_failed_request(
                        int(req_id), "pending",
                        last_retry_error=f"HTTP {resp.status_code}: {resp.text[:200]}",
                    )
                    return jsonify({"status": "error", "error": f"HTTP {resp.status_code}"}), 502
            except Exception as e:
                _registry.update_failed_request(
                    int(req_id), "pending", last_retry_error=str(e),
                )
                return jsonify({"status": "error", "error": str(e)}), 500

        # Входящий запрос — перенаправляем на внутренний сервис
        port_map = {
            "create_chat": config.PORTS["create_chat"],
            "send_text": config.PORTS["send_text"],
            "send_media": config.PORTS["send_media"],
            "leave_chat": config.PORTS["leave_chat"],
        }
        port = port_map.get(service)
        if not port:
            return jsonify({"error": f"unknown service: {service}"}), 400

        endpoint = item["endpoint"] or f"/{service}"
        url = f"http://localhost:{port}{endpoint}"

        try:
            resp = http_requests.post(url, json=payload, timeout=120)
            resp_data = resp.json() if resp.headers.get("content-type", "").startswith("application/json") else {}

            if resp.status_code < 400 and resp_data.get("status") != "error":
                _registry.update_failed_request(int(req_id), "retried")
                return jsonify({"status": "ok", "service_response": resp_data})
            else:
                error_msg = resp_data.get("error", f"HTTP {resp.status_code}")
                _registry.update_failed_request(
                    int(req_id), "pending", last_retry_error=error_msg,
                )
                return jsonify({"status": "error", "error": error_msg}), resp.status_code
        except Exception as e:
            _registry.update_failed_request(
                int(req_id), "pending", last_retry_error=str(e),
            )
            return jsonify({"status": "error", "error": str(e)}), 500

    @app.route("/api/update_failed_payload", methods=["POST"])
    @requires_auth
    def api_update_failed_payload():
        data = request.get_json(force=True) or {}
        req_id = data.get("id")
        new_payload = data.get("payload")
        if not req_id or new_payload is None:
            return jsonify({"error": "id and payload are required"}), 400

        item = _registry.get_failed_request_by_id(int(req_id))
        if not item:
            return jsonify({"error": "request not found"}), 404

        try:
            # Валидируем JSON
            if isinstance(new_payload, str):
                parsed = json.loads(new_payload)
            else:
                parsed = new_payload
            _registry.update_failed_request_payload(
                int(req_id), json.dumps(parsed, ensure_ascii=False),
            )
            return jsonify({"status": "ok"})
        except (json.JSONDecodeError, TypeError) as e:
            return jsonify({"error": f"invalid JSON: {e}"}), 400

    @app.route("/api/delete_failed", methods=["POST"])
    @requires_auth
    def api_delete_failed():
        data = request.get_json(force=True) or {}
        req_id = data.get("id")
        if not req_id:
            return jsonify({"error": "id is required"}), 400
        _registry.delete_failed_request(int(req_id))
        return jsonify({"status": "ok"})

    # --- API: health ---

    @app.route("/health")
    def api_health():
        ok = _pool is not None and any(b.is_healthy for b in _pool.bridges.values())
        return jsonify({"status": "ok" if ok else "not_ready"})

    return app
