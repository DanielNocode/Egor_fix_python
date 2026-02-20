# -*- coding: utf-8 -*-
"""
send_media_webhook.py
Flask + Telethon endpoint для отправки медиа/документов с подписью.

ПАТЧ 2026-02-13:
 - catch_up=False при старте (не синхронизируем пропущенные обновления)
 - retry с reconnect при PersistentTimestampOutdatedError и сетевых ошибках
 - улучшенное логирование ошибок
"""
import asyncio
import threading
import os
import re
import time
import logging
import collections
from typing import Any, Dict, List, Optional, Union, Tuple
from urllib.parse import urlparse

from flask import Flask, request, jsonify
from telethon import TelegramClient, errors
from telethon.tl.types import PeerChannel, PeerChat, PeerUser

# -------------------- CONFIG --------------------
API_ID = 36091011
API_HASH = "72fa475b3b4f5124b9f165672dca423b"
SESSION_PATH = "rumuantsev_media"
BIND_HOST = "0.0.0.0"
BIND_PORT = 5023
CACHE_WARMUP_INTERVAL = 1800  # 30 minutes

# -------------------- RETRY CONFIG --------------------
MAX_RETRIES = 3
RETRY_DELAY = 2

RETRIABLE_ERRORS = (
    ConnectionError,
    OSError,
    TimeoutError,
    asyncio.TimeoutError,
)

# -------------------- GLOBALS -------------------
app = Flask(__name__)
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("send_media_rumyantsev")

_loop: Optional[asyncio.AbstractEventLoop] = None
_client: Optional[TelegramClient] = None
_DIALOGS_BY_ID: Dict[int, Any] = {}

# -------------------- STATS --------------------
_start_time: float = time.time()
_error_count: int = 0
_last_errors: collections.deque = collections.deque(maxlen=10)

# -------------------- RETRY UTILS -------------------

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


# -------------------- УТИЛИТЫ -------------------
def _is_url(s: str) -> bool:
    try:
        u = urlparse(s)
        return u.scheme in ("http", "https")
    except Exception:
        return False

def _looks_like_video(hint: Optional[str]) -> bool:
    if not hint:
        return False
    v = hint.lower()
    return v.startswith("video/") or v.endswith((".mp4", ".mov", ".m4v", ".webm", ".mkv"))

def _guess_file_hint(payload: Union[str, Dict[str, Any]]) -> Optional[str]:
    if isinstance(payload, str):
        return payload
    if isinstance(payload, dict):
        return payload.get("filename") or payload.get("file") or payload.get("url") or payload.get("path")
    return None

def run_coro(coro, timeout: int = 120):
    return asyncio.run_coroutine_threadsafe(coro, _loop).result(timeout=timeout)

def _assert_ready():
    if _client is None:
        raise RuntimeError("Telethon client not initialized yet")

# ---- t.me/<channel>/<id> parsing & fetch ----
_TG_PATTERNS = [
    r'^(?:https?://)?t\.me/([^/]+)/(\d+)$',
    r'^(?:https?://)?telegram\.me/([^/]+)/(\d+)$',
]
def _parse_tg_link_sync(link: str) -> Optional[Tuple[str, int]]:
    link = link.strip()
    for p in _TG_PATTERNS:
        m = re.match(p, link)
        if m:
            return m.group(1), int(m.group(2))
    return None

async def _get_media_from_tg_post(client: TelegramClient, channel: str, msg_id: int):
    ent = await client.get_entity(channel)
    msg = await client.get_messages(ent, ids=msg_id)
    if not msg:
        raise ValueError("Message not found")
    if not msg.media:
        raise ValueError("Message has no media")
    return msg.media

# ---- диалоги: прогрев и резолв по user_id ----
async def _warmup_dialog_cache(client: TelegramClient):
    _DIALOGS_BY_ID.clear()
    async for d in client.iter_dialogs():
        ent = d.entity
        uid = getattr(ent, "id", None)
        if uid is not None:
            if hasattr(ent, 'broadcast') or hasattr(ent, 'megagroup'):
                full_id = -1000000000000 - uid
                _DIALOGS_BY_ID[full_id] = ent
            elif hasattr(ent, 'title') and not hasattr(ent, 'username'):
                _DIALOGS_BY_ID[-uid] = ent
            else:
                _DIALOGS_BY_ID[uid] = ent

