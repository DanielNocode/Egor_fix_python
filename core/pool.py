# -*- coding: utf-8 -*-
"""
core/pool.py — AccountPool: управление пулом Telegram-аккаунтов.

Каждый bridge = один Telegram-аккаунт + один сервис (своя сессия).
Ключ bridge: "{account_name}:{service}" — например "main:create_chat".
"""
import asyncio
import logging
import random
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
        # 1. Create all bridges
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

        # 2. Start all bridges in parallel (each has ~30s flood wait on cache warmup)
        async def _safe_start(key, bridge):
            try:
                await bridge.start()
                self._loop.create_task(bridge.periodic_warmup())
            except Exception as e:
                logger.error("Failed to start bridge %s: %s", key, e)

        logger.info("Starting %d bridges in parallel...", len(self.bridges))
        await asyncio.gather(
            *[_safe_start(k, b) for k, b in self.bridges.items()]
        )

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

    def get_all_healthy_except(self, service: str, exclude_key: str) -> List[TelethonBridge]:
        """Все здоровые bridge'и для сервиса, кроме указанного (по приоритету)."""
        return [
            self.bridges[k]
            for k in self._sorted_by_service.get(service, [])
            if k != exclude_key and self.bridges[k].is_healthy
        ]

    def get_by_account(self, account_name: str, service: str) -> Optional[TelethonBridge]:
        """Получить bridge конкретного аккаунта для конкретного сервиса."""
        key = f"{account_name}:{service}"
        return self.bridges.get(key)

    def get_least_loaded(self, service: str, chat_counts: Dict[str, int],
                         exclude_key: str = "") -> Optional[TelethonBridge]:
        """Здоровый bridge с наименьшим количеством активных чатов."""
        best = None
        best_count = float("inf")
        for key in self._sorted_by_service.get(service, []):
            if key == exclude_key:
                continue
            bridge = self.bridges[key]
            if not bridge.is_healthy:
                continue
            count = chat_counts.get(bridge.account_name, 0)
            if count < best_count:
                best_count = count
                best = bridge
        return best

    def get_weighted_balanced(self, service: str, chat_counts: Dict[str, int],
                              exclude_key: str = "") -> Optional[TelethonBridge]:
        """Взвешенный выбор: main получает фиксированные 5%,
        остальные 95% делятся между бэкапами по дефициту нагрузки."""
        candidates = []
        counts = []
        for key in self._sorted_by_service.get(service, []):
            if key == exclude_key:
                continue
            bridge = self.bridges[key]
            if not bridge.is_healthy:
                continue
            candidates.append(bridge)
            counts.append(chat_counts.get(bridge.account_name, 0))

        if not candidates:
            return None
        if len(candidates) == 1:
            return candidates[0]

        # main = 5%, остальные 95% по дефициту
        MAIN_PCT = 0.05
        main_indices = [i for i, b in enumerate(candidates) if b.account_name == "main"]
        backup_indices = [i for i, b in enumerate(candidates) if b.account_name != "main"]

        # Если main нет среди кандидатов — чисто дефицитная балансировка
        if not main_indices:
            max_count = max(counts)
            weights = [max_count - c + 1 for c in counts]
            return random.choices(candidates, weights=weights, k=1)[0]

        # Если нет бэкапов — только main
        if not backup_indices:
            return candidates[main_indices[0]]

        # Веса бэкапов по дефициту
        backup_counts = [counts[i] for i in backup_indices]
        max_backup = max(backup_counts)
        backup_weights = [max_backup - c + 1 for c in backup_counts]
        backup_total = sum(backup_weights)

        # Финальные веса: main=5%, бэкапы делят 95%
        weights = [0.0] * len(candidates)
        weights[main_indices[0]] = MAIN_PCT
        for idx, bi in enumerate(backup_indices):
            weights[bi] = (1.0 - MAIN_PCT) * backup_weights[idx] / backup_total

        return random.choices(candidates, weights=weights, k=1)[0]

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
