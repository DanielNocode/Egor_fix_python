# -*- coding: utf-8 -*-
"""
dashboard/routes.py — Flask-дашборд для Егора.

Показывает:
  - Статус каждого аккаунта (зелёный/жёлтый/красный)
  - Список чатов с привязкой к аккаунтам
  - Лог операций
  - Лог фейловеров
  - Управление: reload cache, сброс ошибок
"""
import asyncio
import time
import logging
from functools import wraps
from typing import Optional

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

    app = Flask(
        "dashboard",
        template_folder="dashboard/templates",
        static_folder="dashboard/static",
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
        return jsonify({"accounts": _pool.all_statuses()})

    # --- API: status (общая сводка) ---

    @app.route("/api/status")
    @requires_auth
    def api_status():
        db_stats = _registry.get_stats()
        healthy = len(_pool.get_healthy_list())
        total = len(_pool.bridges)
        return jsonify({
            "healthy_accounts": healthy,
            "total_accounts": total,
            "active_chats": db_stats["active_chats"],
            "total_operations": db_stats["total_operations"],
            "total_errors": db_stats["total_errors"],
            "total_failovers": db_stats["total_failovers"],
        })

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
        return jsonify({"operations": ops})

    # --- API: failover log ---

    @app.route("/api/failovers")
    @requires_auth
    def api_failovers():
        limit = int(request.args.get("limit", 50))
        fos = _registry.get_failover_log(limit=limit)
        return jsonify({"failovers": fos})

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
                    return jsonify({"error": f"unknown account: {account}"}), 400
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
            return jsonify({"error": "unknown account"}), 400

        elif action == "clear_flood":
            if account:
                bridge = _pool.get(account)
                if bridge and bridge.status == bridge.STATUS_FLOOD:
                    bridge.status = bridge.STATUS_HEALTHY
                    bridge.flood_until = 0
                    return jsonify({"status": "ok"})
            return jsonify({"error": "unknown account or not in flood"}), 400

        return jsonify({"error": "unknown action"}), 400

    # --- API: health ---

    @app.route("/health")
    def api_health():
        ok = _pool is not None and _pool.get_best() is not None
        return jsonify({"status": "ok" if ok else "not_ready"})

    return app