async def resolve_entity_by_id(client: TelegramClient, uid: int):
    ent = _DIALOGS_BY_ID.get(int(uid))
    if ent is not None:
        return ent

    try:
        if uid > 0:
            return await client.get_entity(PeerUser(uid))
        elif uid < -1000000000000:
            channel_id = -uid - 1000000000000
            return await client.get_entity(PeerChannel(channel_id))
        else:
            return await client.get_entity(PeerChat(-uid))
    except Exception:
        pass

    try:
        return await client.get_entity(uid)
    except Exception:
        pass

    logger.warning(
        f"Cannot resolve entity uid={uid}, cache has {len(_DIALOGS_BY_ID)} entries. "
        "Will NOT re-warmup cache here (use /reload_cache or wait for periodic warmup)."
    )
    raise ValueError(
        f"Cannot resolve entity from user_id={uid}. "
        "Make sure this session has an existing dialog with the user/channel, "
        "or use 'username'."
    )

async def resolve_recipient(client: TelegramClient, user_id: Optional[int], username: Optional[str]):
    if username:
        uname = username.strip()
        if uname.startswith("@"):
            uname = uname[1:]
        return await client.get_entity(uname)
    if user_id is None:
        raise ValueError("Specify 'user_id' or 'username'")
    return await resolve_entity_by_id(client, int(user_id))

# -------------------- НОРМАЛИЗАЦИЯ ФАЙЛОВ -------------------
async def _normalize_file_entry(client: TelegramClient, item: Union[str, Dict[str, Any]]):
    meta = {"force_document": False, "supports_streaming": None, "filename": None}

    if isinstance(item, dict):
        path = item.get("file") or item.get("url") or item.get("path")
        meta["force_document"] = bool(item.get("force_document", False))
        meta["supports_streaming"] = item.get("supports_streaming", None)
        meta["filename"] = item.get("filename")
    else:
        path = item

    if not path:
        raise ValueError("Empty file reference")

    if isinstance(path, str):
        parsed = _parse_tg_link_sync(path)
        if parsed:
            ch, mid = parsed
            media = await _get_media_from_tg_post(client, ch, mid)
            return media, meta

    if isinstance(path, str) and _is_url(path):
        return item, meta

    if isinstance(path, str) and os.path.exists(path):
        return item, meta

    if isinstance(path, str):
        return item, meta

    raise ValueError("Unsupported file reference format")

# -------------------- ОТПРАВКА -------------------
async def _send_any(
    client: TelegramClient,
    entity: Any,
    files: List[Union[str, Dict[str, Any]]],
    caption: str,
    parse_mode: str,
    disable_web_page_preview: bool
):
    prepared: List[Tuple[Union[str, Any], Dict[str, Any]]] = []
    for f in files:
        prepared.append(await _normalize_file_entry(client, f))

    if len(prepared) == 1:
        payload, meta = prepared[0]
        if meta["supports_streaming"] is None and not meta["force_document"]:
            hint = _guess_file_hint(files[0])
            if _looks_like_video(hint):
                meta["supports_streaming"] = True

        file_arg: Any = (payload, {"file_name": meta["filename"]}) if meta["filename"] else payload
        sent = await client.send_file(
            entity=entity,
            file=file_arg,
            caption=caption or "",
            parse_mode=parse_mode,
            force_document=bool(meta["force_document"]),
            supports_streaming=bool(meta["supports_streaming"]),
            link_preview=not disable_web_page_preview
        )
        return [sent]

    first_caption = caption or ""
    files_list: List[Any] = []
    for payload, meta in prepared:
        files_list.append((payload, {"file_name": meta["filename"]}) if meta.get("filename") else payload)

    sent = await client.send_file(
        entity=entity,
        file=files_list,
        caption=first_caption,
        parse_mode=parse_mode,
        link_preview=not disable_web_page_preview
    )
    return sent if isinstance(sent, list) else [sent]


async def _send_media_with_retry(
    client: TelegramClient,
    user_id: Optional[int],
    username: Optional[str],
    files: List,
    caption: str,
    parse_mode: str,
    disable_web_page_preview: bool
):
    entity = await resolve_recipient(client, user_id=user_id, username=username)
    msgs = await _send_any(client, entity, files, caption, parse_mode, disable_web_page_preview)
    return entity, msgs


# -------------------- HTTP -------------------
def _record_error(err: str):
    global _error_count
    _error_count += 1
    _last_errors.append({"ts": time.time(), "error": err})


@app.route("/health", methods=["GET"])
def health():
    return jsonify({"status": "ok" if _client is not None else "not_ready"})


@app.route("/stats", methods=["GET"])
def stats():
    return jsonify({
        "cache_size": len(_DIALOGS_BY_ID),
        "uptime_seconds": round(time.time() - _start_time, 1),
        "error_count": _error_count,
        "last_errors": list(_last_errors),
    })


