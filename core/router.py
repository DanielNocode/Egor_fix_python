# -*- coding: utf-8 -*-
"""
core/router.py — AccountRouter: выбор аккаунта + failover.

Логика:
  1. create_chat  → берём лучший свободный аккаунт
  2. send_text / send_media / leave_chat → ищем привязанный аккаунт
     → если он нездоров → failover на следующий по приоритету
"""
import logging
from typing import Optional

from core.bridge import TelethonBridge
from core.pool import AccountPool
from core.registry import ChatRegistry
from core.retry import is_flood_wait, flood_wait_seconds

import config

logger = logging.getLogger("core.router")


class AccountRouter:
    """Роутер: связывает pool + registry."""

    def __init__(self, pool: AccountPool, registry: ChatRegistry):
        self.pool = pool
        self.registry = registry

    # === Для create_chat ======================================================

    def pick_for_create(self) -> TelethonBridge:
        """Выбрать лучший здоровый аккаунт для создания чата."""
        bridge = self.pool.get_best()
        if bridge is None:
            raise RuntimeError("No healthy accounts available")
        return bridge

    # === Для send_text / send_media / leave_chat ==============================

    def pick_for_chat(self, chat_id) -> TelethonBridge:
        """
        Выбрать аккаунт для операции с чатом.
        1. Ищем привязку chat_id → account
        2. Если привязанный аккаунт здоров → возвращаем его
        3. Если нет → failover
        4. Если привязки нет → берём лучший доступный
        """
        chat_str = str(chat_id)
        assigned = self.registry.get_account(chat_str)

        if assigned:
            bridge = self.pool.get(assigned)
            if bridge and bridge.is_healthy:
                return bridge

            # Failover
            reason = "not found" if not bridge else f"status={bridge.status}"
            new_bridge = self.pool.get_next_healthy(exclude_name=assigned)
            if new_bridge is None:
                # Даже если нездоров — пробуем привязанный
                if bridge:
                    return bridge
                raise RuntimeError(f"No accounts available for chat {chat_id}")

            self.registry.log_failover(
                chat_str, assigned, new_bridge.name, reason,
            )
            self.registry.update_account(chat_str, new_bridge.name)
            logger.warning(
                "Failover for chat %s: %s → %s (%s)",
                chat_id, assigned, new_bridge.name, reason,
            )
            return new_bridge

        # Нет привязки — берём лучший
        bridge = self.pool.get_best()
        if bridge is None:
            raise RuntimeError("No healthy accounts available")
        return bridge

    # === Для send_media (по user_id / username, без chat_id) ==================

    def pick_for_recipient(self, user_id=None, username=None) -> TelethonBridge:
        """
        Для отправки медиа — может быть как группа, так и личка.
        Если user_id есть в реестре чатов → используем привязанный аккаунт.
        Иначе → лучший доступный.
        """
        if user_id is not None:
            chat_str = str(user_id)
            assigned = self.registry.get_account(chat_str)
            if assigned:
                bridge = self.pool.get(assigned)
                if bridge and bridge.is_healthy:
                    return bridge
                # Failover
                new_bridge = self.pool.get_next_healthy(
                    exclude_name=assigned or "",
                )
                if new_bridge:
                    self.registry.log_failover(
                        chat_str, assigned or "?", new_bridge.name,
                        "recipient failover",
                    )
                    self.registry.update_account(chat_str, new_bridge.name)
                    return new_bridge
                if bridge:
                    return bridge

        bridge = self.pool.get_best()
        if bridge is None:
            raise RuntimeError("No healthy accounts available")
        return bridge

    # === Error handling ========================================================

    def handle_error(self, bridge: TelethonBridge, error: Exception,
                     chat_id: str = "", operation: str = ""):
        """
        Обработать ошибку операции: обновить здоровье аккаунта,
        записать в лог.
        """
        if is_flood_wait(error):
            secs = flood_wait_seconds(error)
            bridge.mark_flood(secs)
            self.registry.log_operation(
                bridge.name, chat_id, operation, "flood_wait",
                detail=f"FloodWait {secs}s",
            )
        elif "banned" in str(error).lower() or "deactivated" in str(error).lower():
            bridge.mark_banned()
            self.registry.log_operation(
                bridge.name, chat_id, operation, "banned",
                detail=str(error),
            )
        else:
            bridge.mark_error(str(error))
            self.registry.log_operation(
                bridge.name, chat_id, operation, "error",
                detail=str(error),
            )

    def handle_success(self, bridge: TelethonBridge,
                       chat_id: str = "", operation: str = ""):
        bridge.mark_success()
        self.registry.log_operation(
            bridge.name, chat_id, operation, "ok",
        )
