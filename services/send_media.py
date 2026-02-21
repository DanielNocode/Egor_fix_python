# -*- coding: utf-8 -*-
"""
services/send_media.py — POST /send_media

Отправка медиа/документов с подписью.
Использует привязанный аккаунт из реестра.

JSON запрос (не меняется):
{
    "user_id": 123456,       // или "username": "@channel"
    "files": ["https://..."],
    "caption": "Подпись",
    "parse_mode": "html",
    "disable_web_page_preview": false
}
"""
import asyncio
import os
import re
import logging
from typing import Any, Dict, List, Optional, Union, Tuple
from urllib.parse import urlparse

from flask import Blueprint, request, jsonify
from telethon import TelegramClient, errors as tl_errors
from telethon.tl.types import PeerChannel, PeerChat, PeerUser

from core.bridge import TelethonBridge
from core.router import AccountRouter
from core.retry import run_with_retry

logger = logging.getLogger("svc.send_media")

bp = Blueprint("send_media", __name__)
_router: Optional[AccountRouter] = None
_loop: Optional[asyncio.AbstractEventLoop] = None


def init(router: AccountRouter, loop: asyncio.AbstractEventLoop):
    global _router, _loop
    _router = router
    _loop = loop


def _run(coro, timeout=180):
    return asyncio.run_coroutine_threadsafe(coro, _loop).result(timeout=timeout)


def _save_failed(data: dict, error: str):
    try:
        _router.registry.save_failed_request(
            service="send_media", endpoint="/send_media",
            request_payload=data, error=error,
        )
    except Exception:
        pass


# === Helpers (из оригинального send_media) ====================================

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


def _guess_file_hint(payload) -> Optional[str]:
    if isinstance(payload, str):
        return payload
    if isinstance(payload, dict):
        return payload.get("filename") or payload.get("file") or payload.get("url") or payload.get("path")
    return None


_TG_PATTERNS = [
    r'^(?:https?://)?t\.me/([^/]+)/(\d+)$',
    r'^(?:https?://)?telegram\.me/([^/]+)/(\d+)$',
]


def _parse_tg_link(link: str) -> Optional[Tuple[str, int]]:
    link = link.strip()
    for p in _TG_PATTERNS:
        m = re.match(p, link)
        if m:
            return m.group(1), int(m.group(2))
    return None


async def _get_media_from_tg_post(bridge: TelethonBridge, channel: str, msg_id: int):
    ent = await bridge.get_entity(channel)
    msg = await bridge.client.get_messages(ent, ids=msg_id)
    if not msg:
        raise ValueError("Message not found")
    if not msg.media:
        raise ValueError("Message has no media")
    return msg.media


async def _normalize_file_entry(bridge: TelethonBridge, item):
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
        parsed = _parse_tg_link(path)
        if parsed:
            ch, mid = parsed
            media = await _get_media_from_tg_post(bridge, ch, mid)
            return media, meta

    if isinstance(path, str) and _is_url(path):
        return item, meta

    if isinstance(path, str) and os.path.exists(path):
        return item, meta

    if isinstance(path, str):
        return item, meta

    raise ValueError("Unsupported file reference format")


async def _resolve_recipient(bridge: TelethonBridge,
                              user_id: Optional[int],
                              username: Optional[str]) -> Any:
    if username:
        uname = username.strip().lstrip("@")
        return await bridge.get_entity(uname)
    if user_id is None:
        raise ValueError("Specify 'user_id' or 'username'")
    return await bridge.get_entity(int(user_id))


# === Основная логика ==========================================================

async def _send_media_impl(
    bridge: TelethonBridge,
    user_id: Optional[int], username: Optional[str],
    files: List, caption: str,
    parse_mode: str, disable_web_page_preview: bool,
):
    entity = await _resolve_recipient(bridge, user_id, username)

    # Prepare files
    prepared: List[Tuple[Any, Dict[str, Any]]] = []
    for f in files:
        prepared.append(await _normalize_file_entry(bridge, f))

    if len(prepared) == 1:
        payload, meta = prepared[0]
        if meta["supports_streaming"] is None and not meta["force_document"]:
            hint = _guess_file_hint(files[0])
            if _looks_like_video(hint):
                meta["supports_streaming"] = True

        file_arg = (payload, {"file_name": meta["filename"]}) if meta["filename"] else payload
        sent = await bridge.client.send_file(
            entity=entity, file=file_arg,
            caption=caption or "",
            parse_mode=parse_mode,
            force_document=bool(meta["force_document"]),
            supports_streaming=bool(meta["supports_streaming"]),
            link_preview=not disable_web_page_preview,
        )
        return entity, [sent]

    # Multiple files
    files_list = []
    for payload, meta in prepared:
        files_list.append(
            (payload, {"file_name": meta["filename"]}) if meta.get("filename") else payload
        )
    sent = await bridge.client.send_file(
        entity=entity, file=files_list,
        caption=caption or "",
        parse_mode=parse_mode,
        link_preview=not disable_web_page_preview,
    )
    return entity, sent if isinstance(sent, list) else [sent]


# === HTTP endpoint ============================================================

