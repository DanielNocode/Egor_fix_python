# -*- coding: utf-8 -*-
"""
services/send_text.py — POST /send_text

Отправка текста в чат/ЛС с тегированием клиента.
Использует привязанный аккаунт из реестра.

JSON запрос (не меняется):
{
    "chat": "-1001234567890",
    "text": "Текст сообщения",
    "tag_client": true,
    "client_id": 123456,
    "client_username": "@username",
    "exclude_usernames": ["@bot1"],
    "disable_preview": true,
    "reply_to": null,
    "parse_mode": "html"
}
"""
import asyncio
import logging
from typing import Any, Dict, List, Optional

from flask import Blueprint, request, jsonify
from html import escape as _html_escape
from telethon import functions, types, errors as tl_errors
from telethon.utils import get_peer_id

from core.bridge import TelethonBridge
from core.router import AccountRouter
from core.retry import run_with_retry

logger = logging.getLogger("svc.send_text")

bp = Blueprint("send_text", __name__)
_router: Optional[AccountRouter] = None
_loop: Optional[asyncio.AbstractEventLoop] = None


def init(router: AccountRouter, loop: asyncio.AbstractEventLoop):
    global _router, _loop
    _router = router
    _loop = loop


def _run(coro, timeout=120):
    return asyncio.run_coroutine_threadsafe(coro, _loop).result(timeout=timeout)


# === Helpers ==================================================================

def _display_name(u: types.User) -> str:
    name = " ".join(
        x for x in [(u.first_name or "").strip(), (u.last_name or "").strip()] if x
    ) or (u.username or "user")
    return name.strip() or "user"


def _html_mention(user: types.User) -> str:
    return f'<a href="tg://user?id={user.id}">{_html_escape(_display_name(user))}</a>'


async def _load_participants(bridge: TelethonBridge, chat_peer: Any) -> Dict[int, types.User]:
    try:
        res = await bridge.client(functions.channels.GetParticipantsRequest(
            channel=chat_peer,
            filter=types.ChannelParticipantsRecent(),
            offset=0, limit=200, hash=0,
        ))
        return {u.id: u for u in res.users}
    except Exception:
        return {}


async def _find_client_in_chat(
    bridge: TelethonBridge, chat_peer: Any,
    users_cache: Dict[int, types.User],
    prefer_username: Optional[str] = None,
    exclude_user_ids: Optional[set] = None,
) -> Optional[types.User]:
    exclude_user_ids = exclude_user_ids or set()
    my_id = bridge.self_user_id

    if prefer_username:
        try:
            target = await bridge.get_entity(prefer_username)
            if isinstance(target, types.User):
                if not getattr(target, "bot", False) and target.id != my_id and target.id not in exclude_user_ids:
                    if not users_cache or target.id in users_cache:
                        return target
        except Exception:
            pass

    for uid, u in users_cache.items():
        if isinstance(u, types.User):
            if getattr(u, "bot", False):
                continue
            if u.id == my_id:
                continue
            if u.id in exclude_user_ids:
                continue
            return u
    return None


# === Основная логика ==========================================================

