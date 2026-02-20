# -*- coding: utf-8 -*-
"""
core/pool.py — AccountPool: управление пулом Telegram-аккаунтов.

Каждый bridge = один Telegram-аккаунт + один сервис (своя сессия).
Ключ bridge: "{account_name}:{service}" — например "main:create_chat".
"""
import asyncio
import logging
from typing import Dict, List, Optional

import config
from core.bridge import TelethonBridge

logger = logging.getLogger("core.pool")


class AccountPool:
    """
    Пул TelethonBridge'ей.
    Один bridge = один аккаунт + один сервис (= своя .session).
    """

    def __init__(self, loop: asyncio.AbstractEventLoop):
        self._loop = loop
        # Все bridge'и: ключ = "account_name:service"
        self.bridges: Dict[str, TelethonBridge] = {}
        # Порядок по приоритету для каждого сервиса
        self._sorted_by_service: Dict[str, List[str]] = {}

    # === Lifecycle ============================================================

    async def start_all(self):
        """Создаём и запускаем bridge'и для каждой пары (аккаунт, сервис)."""
        for acc in sorted(config.ACCOUNTS, key=lambda a: a["priority"]):
            acc_name = acc["name"]
            sessions = acc.get("sessions", {})

            for service, session_name in sessions.items():
                bridge_key = f"{acc_name}:{service}"
                bridge = TelethonBridge(
                    name=bridge_key,
                    account_name=acc_name,
                    service=service,
                    session=session_name,
                    priority=acc["priority"],
                    loop=self._loop,
                    api_id=acc["api_id"],
                    api_hash=acc["api_hash"],
                )
                self.bridges[bridge_key] = bridge

                if service not in self._sorted_by_service:
                    self._sorted_by_service[service] = []
                self._sorted_by_service[service].append(bridge_key)

                try:
                    await bridge.start()
                    self._loop.create_task(bridge.periodic_warmup())
                except Exception as e:
                    logger.error("Failed to start bridge %s: %s", bridge_key, e)

        total = len(self.bridges)
        healthy = sum(1 for b in self.bridges.values() if b.is_healthy)
        logger.info(
            "AccountPool started: %d/%d bridges healthy", healthy, total,
        )
        for svc, keys in self._sorted_by_service.items():
            svc_healthy = sum(1 for k in keys if self.bridges[k].is_healthy)
            logger.info(
                "  service=%s: %d/%d healthy", svc, svc_healthy, len(keys),
            )

    async def stop_all(self):
        for bridge in self.bridges.values():
            await bridge.stop()

    # === Выбор bridge по сервису ==============================================

    def get(self, bridge_key: str) -> Optional[TelethonBridge]:
        return self.bridges.get(bridge_key)

    def get_best(self, service: str) -> Optional[TelethonBridge]:
        """Вернуть самый приоритетный здоровый bridge для данного сервиса."""
        for key in self._sorted_by_service.get(service, []):
            bridge = self.bridges[key]
            if bridge.is_healthy:
                return bridge
        return None

    def get_healthy_list(self, service: str) -> List[TelethonBridge]:
        """Все здоровые bridge'и для сервиса, по приоритету."""
        return [
            self.bridges[k]
            for k in self._sorted_by_service.get(service, [])
            if self.bridges[k].is_healthy
        ]

    def get_next_healthy(self, service: str, exclude_key: str) -> Optional[TelethonBridge]:
        """Следующий здоровый bridge для сервиса, кроме указанного."""
        for key in self._sorted_by_service.get(service, []):
            if key == exclude_key:
                continue
            bridge = self.bridges[key]
            if bridge.is_healthy:
                return bridge
        return None

    def get_by_account(self, account_name: str, service: str) -> Optional[TelethonBridge]:
        """Получить bridge конкретного аккаунта для конкретного сервиса."""
        key = f"{account_name}:{service}"
        return self.bridges.get(key)

    # === Информация ===========================================================

    def all_statuses(self) -> List[dict]:
        return [b.to_dict() for b in self.bridges.values()]

    def service_statuses(self, service: str) -> List[dict]:
        return [
            self.bridges[k].to_dict()
            for k in self._sorted_by_service.get(service, [])
        ]

    @property
    def total_operations(self) -> int:
        return sum(b.operations_count for b in self.bridges.values())

    @property
    def total_errors(self) -> int:
        return sum(b.error_count for b in self.bridges.values())

    # === Reload cache =========================================================

    async def reload_all_caches(self):
        for bridge in self.bridges.values():
            if bridge.is_healthy:
                try:
                    await bridge.warmup_cache()
                except Exception as e:
                    logger.warning("Cache reload failed for %s: %s", bridge.name, e)

    async def reload_service_caches(self, service: str):
        for key in self._sorted_by_service.get(service, []):
            bridge = self.bridges[key]
            if bridge.is_healthy:
                try:
                    await bridge.warmup_cache()
                except Exception as e:
                    logger.warning("Cache reload failed for %s: %s", bridge.name, e)
