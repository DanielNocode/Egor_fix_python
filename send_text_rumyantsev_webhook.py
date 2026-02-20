# -*- coding: utf-8 -*-
"""
send_text_rumyantsev_webhook.py
Flask + Telethon endpoint для отправки текстовых сообщений.

ПАТЧ 2026-02-13:
 - catch_up=False при старте (не синхронизируем пропущенные обновления)
 - retry с reconnect при PersistentTimestampOutdatedError и сетевых ошибках
 - улучшенное логирование ошибок
"""

import asyncio
import threading
import time
import logging
from typing import Any, Dict, List, Optional

from flask import Flask, request, jsonify
from html import escape as _html_escape
from telethon import TelegramClient, functions, types, errors as tl_errors
from telethon.utils import get_peer_id

# === КОНФИГ =========
API_ID = 36091011
API_HASH = "72fa475b3b4f5124b9f165672dca423b"
SESSION_PATH = "rumyantsev_send_text"

# === RETRY CONFIG ===
MAX_RETRIES = 3
RETRY_DELAY = 2

RETRIABLE_ERRORS = (
    ConnectionError,
    OSError,
    TimeoutError,
    asyncio.TimeoutError,
)

# === ГЛОБАЛЬНО ============================================================
app = Flask(__name__)
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("send_text_rumyantsev")

_loop = asyncio.new_event_loop()
_client: Optional[TelegramClient] = None
_self_user_id: Optional[int] = None

# === ВСПОМОГАТЕЛЬНОЕ =====================================================

def run_coro(coro, timeout: int = 60):
    return asyncio.run_coroutine_threadsafe(coro, _loop).result(timeout=timeout)


async def _reconnect_client(client: TelegramClient):
    logger.warning("Reconnecting Telethon client...")
    try:
        await client.disconnect()
    except Exception:
        pass
    await asyncio.sleep(1)
    try:
        await client.connect()
        if not await client.is_user_authorized():
            logger.error("Client not authorized after reconnect!")
            raise RuntimeError("Client lost authorization")
        logger.info("Reconnect successful")
    except Exception as e:
        logger.error(f"Reconnect failed: {e}")
        raise


def _is_persistent_timestamp_error(e: Exception) -> bool:
    err_name = type(e).__name__
    err_str = str(e).lower()
    return (
        "persistenttimestamp" in err_name.lower()
        or "persistent timestamp" in err_str
    )


async def _run_with_retry(coro_func, *args, **kwargs):
    last_error = None
    for attempt in range(1, MAX_RETRIES + 1):
        try:
            return await coro_func(*args, **kwargs)
        except RETRIABLE_ERRORS as e:
            last_error = e
            logger.warning(f"Attempt {attempt}/{MAX_RETRIES} failed (network): {type(e).__name__}: {e}")
            if attempt < MAX_RETRIES and _client:
                await _reconnect_client(_client)
                await asyncio.sleep(RETRY_DELAY)
        except Exception as e:
            if _is_persistent_timestamp_error(e):
                last_error = e
                logger.warning(f"Attempt {attempt}/{MAX_RETRIES} failed (PersistentTimestamp): {e}")
                if attempt < MAX_RETRIES and _client:
                    await _reconnect_client(_client)
                    await asyncio.sleep(RETRY_DELAY)
            else:
                raise
    raise last_error


async def _get_self_id(client: TelegramClient) -> int:
    global _self_user_id
    if _self_user_id:
        return _self_user_id
    me = await client.get_me()
    _self_user_id = me.id
    return _self_user_id

def _display_name(u: types.User) -> str:
    name = " ".join([x for x in [(u.first_name or "").strip(), (u.last_name or "").strip()] if x]) or (u.username or "user")
    return name.strip() or "user"

def _html_mention(user: types.User) -> str:
    return f'<a href="tg://user?id={user.id}">{_html_escape(_display_name(user))}</a>'

async def _load_chat_participants(client: TelegramClient, chat_peer: Any) -> Dict[int, types.User]:
    users_cache: Dict[int, types.User] = {}
    try:
        res = await client(functions.channels.GetParticipantsRequest(
            channel=chat_peer,
            filter=types.ChannelParticipantsRecent(),
            offset=0,
            limit=200,
            hash=0
        ))
        users_cache = {u.id: u for u in res.users}
    except Exception:
        pass
    return users_cache

async def _find_client_in_chat(client: TelegramClient,
                               chat_peer: Any,
                               users_cache: Dict[int, types.User],
                               prefer_username: Optional[str] = None,
                               exclude_user_ids: Optional[set[int]] = None) -> Optional[types.User]:
    exclude_user_ids = exclude_user_ids or set()
    my_id = await _get_self_id(client)

    if prefer_username:
        try:
            target = await client.get_entity(prefer_username)
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

async def _get_chat_entity(client: TelegramClient, chat: Any) -> Any:
    try:
        return await client.get_entity(chat)
    except ValueError:
        async for dialog in client.iter_dialogs(limit=200):
            if isinstance(chat, int):
                dialog_id = get_peer_id(dialog.entity)
                if dialog.entity.id == chat or dialog_id == chat:
                    return dialog.entity
            elif isinstance(chat, str):
                if hasattr(dialog.entity, 'username') and dialog.entity.username:
                    if dialog.entity.username == chat.lstrip('@'):
                        return dialog.entity
        raise ValueError(f"Не удалось найти чат {chat} в диалогах")