async def _send_text_impl(
    bridge: TelethonBridge, chat: Any, text: str,
    tag_client: bool, client_id: Optional[int],
    client_username: Optional[str],
    exclude_usernames: Optional[List[str]],
    disable_preview: bool, reply_to: Optional[int],
    parse_mode: str,
) -> Dict[str, Any]:
    my_id = bridge.self_user_id
    chat_ent = await bridge.get_entity(chat)
    is_private = isinstance(chat_ent, types.User)

    if is_private and not tag_client:
        sent = await bridge.client.send_message(
            entity=chat_ent, message=text or "",
            parse_mode=(parse_mode or "html"),
            link_preview=not disable_preview,
            reply_to=reply_to,
        )
        return {
            "status": "ok",
            "chat_id": get_peer_id(chat_ent),
            "message_id": getattr(sent, "id", None),
            "chat_type": "private",
        }

    users_cache: Dict[int, types.User] = {}
    if not is_private:
        users_cache = await _load_participants(bridge, chat_ent)

    exclude_ids: set = set()
    for uname in exclude_usernames or []:
        try:
            ent = await bridge.get_entity(uname)
            if isinstance(ent, types.User):
                exclude_ids.add(ent.id)
        except Exception:
            pass

    client_user: Optional[types.User] = None

    if is_private and tag_client:
        if isinstance(chat_ent, types.User) and not getattr(chat_ent, "bot", False) and chat_ent.id != my_id:
            client_user = chat_ent
    else:
        if client_id:
            cid = int(client_id)
            if cid in users_cache:
                u = users_cache[cid]
                if not getattr(u, "bot", False) and u.id != my_id:
                    client_user = u
            else:
                try:
                    ent = await bridge.get_entity(cid)
                    if isinstance(ent, types.User) and not getattr(ent, "bot", False) and ent.id != my_id:
                        client_user = ent
                except Exception:
                    pass

        if client_user is None and client_username:
            try:
                ent = await bridge.get_entity(client_username)
                if isinstance(ent, types.User) and not getattr(ent, "bot", False) and ent.id != my_id:
                    client_user = ent
            except Exception:
                pass

        if client_user is None and tag_client:
            client_user = await _find_client_in_chat(
                bridge, chat_ent, users_cache,
                prefer_username=client_username,
                exclude_user_ids=exclude_ids,
            )

    msg_text = text or ""
    if tag_client and client_user:
        mention = _html_mention(client_user)
        if "{client}" in msg_text or "{{client}}" in msg_text:
            msg_text = msg_text.replace("{client}", mention).replace("{{client}}", mention)
        else:
            msg_text = f"{mention} {msg_text}".strip()

    sent = await bridge.client.send_message(
        entity=chat_ent, message=msg_text,
        parse_mode=(parse_mode or "html"),
        link_preview=not disable_preview,
        reply_to=reply_to,
    )
    return {
        "status": "ok",
        "chat_id": get_peer_id(chat_ent),
        "message_id": getattr(sent, "id", None),
        "client_tagged_id": getattr(client_user, "id", None) if client_user else None,
        "client_tagged_name": _display_name(client_user) if client_user else None,
        "chat_type": "private" if is_private else "group",
    }


# === HTTP endpoint ============================================================

