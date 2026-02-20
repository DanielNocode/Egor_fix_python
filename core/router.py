# -*- coding: utf-8 -*-
"""
core/router.py — AccountRouter: выбор аккаунта + failover.

Логика:
  1. create_chat  → берём лучший свободный bridge для сервиса create_chat
  2. send_text / send_media / leave_chat → ищем привязанный аккаунт,
     берём его bridge для нужного сервиса
     → если он нездоров → failover на следующий bridge того же сервиса
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
    """Роутер: связывает pool + registry. Все методы принимают service."""

    def __init__(self, pool: AccountPool, registry: ChatRegistry):
        self.pool = pool
        self.registry = registry

    # === Для create_chat ======================================================

    def pick_for_create(self, service: str = "create_chat") -> TelethonBridge:
        """Выбрать лучший здоровый bridge для создания чата."""
        bridge = self.pool.get_best(service)
        if bridge is None:
            raise RuntimeError(f"No healthy accounts for service={service}")
        return bridge

    # === Для send_text / send_media / leave_chat ==============================

    def pick_for_chat(self, chat_id, service: str) -> TelethonBridge:
        """
        Выбрать bridge для операции с чатом.
        1. Ищем привязку chat_id → account_name
        2. Берём bridge этого аккаунта для нужного сервиса
        3. Если нездоров → failover на другой bridge того же сервиса
        4. Если привязки нет → берём лучший доступный bridge для сервиса
        """
        chat_str = str(chat_id)
        assigned_account = self.registry.get_account(chat_str)

        if assigned_account:
            bridge = self.pool.get_by_account(assigned_account, service)
            if bridge and bridge.is_healthy:
                return bridge

            # Failover внутри того же сервиса
            current_key = f"{assigned_account}:{service}"
            reason = "no bridge" if not bridge else f"status={bridge.status}"
            new_bridge = self.pool.get_next_healthy(service, exclude_key=current_key)
            if new_bridge is None:
                # Даже если нездоров — пробуем привязанный
                if bridge:
                    return bridge
                raise RuntimeError(
                    f"No accounts for chat {chat_id}, service={service}"
                )

            self.registry.log_failover(
                chat_str, assigned_account, new_bridge.account_name, reason,
            )
            self.registry.update_account(chat_str, new_bridge.account_name)
            logger.warning(
                "Failover for chat %s [%s]: %s → %s (%s)",
                chat_id, service, assigned_account, new_bridge.account_name, reason,
            )
            return new_bridge

        # Нет привязки — берём лучший для сервиса
        bridge = self.pool.get_best(service)
        if bridge is None:
            raise RuntimeError(f"No healthy accounts for service={service}")
        return bridge

    # === Для send_media (по user_id / username, без chat_id) ==================

    def pick_for_recipient(self, service: str = "send_media",
                           user_id=None, username=None) -> TelethonBridge:
        """
        Для отправки медиа — может быть как группа, так и личка.
        Если user_id есть в реестре чатов → используем привязанный аккаунт.
        Иначе → лучший доступный bridge для сервиса.
        """
        if user_id is not None:
            chat_str = str(user_id)
            assigned = self.registry.get_account(chat_str)
            if assigned:
                bridge = self.pool.get_by_account(assigned, service)
                if bridge and bridge.is_healthy:
                    return bridge
                # Failover
                current_key = f"{assigned}:{service}"
                new_bridge = self.pool.get_next_healthy(
                    service, exclude_key=current_key,
                )
                if new_bridge:
                    self.registry.log_failover(
                        chat_str, assigned, new_bridge.account_name,
                        "recipient failover",
                    )
                    self.registry.update_account(chat_str, new_bridge.account_name)
                    return new_bridge
                if bridge:
                    return bridge

        bridge = self.pool.get_best(service)
        if bridge is None:
            raise RuntimeError(f"No healthy accounts for service={service}")
        return bridge

    # === Error handling ========================================================

    def handle_error(self, bridge: TelethonBridge, error: Exception,
                     chat_id: str = "", operation: str = ""):
        if is_flood_wait(error):
            secs = flood_wait_seconds(error)
            bridge.mark_flood(secs)
            self.registry.log_operation(
                bridge.account_name, chat_id, operation, "flood_wait",
                detail=f"FloodWait {secs}s",
            )
        elif "banned" in str(error).lower() or "deactivated" in str(error).lower():
            bridge.mark_banned()
            self.registry.log_operation(
                bridge.account_name, chat_id, operation, "banned",
                detail=str(error),
            )
        else:
            bridge.mark_error(str(error))
            self.registry.log_operation(
                bridge.account_name, chat_id, operation, "error",
                detail=str(error),
            )

    def handle_success(self, bridge: TelethonBridge,
                       chat_id: str = "", operation: str = ""):
        bridge.mark_success()
        self.registry.log_operation(
            bridge.account_name, chat_id, operation, "ok",
        )
