# -*- coding: utf-8 -*-
"""
core/retry.py — Retry, reconnect, error classification.
"""
import asyncio
import logging

from telethon import TelegramClient

import config

logger = logging.getLogger("core.retry")

RETRIABLE_ERRORS = (
    ConnectionError,
    OSError,
    TimeoutError,
    asyncio.TimeoutError,
)


def is_persistent_timestamp_error(e: Exception) -> bool:
    name = type(e).__name__.lower()
    text = str(e).lower()
    return "persistenttimestamp" in name or "persistent timestamp" in text


def is_flood_wait(e: Exception) -> bool:
    return type(e).__name__ == "FloodWaitError"


def flood_wait_seconds(e: Exception) -> int:
    return getattr(e, "seconds", 0)


async def reconnect_client(client: TelegramClient):
    """Disconnect + reconnect. Raises if authorization lost."""
    logger.warning("Reconnecting Telethon client...")
    try:
        await client.disconnect()
    except Exception:
        pass
    await asyncio.sleep(1)
    await client.connect()
    if not await client.is_user_authorized():
        logger.error("Client not authorized after reconnect!")
        raise RuntimeError("Client lost authorization")
    logger.info("Reconnect successful")


async def run_with_retry(coro_func, client: TelegramClient, *args, **kwargs):
    """
    Вызывает coro_func(*args, **kwargs) с retry.
    При сетевой ошибке или PersistentTimestamp — reconnect + retry.
    FloodWaitError пробрасывается наверх (обрабатывается роутером).
    """
    last_error = None
    for attempt in range(1, config.MAX_RETRIES + 1):
        try:
            return await coro_func(*args, **kwargs)
        except RETRIABLE_ERRORS as e:
            last_error = e
            logger.warning(
                "Attempt %d/%d failed (network): %s: %s",
                attempt, config.MAX_RETRIES, type(e).__name__, e,
            )
            if attempt < config.MAX_RETRIES:
                await reconnect_client(client)
                await asyncio.sleep(config.RETRY_DELAY)
        except Exception as e:
            if is_persistent_timestamp_error(e):
                last_error = e
                logger.warning(
                    "Attempt %d/%d failed (PersistentTimestamp): %s",
                    attempt, config.MAX_RETRIES, e,
                )
                if attempt < config.MAX_RETRIES:
                    await reconnect_client(client)
                    await asyncio.sleep(config.RETRY_DELAY)
            else:
                raise
    raise last_error
