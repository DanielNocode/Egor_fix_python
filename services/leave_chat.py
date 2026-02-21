# -*- coding: utf-8 -*-
"""
services/leave_chat.py — POST /leave_chat

Выход из чата. Помечает чат как 'left' в реестре.

JSON запрос (не меняется):
{
    "chat": "-1001234567890"
}
"""
import asyncio
import logging
from typing import Any, Optional

from flask import Blueprint, request, jsonify
from telethon import functions, types

from core.bridge import TelethonBridge
from core.router import AccountRouter
from core.retry import run_with_retry

logger = logging.getLogger("svc.leave_chat")

bp = Blueprint("leave_chat", __name__)
_router: Optional[AccountRouter] = None
_loop: Optional[asyncio.AbstractEventLoop] = None


def init(router: AccountRouter, loop: asyncio.AbstractEventLoop):
    global _router, _loop
    _router = router
    _loop = loop


def _run(coro, timeout=180):
    return asyncio.run_coroutine_threadsafe(coro, _loop).result(timeout=timeout)


def _normalize_chat_ref(raw: Any) -> Any:
    """Нормализация ID чата (из оригинала leave_chat)."""
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
                return int("-100" + s)
        return s
    if isinstance(raw, int):
        if raw > 0:
            return int("-100" + str(raw))
        return raw
    return raw


async def _kick_all_members(bridge: TelethonBridge, channel_peer: Any) -> list:
    """Кикнуть всех участников (кроме себя) перед выходом из чата."""
    kicked = []
    my_id = bridge.self_user_id
    try:
        result = await bridge.client(functions.channels.GetParticipantsRequest(
            channel=channel_peer,
            filter=types.ChannelParticipantsRecent(),
            offset=0, limit=200, hash=0,
        ))
        for user in result.users:
            if user.id == my_id:
                continue
            try:
                await bridge.client(functions.channels.EditBannedRequest(
                    channel=channel_peer,
                    participant=types.InputPeerUser(user.id, user.access_hash or 0),
                    banned_rights=types.ChatBannedRights(
                        until_date=0,
                        view_messages=True,
                    ),
                ))
                kicked.append(user.id)
                logger.info("Kicked user %s (%s) from chat", user.id, user.username or "no_username")
                await asyncio.sleep(0.5)  # пауза между кикам чтобы не словить FloodWait
            except Exception as e:
                logger.warning("Failed to kick user %s: %s", user.id, e)
    except Exception as e:
        logger.warning("Failed to get participants for kick: %s", e)
    return kicked


async def _leave_chat_impl(bridge: TelethonBridge, chat_ref: Any) -> dict:
    entity = await bridge.get_entity(chat_ref)

    if isinstance(entity, types.Channel):
        kicked = await _kick_all_members(bridge, entity)
        await bridge.client(functions.channels.LeaveChannelRequest(entity))
        return {"status": "ok", "left_type": "channel", "id": entity.id, "kicked": kicked}

    if isinstance(entity, types.Chat):
        await bridge.client(
            functions.messages.DeleteChatUserRequest(
                chat_id=entity.id, user_id="me",
            )
        )
        return {"status": "ok", "left_type": "basic_chat", "id": entity.id}

    return {"status": "error", "error": f"unsupported entity type: {type(entity)}"}


# === HTTP endpoint ============================================================

@bp.route("/leave_chat", methods=["POST"])
def leave_chat():
    if _router is None:
        return jsonify({"status": "error", "error": "not initialized"}), 503

    data = request.get_json(force=True, silent=True) or {}
    chat = data.get("chat")
    if chat is None:
        return jsonify({"status": "error", "error": "chat is required"}), 400

    chat_ref = _normalize_chat_ref(chat)

    try:
        bridge = _router.pick_for_chat(chat_ref, service="leave_chat")
    except RuntimeError as e:
        return jsonify({"status": "error", "error": str(e)}), 503

    try:
        result = _run(
            run_with_retry(_leave_chat_impl, bridge.client, bridge, chat_ref),
            timeout=60,
        )
        code = 200 if result.get("status") == "ok" else 400
        if result.get("status") == "ok":
            _router.registry.mark_left(str(chat_ref))
            _router.handle_success(bridge, str(chat_ref), "leave_chat")
        return jsonify(result), code

    except Exception as e:
        # Если чат не найден — фактически мы уже вышли, помечаем как left
        if isinstance(e, ValueError) and "Cannot resolve" in str(e):
            _router.registry.mark_left(str(chat_ref))
            logger.info("leave_chat: chat %s not found, marking as left", chat_ref)
            return jsonify({
                "status": "ok",
                "left_type": "unresolvable",
                "note": "Chat not found, marked as left",
            })
        _router.handle_error(bridge, e, str(chat_ref), "leave_chat")
        return jsonify({"status": "error", "error": str(e)}), 500


@bp.route("/health", methods=["GET"])
def health():
    ok = _router is not None and _router.pool.get_best("leave_chat") is not None
    return jsonify({"status": "ok" if ok else "not_ready"})
