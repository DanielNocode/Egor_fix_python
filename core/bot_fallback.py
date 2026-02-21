# -*- coding: utf-8 -*-
"""
core/bot_fallback.py — Fallback через Telegram Bot API.

Когда все Telethon-аккаунты недоступны (бан, FloodWait, ошибки),
отправляем сообщение через @alex_rumhelp_bot, который всегда есть в группах.

Используется стандартный HTTP Bot API: https://api.telegram.org/bot<token>/...
"""
import logging
from typing import Any, Dict, List, Optional

import requests as http_requests

import config

logger = logging.getLogger("core.bot_fallback")

_BASE = "https://api.telegram.org/bot{token}"


def is_configured() -> bool:
    """Проверяет, задан ли токен бота."""
    return bool(config.BOT_TOKEN)


def _api_url(method: str) -> str:
    return f"{_BASE.format(token=config.BOT_TOKEN)}/{method}"


def _call(method: str, data: dict, timeout: int = 30) -> Dict[str, Any]:
    """Вызов Bot API метода. Возвращает response JSON."""
    url = _api_url(method)
    resp = http_requests.post(url, json=data, timeout=timeout)
    result = resp.json()
    if not result.get("ok"):
        desc = result.get("description", "Unknown error")
        logger.error("Bot API %s failed: %s", method, desc)
        raise RuntimeError(f"Bot API error: {desc}")
    return result


def send_text(
    chat_id: Any,
    text: str,
    parse_mode: str = "HTML",
    disable_web_page_preview: bool = True,
    reply_to_message_id: Optional[int] = None,
) -> Dict[str, Any]:
    """
    Отправить текстовое сообщение через Bot API.
    Возвращает результат Bot API (message object).
    """
    if not is_configured():
        raise RuntimeError("Bot token not configured")

    data = {
        "chat_id": int(chat_id) if str(chat_id).lstrip("-").isdigit() else chat_id,
        "text": text,
        "parse_mode": parse_mode.upper() if parse_mode else "HTML",
    }
    if disable_web_page_preview:
        data["disable_web_page_preview"] = True
    if reply_to_message_id:
        data["reply_to_message_id"] = reply_to_message_id

    logger.info("Bot fallback send_text to %s (len=%d)", chat_id, len(text))
    result = _call("sendMessage", data)
    msg = result.get("result", {})
    logger.info("Bot fallback send_text OK: message_id=%s", msg.get("message_id"))
    return msg


def send_document(
    chat_id: Any,
    document_url: str,
    caption: str = "",
    parse_mode: str = "HTML",
    filename: Optional[str] = None,
) -> Dict[str, Any]:
    """Отправить документ по URL через Bot API."""
    if not is_configured():
        raise RuntimeError("Bot token not configured")

    data = {
        "chat_id": int(chat_id) if str(chat_id).lstrip("-").isdigit() else chat_id,
        "document": document_url,
    }
    if caption:
        data["caption"] = caption
        data["parse_mode"] = parse_mode.upper() if parse_mode else "HTML"

    logger.info("Bot fallback send_document to %s: %s", chat_id, document_url[:80])
    result = _call("sendDocument", data)
    msg = result.get("result", {})
    logger.info("Bot fallback send_document OK: message_id=%s", msg.get("message_id"))
    return msg


def send_photo(
    chat_id: Any,
    photo_url: str,
    caption: str = "",
    parse_mode: str = "HTML",
) -> Dict[str, Any]:
    """Отправить фото по URL через Bot API."""
    if not is_configured():
        raise RuntimeError("Bot token not configured")

    data = {
        "chat_id": int(chat_id) if str(chat_id).lstrip("-").isdigit() else chat_id,
        "photo": photo_url,
    }
    if caption:
        data["caption"] = caption
        data["parse_mode"] = parse_mode.upper() if parse_mode else "HTML"

    logger.info("Bot fallback send_photo to %s", chat_id)
    result = _call("sendPhoto", data)
    msg = result.get("result", {})
    logger.info("Bot fallback send_photo OK: message_id=%s", msg.get("message_id"))
    return msg


def send_video(
    chat_id: Any,
    video_url: str,
    caption: str = "",
    parse_mode: str = "HTML",
) -> Dict[str, Any]:
    """Отправить видео по URL через Bot API."""
    if not is_configured():
        raise RuntimeError("Bot token not configured")

    data = {
        "chat_id": int(chat_id) if str(chat_id).lstrip("-").isdigit() else chat_id,
        "video": video_url,
    }
    if caption:
        data["caption"] = caption
        data["parse_mode"] = parse_mode.upper() if parse_mode else "HTML"

    logger.info("Bot fallback send_video to %s", chat_id)
    result = _call("sendVideo", data)
    msg = result.get("result", {})
    logger.info("Bot fallback send_video OK: message_id=%s", msg.get("message_id"))
    return msg


def send_media_by_url(
    chat_id: Any,
    file_url: str,
    caption: str = "",
    parse_mode: str = "HTML",
    force_document: bool = False,
) -> Dict[str, Any]:
    """
    Универсальная отправка медиа по URL.
    Пытаемся определить тип по расширению, если не получается — отправляем как документ.
    """
    url_lower = file_url.lower().split("?")[0]

    if not force_document:
        if any(url_lower.endswith(ext) for ext in (".jpg", ".jpeg", ".png", ".gif", ".webp")):
            return send_photo(chat_id, file_url, caption, parse_mode)
        if any(url_lower.endswith(ext) for ext in (".mp4", ".mov", ".m4v", ".webm", ".mkv")):
            return send_video(chat_id, file_url, caption, parse_mode)

    return send_document(chat_id, file_url, caption, parse_mode)