@app.route("/reload_cache", methods=["POST"])
def reload_cache():
    if _client is None:
        return jsonify({"status": "error", "error": "client not ready"}), 503
    try:
        run_coro(_warmup_dialog_cache(_client), timeout=120)
        return jsonify({"status": "ok", "cache_size": len(_DIALOGS_BY_ID)})
    except Exception as e:
        _record_error(f"reload_cache: {e}")
        return jsonify({"status": "error", "error": str(e)}), 500

@app.route("/send_media", methods=["POST"])
def send_media():
    try:
        _assert_ready()
    except Exception as e:
        return jsonify({"status": "error", "error": str(e)}), 503

    try:
        raw_preview = request.get_data(as_text=True)[:500]
        app.logger.info(f"[send_media] CT={request.content_type} RAW={raw_preview}")
    except Exception:
        pass

    try:
        data = request.get_json(force=True)
    except Exception as e:
        return jsonify({"status": "error", "error": f"Invalid JSON: {e}"}), 400

    user_id = data.get("user_id")
    username = data.get("username")
    files = data.get("files")
    caption = data.get("caption", "")
    parse_mode = (data.get("parse_mode") or "html").lower()
    disable_web_page_preview = bool(data.get("disable_web_page_preview", False))

    if user_id is not None:
        try:
            user_id = int(user_id)
        except Exception:
            return jsonify({"status": "error", "error": "user_id must be integer"}), 400

    if not (user_id is not None or username):
        return jsonify({"status": "error", "error": "Specify 'user_id' or 'username'"}), 400

    if not files or not isinstance(files, list):
        return jsonify({"status": "error", "error": "files must be a non-empty list"}), 400

    try:
        entity, msgs = run_coro(_run_with_retry(
            _send_media_with_retry,
            _client,
            user_id=user_id,
            username=username,
            files=files,
            caption=caption,
            parse_mode=parse_mode,
            disable_web_page_preview=disable_web_page_preview
        ), timeout=180)
        return jsonify({
            "status": "ok",
            "recipient": username if username else user_id,
            "message_ids": [m.id for m in msgs],
            "count": len(msgs)
        })
    except errors.FloodWaitError as e:
        _record_error(f"FloodWait: {e.seconds}s")
        return jsonify({"status": "error", "error": "FloodWait", "retry_after": e.seconds}), 429
    except errors.FileReferenceExpiredError:
        _record_error("FileReferenceExpired")
        return jsonify({"status": "error", "error": "File reference expired. Re-fetch the post or use a fresh link."}), 410
    except errors.UsernameNotOccupiedError:
        _record_error("UsernameNotOccupied")
        return jsonify({"status": "error", "error": "Channel/username not found"}), 404
    except errors.PeerIdInvalidError:
        _record_error("PeerIdInvalid")
        return jsonify({"status": "error", "error": "Invalid peer (user_id/username)"}), 400
    except Exception as e:
        import traceback
        _record_error(f"{type(e).__name__}: {e}")
        logger.error(f"send_media failed: {type(e).__name__}: {e}")
        return jsonify({"status": "error", "error": str(e), "trace": traceback.format_exc()}), 500

# -------------------- PERIODIC CACHE WARMUP ----
async def _periodic_cache_warmup():
    """Re-warm dialog cache every CACHE_WARMUP_INTERVAL seconds."""
    while True:
        await asyncio.sleep(CACHE_WARMUP_INTERVAL)
        try:
            logger.info("Periodic cache warmup started...")
            await _warmup_dialog_cache(_client)
            logger.info(f"Periodic cache warmup done, {len(_DIALOGS_BY_ID)} entries")
        except Exception as e:
            _record_error(f"periodic_warmup: {e}")
            logger.error(f"Periodic cache warmup failed: {e}")


# -------------------- BOOTSTRAP ----------------
def _telethon_loop():
    global _loop, _client
    if not API_ID or not API_HASH:
        raise RuntimeError("Set API_ID/API_HASH in the script before starting the server.")
    _loop = asyncio.new_event_loop()
    asyncio.set_event_loop(_loop)
    _client = TelegramClient(SESSION_PATH, API_ID, API_HASH, catch_up=False)
    started = _client.start()
    if asyncio.iscoroutine(started):
        _loop.run_until_complete(started)

    _loop.run_until_complete(_warmup_dialog_cache(_client))
    _loop.create_task(_periodic_cache_warmup())

    logger.info("Telethon client started, dialog cache warmed up")
    _loop.run_forever()

threading.Thread(target=_telethon_loop, name="telethon-loop", daemon=True).start()

if __name__ == "__main__":
    from werkzeug.serving import run_simple
    run_simple(BIND_HOST, BIND_PORT, app, threaded=True)