async def _send_text_impl(client: TelegramClient,
                          chat: Any,
                          text: str,
                          tag_client: bool,
                          client_id: Optional[int],
                          client_username: Optional[str],
                          exclude_usernames: Optional[List[str]],
                          disable_preview: bool,
                          reply_to: Optional[int],
                          parse_mode: str) -> Dict[str, Any]:
    my_id = await _get_self_id(client)
    chat_ent = await _get_chat_entity(client, chat)
    is_private_chat = isinstance(chat_ent, types.User)

    if is_private_chat and not tag_client:
        sent = await client.send_message(
            entity=chat_ent,
            message=text or "",
            parse_mode=(parse_mode or "html"),
            link_preview=not disable_preview,
            reply_to=reply_to
        )
        return {
            "status": "ok",
            "chat_id": get_peer_id(chat_ent),
            "message_id": getattr(sent, "id", None),
            "chat_type": "private"
        }

    users_cache: Dict[int, types.User] = {}
    if not is_private_chat:
        users_cache = await _load_chat_participants(client, chat_ent)

    exclude_ids: set[int] = set()
    for uname in exclude_usernames or []:
        try:
            ent = await client.get_entity(uname)
            if isinstance(ent, types.User):
                exclude_ids.add(ent.id)
        except Exception:
            pass

    client_user: Optional[types.User] = None

    if is_private_chat and tag_client:
        if isinstance(chat_ent, types.User) and not getattr(chat_ent, "bot", False) and chat_ent.id != my_id:
            client_user = chat_ent
    else:
        if client_id:
            client_id_int = int(client_id)
            if client_id_int in users_cache:
                u = users_cache[client_id_int]
                if not getattr(u, "bot", False) and u.id != my_id:
                    client_user = u
            else:
                try:
                    ent = await client.get_entity(client_id_int)
                    if isinstance(ent, types.User) and not getattr(ent, "bot", False) and ent.id != my_id:
                        client_user = ent
                except Exception:
                    client_user = None

        if client_user is None and client_username:
            try:
                ent = await client.get_entity(client_username)
                if isinstance(ent, types.User) and not getattr(ent, "bot", False) and ent.id != my_id:
                    client_user = ent
            except Exception:
                client_user = None

        if client_user is None and tag_client:
            client_user = await _find_client_in_chat(
                client, chat_ent, users_cache,
                prefer_username=client_username,
                exclude_user_ids=exclude_ids
            )

    msg_text = text or ""
    if tag_client and client_user:
        mention = _html_mention(client_user)
        if "{client}" in msg_text or "{{client}}" in msg_text:
            msg_text = msg_text.replace("{client}", mention).replace("{{client}}", mention)
        else:
            msg_text = f"{mention} {msg_text}".strip()

    sent = await client.send_message(
        entity=chat_ent,
        message=msg_text,
        parse_mode=(parse_mode or "html"),
        link_preview=not disable_preview,
        reply_to=reply_to
    )
    return {
        "status": "ok",
        "chat_id": get_peer_id(chat_ent),
        "message_id": getattr(sent, "id", None),
        "client_tagged_id": getattr(client_user, "id", None) if client_user else None,
        "client_tagged_name": _display_name(client_user) if client_user else None,
        "chat_type": "private" if is_private_chat else "group"
    }

# === HTTP API =============================================================

@app.route("/health", methods=["GET"])
def health():
    ok = _client is not None
    return jsonify({"status": "ok" if ok else "not_ready"})

@app.route("/send_text", methods=["POST"])
def send_text():
    if _client is None:
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

    chat_ref = chat
    if isinstance(chat_ref, str) and chat_ref.strip().lstrip("-").isdigit():
        try:
            chat_ref = int(chat_ref)
        except Exception:
            pass

    try:
        result = run_coro(_run_with_retry(
            _send_text_impl,
            _client,
            chat=chat_ref,
            text=text,
            tag_client=tag_client,
            client_id=(int(client_id) if client_id is not None else None),
            client_username=(client_username if isinstance(client_username, str) else None),
            exclude_usernames=(exclude_usernames if isinstance(exclude_usernames, list) else []),
            disable_preview=disable_preview,
            reply_to=(int(reply_to) if reply_to is not None else None),
            parse_mode=parse_mode
        ), timeout=120)
        return jsonify(result)
    except tl_errors.FloodWaitError as e:
        return jsonify({"status": "error", "error": "FloodWait", "retry_after": e.seconds}), 429
    except Exception as e:
        import traceback
        logger.error(f"send_text failed: {type(e).__name__}: {e}")
        return jsonify({
            "status": "error",
            "error": str(e),
            "traceback": traceback.format_exc()
        }), 500

# === ЗАПУСК TELETHON В ФОНЕ ==============================================

def telethon_thread():
    global _client
    asyncio.set_event_loop(_loop)
    _client = TelegramClient(SESSION_PATH, API_ID, API_HASH)
    started = _client.start()
    if asyncio.iscoroutine(started):
        _loop.run_until_complete(started)

    logger.info("Telethon client started")
    _loop.run_forever()

threading.Thread(target=telethon_thread, name="telethon-loop", daemon=True).start()

if __name__ == "__main__":
    from werkzeug.serving import run_simple
    run_simple("0.0.0.0", 5022, app)