@bp.route("/send_text", methods=["POST"])
def send_text():
    if _router is None:
        return jsonify({"error": "telethon client not ready"}), 503

    data = request.get_json(force=True, silent=True) or {}
    chat = data.get("chat")
    text = data.get("text") or ""
    tag_client = bool(data.get("tag_client", False))
    client_id = data.get("client_id")
    client_username = data.get("client_username")
    exclude_usernames = data.get("exclude_usernames") or []
    disable_preview = bool(data.get("disable_preview", True))
    reply_to = data.get("reply_to")
    parse_mode = (data.get("parse_mode") or "html").lower()

    if chat is None:
        return jsonify({"error": "chat is required"}), 400

    # Проверяем, не вышли ли мы уже из этого чата
    if _router.registry.is_left(str(chat)):
        logger.info("send_text skipped: chat %s already left", chat)
        return jsonify({"status": "skipped", "reason": "chat already left"})

    # Нормализуем chat в int если можно
    chat_ref = chat
    if isinstance(chat_ref, str) and chat_ref.strip().lstrip("-").isdigit():
        try:
            chat_ref = int(chat_ref)
        except Exception:
            pass

    try:
        bridge = _router.pick_for_chat(chat_ref, service="send_text")
    except RuntimeError as e:
        return jsonify({"error": str(e)}), 503

    try:
        result = _run(
            run_with_retry(
                _send_text_impl, bridge.client,
                bridge, chat_ref, text, tag_client,
                int(client_id) if client_id is not None else None,
                client_username if isinstance(client_username, str) else None,
                exclude_usernames if isinstance(exclude_usernames, list) else [],
                disable_preview,
                int(reply_to) if reply_to is not None else None,
                parse_mode,
            ),
            timeout=120,
        )
        _router.handle_success(bridge, str(chat_ref), "send_text")
        return jsonify(result)

    except tl_errors.FloodWaitError as e:
        _router.handle_error(bridge, e, str(chat_ref), "send_text")
        # Failover
        fallback = _router.pool.get_next_healthy("send_text", exclude_key=bridge.name)
        if fallback:
            try:
                result = _run(
                    run_with_retry(
                        _send_text_impl, fallback.client,
                        fallback, chat_ref, text, tag_client,
                        int(client_id) if client_id is not None else None,
                        client_username if isinstance(client_username, str) else None,
                        exclude_usernames if isinstance(exclude_usernames, list) else [],
                        disable_preview,
                        int(reply_to) if reply_to is not None else None,
                        parse_mode,
                    ),
                    timeout=120,
                )
                _router.handle_success(fallback, str(chat_ref), "send_text")
                return jsonify(result)
            except Exception:
                pass
        return jsonify({"status": "error", "error": "FloodWait", "retry_after": e.seconds}), 429

    except ValueError as e:
        # Entity resolution failed — пробуем другой аккаунт
        if "Cannot resolve" in str(e):
            logger.warning("send_text: entity %s not found on %s, trying failover", chat_ref, bridge.name)
            fallback = _router.pool.get_next_healthy("send_text", exclude_key=bridge.name)
            if fallback:
                try:
                    result = _run(
                        run_with_retry(
                            _send_text_impl, fallback.client,
                            fallback, chat_ref, text, tag_client,
                            int(client_id) if client_id is not None else None,
                            client_username if isinstance(client_username, str) else None,
                            exclude_usernames if isinstance(exclude_usernames, list) else [],
                            disable_preview,
                            int(reply_to) if reply_to is not None else None,
                            parse_mode,
                        ),
                        timeout=120,
                    )
                    _router.handle_success(fallback, str(chat_ref), "send_text")
                    return jsonify(result)
                except Exception:
                    pass
        _router.handle_error(bridge, e, str(chat_ref), "send_text")
        logger.error("send_text failed: %s: %s", type(e).__name__, e)
        return jsonify({"status": "error", "error": str(e)}), 500

    except Exception as e:
        import traceback
        _router.handle_error(bridge, e, str(chat_ref), "send_text")
        logger.error("send_text failed: %s: %s", type(e).__name__, e)
        return jsonify({
            "status": "error",
            "error": str(e),
            "traceback": traceback.format_exc(),
        }), 500


# === Extra endpoints (совместимость) ==========================================

@bp.route("/health", methods=["GET"])
def health():
    ok = _router is not None and _router.pool.get_best("send_text") is not None
    return jsonify({"status": "ok" if ok else "not_ready"})


@bp.route("/stats", methods=["GET"])
def stats():
    if _router is None:
        return jsonify({})
    pool = _router.pool
    bridges = pool.get_healthy_list("send_text")
    total_cache = sum(len(b._dialogs) for b in bridges)
    return jsonify({
        "cache_size": total_cache,
        "accounts": pool.service_statuses("send_text"),
        "error_count": pool.total_errors,
        "operations_count": pool.total_operations,
    })


@bp.route("/reload_cache", methods=["POST"])
def reload_cache():
    if _router is None:
        return jsonify({"status": "error", "error": "not ready"}), 503
    try:
        _run(_router.pool.reload_service_caches("send_text"), timeout=120)
        bridges = _router.pool.get_healthy_list("send_text")
        total_cache = sum(len(b._dialogs) for b in bridges)
        return jsonify({"status": "ok", "cache_size": total_cache})
    except Exception as e:
        return jsonify({"status": "error", "error": str(e)}), 500
