# -*- coding: utf-8 -*-
"""
app.py — Точка входа: один процесс, 4 порта, общий пул аккаунтов.

Запуск:
    python app.py              — запустить все 4 сервиса + дашборд
    python app.py create_chat  — только create_chat (порт 5021)
    python app.py send_text    — только send_text (порт 5022)
    python app.py send_media   — только send_media (порт 5023)
    python app.py leave_chat   — только leave_chat (порт 5024)
    python app.py dashboard    — только дашборд (порт 5099)
"""
import sys
import asyncio
import threading
import logging
import time

from flask import Flask
from werkzeug.serving import make_server

import config
from core.pool import AccountPool
from core.registry import ChatRegistry
from core.router import AccountRouter

from services import create_chat as svc_create_chat
from services import send_text as svc_send_text
from services import send_media as svc_send_media
from services import leave_chat as svc_leave_chat

# === Logging ==================================================================
logging.basicConfig(
    level=getattr(logging, config.LOG_LEVEL, logging.INFO),
    format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger("app")

# === Globals ==================================================================
_loop = asyncio.new_event_loop()
_pool: AccountPool = None
_registry: ChatRegistry = None
_router: AccountRouter = None


# === Telethon thread ==========================================================

def telethon_thread():
    global _pool, _registry, _router

    asyncio.set_event_loop(_loop)

    # 1. Registry (SQLite)
    _registry = ChatRegistry()

    # 2. Account pool
    _pool = AccountPool(_loop)
    _loop.run_until_complete(_pool.start_all())

    # 3. Router
    _router = AccountRouter(_pool, _registry)

    # 4. Init services (inject dependencies)
    svc_create_chat.init(_router, _loop)
    svc_send_text.init(_router, _loop)
    svc_send_media.init(_router, _loop)
    svc_leave_chat.init(_router, _loop)

    logger.info("All bridges started, router ready")

    # 5. Periodic cleanup (old logs)
    async def _periodic_cleanup():
        while True:
            await asyncio.sleep(86400)  # раз в сутки
            try:
                _registry.cleanup_old_logs(days=30)
                logger.info("Old logs cleaned up")
            except Exception as e:
                logger.error("Cleanup failed: %s", e)

    _loop.create_task(_periodic_cleanup())
    _loop.run_forever()


# === Flask apps ===============================================================

def make_create_chat_app() -> Flask:
    app = Flask("create_chat")
    app.register_blueprint(svc_create_chat.bp)
    return app


def make_send_text_app() -> Flask:
    app = Flask("send_text")
    app.register_blueprint(svc_send_text.bp)
    return app


def make_send_media_app() -> Flask:
    app = Flask("send_media")
    app.register_blueprint(svc_send_media.bp)
    return app


def make_leave_chat_app() -> Flask:
    app = Flask("leave_chat")
    app.register_blueprint(svc_leave_chat.bp)
    return app


def make_dashboard_app() -> Flask:
    """Дашборд — отдельный blueprint, подключается если есть."""
    try:
        from dashboard.routes import create_dashboard_app
        return create_dashboard_app(_pool, _registry, _router, _loop)
    except ImportError:
        logger.warning("Dashboard module not found, skipping")
        return None


# === Server threads ===========================================================

def run_flask(app: Flask, port: int, name: str):
    """Запустить Flask на указанном порту в отдельном потоке."""
    server = make_server("0.0.0.0", port, app, threaded=True)
    logger.info("Starting %s on port %d", name, port)
    server.serve_forever()


def start_server_thread(app: Flask, port: int, name: str):
    t = threading.Thread(
        target=run_flask, args=(app, port, name),
        name=f"flask-{name}", daemon=True,
    )
    t.start()
    return t


# === Main =====================================================================

def main():
    # Запускаем Telethon в фоновом потоке
    tg_thread = threading.Thread(
        target=telethon_thread, name="telethon-loop", daemon=True,
    )
    tg_thread.start()

    # Ждём пока pool стартанёт (16 bridges с flood wait ~30s each, but parallel)
    logger.info("Waiting for Telethon bridges to start...")
    for _ in range(300):  # max 300 секунд (5 мин)
        if _router is not None:
            break
        time.sleep(1)

    if _router is None:
        logger.error("Telethon bridges failed to start within 300s, exiting")
        sys.exit(1)

    logger.info("Router ready, starting HTTP servers...")

    # Определяем какие сервисы запускать
    args = set(sys.argv[1:])

    services = {
        "create_chat": (make_create_chat_app, config.PORTS["create_chat"]),
        "send_text":   (make_send_text_app,   config.PORTS["send_text"]),
        "send_media":  (make_send_media_app,  config.PORTS["send_media"]),
        "leave_chat":  (make_leave_chat_app,  config.PORTS["leave_chat"]),
    }

    threads = []

    if not args or args == {"all"}:
        # Запускаем всё
        for name, (factory, port) in services.items():
            app = factory()
            threads.append(start_server_thread(app, port, name))

        # Dashboard
        dash_app = make_dashboard_app()
        if dash_app:
            threads.append(
                start_server_thread(dash_app, config.PORTS["dashboard"], "dashboard")
            )
    else:
        for name in args:
            if name in services:
                factory, port = services[name]
                app = factory()
                threads.append(start_server_thread(app, port, name))
            elif name == "dashboard":
                dash_app = make_dashboard_app()
                if dash_app:
                    threads.append(
                        start_server_thread(dash_app, config.PORTS["dashboard"], "dashboard")
                    )
            else:
                logger.warning("Unknown service: %s", name)

    if not threads:
        logger.error("No services started!")
        sys.exit(1)

    logger.info("All services started. Press Ctrl+C to stop.")

    # Держим основной поток живым
    try:
        while True:
            time.sleep(60)
    except KeyboardInterrupt:
        logger.info("Shutting down...")


if __name__ == "__main__":
    main()
