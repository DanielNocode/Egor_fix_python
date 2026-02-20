# -*- coding: utf-8 -*-
"""
core/pool.py — AccountPool: управление пулом Telegram-аккаунтов.
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
    Один bridge = один Telegram-аккаунт.
    """

    def __init__(self, loop: asyncio.AbstractEventLoop):
        self._loop = loop
        self.bridges: Dict[str, TelethonBridge] = {}
        self._sorted_names: List[str] = []  # по приоритету

    # === Lifecycle ============================================================

    async def start_all(self):
        """Создаём и запускаем bridge'и для каждого аккаунта из конфига."""
        for acc in sorted(config.ACCOUNTS, key=lambda a: a["priority"]):
            name = acc["name"]
            bridge = TelethonBridge(
                name=name,
                session=acc["session"],
                priority=acc["priority"],
                loop=self._loop,
            )
            self.bridges[name] = bridge
            self._sorted_names.append(name)
            try:
                await bridge.start()
                # Запускаем периодический прогрев кэша
                self._loop.create_task(bridge.periodic_warmup())
            except Exception as e:
                logger.error("Failed to start bridge %s: %s", name, e)
                # Не крашим — остальные аккаунты пусть стартуют

        healthy = [n for n in self._sorted_names if self.bridges[n].is_healthy]
        logger.info(
            "AccountPool started: %d/%d healthy",
            len(healthy), len(self.bridges),
        )

    async def stop_all(self):
        for bridge in self.bridges.values():
            await bridge.stop()

    # === Выбор аккаунта =======================================================

    def get(self, name: str) -> Optional[TelethonBridge]:
        return self.bridges.get(name)

    def get_best(self) -> Optional[TelethonBridge]:
        """Вернуть самый приоритетный здоровый bridge."""
        for name in self._sorted_names:
            bridge = self.bridges[name]
            if bridge.is_healthy:
                return bridge
        return None

    def get_healthy_list(self) -> List[TelethonBridge]:
        """Все здоровые bridge'и, отсортированные по приоритету."""
        return [self.bridges[n] for n in self._sorted_names if self.bridges[n].is_healthy]

    def get_next_healthy(self, exclude_name: str) -> Optional[TelethonBridge]:
        """Следующий здоровый bridge, кроме указанного."""
        for name in self._sorted_names:
            if name == exclude_name:
                continue
            bridge = self.bridges[name]
            if bridge.is_healthy:
                return bridge
        return None

    # === Информация ===========================================================

    def all_statuses(self) -> List[dict]:
        return [self.bridges[n].to_dict() for n in self._sorted_names]

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
