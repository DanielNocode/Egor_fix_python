root@wfoxxidthq:~# cat /root/leave_chat_rumyantsev_webhook.py
# leave_chat_webhook.py
# -*- coding: utf-8 -*-

import asyncio
import threading
from typing import Any, Optional

from flask import Flask, request, jsonify
from telethon import TelegramClient, functions, types

# ==== КОНФИГ (подставь свои значения при необходимости) ==================
API_ID = 36091011
API_HASH = "72fa475b3b4f5124b9f165672dca423b"
SESSION_PATH = "rumyantsev_leave"  # путь к user-сессии, от имени которой выходим из чатов

# ==== ГЛОБАЛЬНО ===========================================================
app = Flask(__name__)
_loop = asyncio.new_event_loop()
_client: Optional[TelegramClient] = None


# ==== УТИЛИТЫ =============================================================
def run_coro(coro, timeout: int = 60):
    """Запускает coroutine в фоновом event loop и ждёт результат."""
    return asyncio.run_coroutine_threadsafe(coro, _loop).result(timeout=timeout)


def _normalize_chat_ref(raw: Any) -> Any:
    """
    Принимает:
      - '-1001234567890' (str) → int(-1001234567890)
      - '1234567890' (str) → int(-1001234567890)  # если передали без -100
      - @username (str) → '@username'
      - -1001234567890 (int) → как есть
      - 1234567890 (int) → int(-1001234567890)
    """
    if isinstance(raw, str):
        s = raw.strip()
        if not s:
            return raw
        if s.startswith("@"):
            return s
        if s.lstrip("-").isdigit():
            if s.startswith("-"):
                return int(s)
            else:
                # положительный id → считаем, что это channel/supergroup id без -100
                return int("-100" + s)
        return s
    if isinstance(raw, int):
        if raw > 0:
            return int("-100" + str(raw))
        return raw
    return raw


# ==== ЛОГИКА ВЫХОДА =======================================================
async def _leave_chat_impl(chat_ref_in: Any) -> dict:
    chat_ref = _normalize_chat_ref(chat_ref_in)
    entity = await _client.get_entity(chat_ref)

    # Супергруппа/канал
    if isinstance(entity, types.Channel):
        await _client(functions.channels.LeaveChannelRequest(entity))
        return {"status": "ok", "left_type": "channel", "id": entity.id}

    # Обычная (basic) группа
    if isinstance(entity, types.Chat):
        await _client(functions.messages.DeleteChatUserRequest(chat_id=entity.id, user_id="me"))
        return {"status": "ok", "left_type": "basic_chat", "id": entity.id}

    return {"status": "error", "error": f"unsupported entity type: {type(entity)}"}


# ==== HTTP API ============================================================
@app.route("/health", methods=["GET"])
def health():
    return jsonify({"status": "ok" if _client is not None else "not_ready"}), 200


@app.route("/leave_chat", methods=["POST"])
def leave_chat_route():
    """
    POST /leave_chat
    JSON:
    {
      "chat": "-1001234567890"   // или "1234567890" (без -100), или "@username"
    }
    """
    if _client is None:
        return jsonify({"status": "error", "error": "telethon client not ready"}), 503

    data = request.get_json(force=True, silent=True) or {}
    chat = data.get("chat")
    if chat is None:
        return jsonify({"status": "error", "error": "chat is required"}), 400

    try:
        result = run_coro(_leave_chat_impl(chat), timeout=60)
        code = 200 if result.get("status") == "ok" else 400
        return jsonify(result), code
    except Exception as e:
        return jsonify({"status": "error", "error": str(e)}), 500


# ==== ЗАПУСК TELETHON В ОТДЕЛЬНОМ ПОТОКЕ ==================================
def telethon_thread():
    global _client
    asyncio.set_event_loop(_loop)
    _client = TelegramClient(SESSION_PATH, API_ID, API_HASH)
    started = _client.start()
    if asyncio.iscoroutine(started):
        _loop.run_until_complete(started)
    _loop.run_forever()


threading.Thread(target=telethon_thread, name="telethon-loop", daemon=True).start()


# ==== ЛОКАЛЬНЫЙ ЗАПУСК (порт 5024) ========================================
if __name__ == "__main__":
    from werkzeug.serving import run_simple
    run_simple("0.0.0.0", 5024, app)