@bp.route("/send_media", methods=["POST"])
def send_media():
    if _router is None:
        return jsonify({"status": "error", "error": "not initialized"}), 503

    try:
        raw_preview = request.get_data(as_text=True)[:500]
        logger.info("[send_media] CT=%s RAW=%s", request.content_type, raw_preview)
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

    # Проверяем, не вышли ли мы уже из этого чата
    if user_id is not None and _router.registry.is_left(str(user_id)):
        logger.info("send_media skipped: chat %s already left", user_id)
        return jsonify({"status": "skipped", "reason": "chat already left"})

    # Выбираем аккаунт
    try:
        bridge = _router.pick_for_recipient(service="send_media", user_id=user_id, username=username)
    except RuntimeError as e:
        return jsonify({"status": "error", "error": str(e)}), 503

    try:
        entity, msgs = _run(
            run_with_retry(
                _send_media_impl, bridge.client,
                bridge, user_id, username,
                files, caption, parse_mode, disable_web_page_preview,
            ),
            timeout=180,
        )
        chat_str = str(user_id) if user_id else (username or "")
        _router.handle_success(bridge, chat_str, "send_media")
        return jsonify({
            "status": "ok",
            "recipient": username if username else user_id,
            "message_ids": [m.id for m in msgs],
            "count": len(msgs),
        })

    except tl_errors.FloodWaitError as e:
        chat_str = str(user_id) if user_id else (username or "")
        _router.handle_error(bridge, e, chat_str, "send_media")
        # Failover — пробуем все оставшиеся аккаунты
        fallbacks = _router.pool.get_all_healthy_except("send_media", exclude_key=bridge.name)
        for fallback in fallbacks:
            try:
                entity, msgs = _run(
                    run_with_retry(
                        _send_media_impl, fallback.client,
                        fallback, user_id, username,
                        files, caption, parse_mode, disable_web_page_preview,
                    ),
                    timeout=180,
                )
                _router.handle_success(fallback, chat_str, "send_media")
                return jsonify({
                    "status": "ok",
                    "recipient": username if username else user_id,
                    "message_ids": [m.id for m in msgs],
                    "count": len(msgs),
                })
            except Exception:
                continue
        _save_failed(data, f"FloodWait {e.seconds}s (all accounts)")
        return jsonify({"status": "error", "error": "FloodWait", "retry_after": e.seconds}), 429

    except tl_errors.FileReferenceExpiredError:
        _save_failed(data, "File reference expired")
        return jsonify({"status": "error", "error": "File reference expired. Re-fetch the post or use a fresh link."}), 410

    except tl_errors.UsernameNotOccupiedError:
        _save_failed(data, "Channel/username not found")
        return jsonify({"status": "error", "error": "Channel/username not found"}), 404

    except tl_errors.PeerIdInvalidError:
        _save_failed(data, "Invalid peer")
        return jsonify({"status": "error", "error": "Invalid peer (user_id/username)"}), 400

    except ValueError as e:
        # Entity resolution failed — пробуем все оставшиеся аккаунты
        chat_str = str(user_id) if user_id else (username or "")
        if "Cannot resolve" in str(e):
            logger.warning("send_media: entity %s not found on %s, trying failover", chat_str, bridge.name)
            fallbacks = _router.pool.get_all_healthy_except("send_media", exclude_key=bridge.name)
            for fallback in fallbacks:
                try:
                    entity, msgs = _run(
                        run_with_retry(
                            _send_media_impl, fallback.client,
                            fallback, user_id, username,
                            files, caption, parse_mode, disable_web_page_preview,
                        ),
                        timeout=180,
                    )
                    _router.handle_success(fallback, chat_str, "send_media")
                    return jsonify({
                        "status": "ok",
                        "recipient": username if username else user_id,
                        "message_ids": [m.id for m in msgs],
                        "count": len(msgs),
                    })
                except Exception:
                    continue
        _router.handle_error(bridge, e, chat_str, "send_media")
        logger.error("send_media failed: %s: %s", type(e).__name__, e)
        _save_failed(data, str(e))
        return jsonify({"status": "error", "error": str(e)}), 500

    except Exception as e:
        import traceback
        chat_str = str(user_id) if user_id else (username or "")
        _router.handle_error(bridge, e, chat_str, "send_media")
        logger.error("send_media failed: %s: %s", type(e).__name__, e)
        _save_failed(data, str(e))
        return jsonify({
            "status": "error",
            "error": str(e),
            "trace": traceback.format_exc(),
        }), 500


# === Extra endpoints (совместимость) ==========================================

@bp.route("/health", methods=["GET"])
def health():
    ok = _router is not None and _router.pool.get_best("send_media") is not None
    return jsonify({"status": "ok" if ok else "not_ready"})


@bp.route("/stats", methods=["GET"])
def stats():
    if _router is None:
        return jsonify({})
    pool = _router.pool
    bridges = pool.get_healthy_list("send_media")
    total_cache = sum(len(b._dialogs) for b in bridges)
    return jsonify({
        "cache_size": total_cache,
        "accounts": pool.service_statuses("send_media"),
        "error_count": pool.total_errors,
        "operations_count": pool.total_operations,
    })


@bp.route("/reload_cache", methods=["POST"])
def reload_cache():
    if _router is None:
        return jsonify({"status": "error", "error": "not ready"}), 503
    try:
        _run(_router.pool.reload_service_caches("send_media"), timeout=120)
        bridges = _router.pool.get_healthy_list("send_media")
        total_cache = sum(len(b._dialogs) for b in bridges)
        return jsonify({"status": "ok", "cache_size": total_cache})
    except Exception as e:
        return jsonify({"status": "error", "error": str(e)}), 500
