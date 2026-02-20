# -*- coding: utf-8 -*-
"""
core/bridge.py — TelethonBridge: обёртка над TelegramClient.

Один bridge = один Telegram-аккаунт.
Включает:
 - подключение / старт
 - кэш диалогов (warmup + mini-refresh)
 - отслеживание здоровья (status, flood_until, error_count)
 - resolve entity по ID / username / chat_id
"""
import asyncio
import time
import logging
from typing import Any, Dict, Optional

from telethon import TelegramClient, functions, types
from telethon.tl.types import PeerChannel, PeerChat, PeerUser
from telethon.utils import get_peer_id

import config

logger = logging.getLogger("core.bridge")


class TelethonBridge:
    """Обёртка над одним TelegramClient с кэшем и здоровьем."""

    # --- Статусы ---
    STATUS_OFFLINE = "offline"
    STATUS_STARTING = "starting"
    STATUS_HEALTHY = "healthy"
    STATUS_FLOOD = "flood_wait"
    STATUS_ERROR = "error"
    STATUS_BANNED = "banned"

    def __init__(self, name: str, session: str, priority: int,
                 loop: asyncio.AbstractEventLoop,
                 api_id: int = None, api_hash: str = None):
        self.name = name
        self.session = session
        self.priority = priority
        self._loop = loop
        self.api_id = api_id
        self.api_hash = api_hash

        self.client: Optional[TelegramClient] = None
        self.self_user_id: Optional[int] = None
        self.self_username: Optional[str] = None

        # Health
        self.status: str = self.STATUS_OFFLINE
        self.flood_until: float = 0.0  # timestamp когда FloodWait кончится
        self.last_error: Optional[str] = None
        self.error_count: int = 0
        self.operations_count: int = 0
        self.last_active: float = 0.0

        # Dialog cache
        self._dialogs: Dict[int, Any] = {}
        self._last_mini_refresh: float = 0.0

    # === Lifecycle ============================================================

    async def start(self):
        """Подключить клиент и прогреть кэш."""
        self.status = self.STATUS_STARTING
        logger.info("Starting bridge %s (session=%s)", self.name, self.session)
        try:
            self.client = TelegramClient(
                self.session, self.api_id, self.api_hash,
                loop=self._loop, catch_up=False,
            )
            started = self.client.start()
            if asyncio.iscoroutine(started):
                await started

            me = await self.client.get_me()
            self.self_user_id = me.id
            self.self_username = me.username

            await self.warmup_cache()
            self.status = self.STATUS_HEALTHY
            logger.info(
                "Bridge %s ready (user_id=%s, @%s, cache=%d)",
                self.name, self.self_user_id, self.self_username,
                len(self._dialogs),
            )
        except Exception as e:
            self.status = self.STATUS_ERROR
            self.last_error = str(e)
            logger.error("Bridge %s failed to start: %s", self.name, e)
            raise

    async def stop(self):
        if self.client:
            try:
                await self.client.disconnect()
            except Exception:
                pass
        self.status = self.STATUS_OFFLINE

    # === Health ===============================================================

    @property
    def is_healthy(self) -> bool:
        if self.status == self.STATUS_FLOOD:
            if time.time() >= self.flood_until:
                self.status = self.STATUS_HEALTHY
                return True
            return False
        return self.status == self.STATUS_HEALTHY

    @property
    def flood_remaining(self) -> int:
        if self.status != self.STATUS_FLOOD:
            return 0
        return max(0, int(self.flood_until - time.time()))

    def mark_flood(self, seconds: int):
        self.flood_until = time.time() + seconds
        self.status = self.STATUS_FLOOD
        self.last_error = f"FloodWait {seconds}s"
        logger.warning("Bridge %s: FloodWait %ds", self.name, seconds)

    def mark_error(self, error: str):
        self.error_count += 1
        self.last_error = error
        # После 10 ошибок подряд без успеха — помечаем как error
        if self.error_count >= 10:
            self.status = self.STATUS_ERROR
            logger.error("Bridge %s: too many errors, marking as error", self.name)

    def mark_banned(self):
        self.status = self.STATUS_BANNED
        self.last_error = "Account banned"
        logger.error("Bridge %s: BANNED", self.name)

    def mark_success(self):
        self.error_count = 0
        self.last_error = None
        self.operations_count += 1
        self.last_active = time.time()
        if self.status in (self.STATUS_ERROR, self.STATUS_FLOOD):
            if self.status == self.STATUS_FLOOD and time.time() < self.flood_until:
                return
            self.status = self.STATUS_HEALTHY

    def to_dict(self) -> dict:
        return {
            "name": self.name,
            "session": self.session,
            "priority": self.priority,
            "status": self.status,
            "is_healthy": self.is_healthy,
            "flood_remaining": self.flood_remaining,
            "last_error": self.last_error,
            "error_count": self.error_count,
            "operations_count": self.operations_count,
            "last_active": self.last_active,
            "self_user_id": self.self_user_id,
            "self_username": self.self_username,
            "cache_size": len(self._dialogs),
        }

    # === Dialog Cache =========================================================

    async def warmup_cache(self):
        """Полный прогрев: загрузить все диалоги."""
        self._dialogs.clear()
        async for d in self.client.iter_dialogs():
            self._add_to_cache(d.entity)
        logger.info("Bridge %s: cache warmed, %d entries", self.name, len(self._dialogs))

    async def mini_refresh_cache(self):
        """Лёгкий прогрев: последние 100 диалогов."""
        now = time.time()
        if now - self._last_mini_refresh < config.MINI_REFRESH_COOLDOWN:
            return
        self._last_mini_refresh = now
        added = 0
        try:
            async for d in self.client.iter_dialogs(limit=100):
                self._add_to_cache(d.entity)
                added += 1
            logger.info(
                "Bridge %s: mini refresh +%d, total=%d",
                self.name, added, len(self._dialogs),
            )
        except Exception as e:
            logger.warning("Bridge %s: mini refresh failed: %s", self.name, e)

    def _add_to_cache(self, ent):
        uid = getattr(ent, "id", None)
        if uid is None:
            return
        # Супергруппа / канал → -100<id>
        if hasattr(ent, "broadcast") or hasattr(ent, "megagroup"):
            full_id = -1000000000000 - uid
            self._dialogs[full_id] = ent
        # Обычная группа
        elif hasattr(ent, "title") and not hasattr(ent, "username"):
            self._dialogs[-uid] = ent
        else:
            self._dialogs[uid] = ent
        # Дубль по peer_id
        try:
            pid = get_peer_id(ent)
            if pid not in self._dialogs:
                self._dialogs[pid] = ent
        except Exception:
            pass

    # === Entity Resolve =======================================================

    async def get_entity(self, ref: Any) -> Any:
        """
        Резолвит entity по:
         - int (chat_id / user_id)
         - str ("@username" / "username" / "-1001234567890")
        С fallback на кэш и mini-refresh.
        """
        # Нормализуем строковый ID в int
        if isinstance(ref, str):
            s = ref.strip()
            if s.lstrip("-").isdigit():
                ref = int(s)

        # 1. Прямой API-вызов
        try:
            return await self.client.get_entity(ref)
        except (ValueError, KeyError):
            pass

        # 2. Кэш
        cached = self._find_in_cache(ref)
        if cached is not None:
            return cached

        # 3. Mini-refresh + кэш
        await self.mini_refresh_cache()
        cached = self._find_in_cache(ref)
        if cached is not None:
            return cached

        # 4. Ещё раз API (после mini-refresh Telethon знает больше)
        try:
            return await self.client.get_entity(ref)
        except (ValueError, KeyError):
            pass

        # 5. Пробуем Peer-обёртки для int
        if isinstance(ref, int):
            for peer_cls, transform in [
                (PeerChannel, lambda x: -x - 1000000000000 if x < -1000000000000 else x),
                (PeerChat, lambda x: -x if -1000000000000 < x < 0 else None),
                (PeerUser, lambda x: x if x > 0 else None),
            ]:
                mapped = transform(ref)
                if mapped is not None:
                    try:
                        return await self.client.get_entity(peer_cls(mapped))
                    except Exception:
                        continue

        raise ValueError(f"Cannot resolve entity {ref} (cache={len(self._dialogs)})")

    def _find_in_cache(self, ref) -> Optional[Any]:
        if isinstance(ref, int):
            ent = self._dialogs.get(ref)
            if ent is not None:
                return ent
            for cached_ent in self._dialogs.values():
                if getattr(cached_ent, "id", None) == ref:
                    return cached_ent
                try:
                    if get_peer_id(cached_ent) == ref:
                        return cached_ent
                except Exception:
                    pass
        elif isinstance(ref, str):
            uname = ref.lstrip("@")
            for cached_ent in self._dialogs.values():
                if getattr(cached_ent, "username", None) == uname:
                    return cached_ent
        return None

    # === Периодический прогрев ================================================

    async def periodic_warmup(self):
        """Бесконечный цикл: прогреваем кэш каждые CACHE_WARMUP_INTERVAL секунд."""
        while True:
            await asyncio.sleep(config.CACHE_WARMUP_INTERVAL)
            try:
                await self.warmup_cache()
            except Exception as e:
                logger.error("Bridge %s: periodic warmup failed: %s", self.name, e)
