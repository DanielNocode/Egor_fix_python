# -*- coding: utf-8 -*-
"""
core/router.py — AccountRouter: выбор аккаунта + failover + балансировка.

Логика:
  1. create_chat  → weighted-balanced: вероятность обратна загрузке
  2. send_text / send_media / leave_chat → привязанный аккаунт (из registry),
     если нездоров → failover на least-loaded
     если привязки нет → least-loaded
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
    """Роутер: связывает pool + registry. Балансировка по числу чатов."""

    def __init__(self, pool: AccountPool, registry: ChatRegistry):
        self.pool = pool
        self.registry = registry

    def _pick_least_loaded(self, service: str,
                           exclude_key: str = "") -> Optional[TelethonBridge]:
        """Выбрать здоровый bridge с наименьшим количеством активных чатов."""
        counts = self.registry.get_account_chat_counts()
        return self.pool.get_least_loaded(service, counts, exclude_key)

    def _pick_weighted(self, service: str,
                       exclude_key: str = "") -> Optional[TelethonBridge]:
        """Взвешенный выбор: менее загруженные получают больше, но не 100%."""
        counts = self.registry.get_account_chat_counts()
        return self.pool.get_weighted_balanced(service, counts, exclude_key)

    # === Для create_chat ======================================================

    def pick_for_create(self, service: str = "create_chat") -> TelethonBridge:
        """Выбрать bridge взвешенным методом для создания чата."""
        bridge = self._pick_weighted(service)
        if bridge is None:
            raise RuntimeError(f"No healthy accounts for service={service}")
        logger.info(
            "Weighted pick for %s → %s (account=%s)",
            service, bridge.name, bridge.account_name,
        )
        return bridge

    # === Для send_text / send_media / leave_chat ==============================

    def pick_for_chat(self, chat_id, service: str) -> TelethonBridge:
        """
        Выбрать bridge для операции с чатом.
        1. Ищем привязку chat_id → account_name
        2. Берём bridge этого аккаунта для нужного сервиса
        3. Если нездоров → failover на least-loaded bridge того же сервиса
        4. Если привязки нет → least-loaded bridge для сервиса
        """
        chat_str = str(chat_id)
        assigned_account = self.registry.get_account(chat_str)

        if assigned_account:
            bridge = self.pool.get_by_account(assigned_account, service)
            if bridge and bridge.is_healthy:
                return bridge

            # Failover — берём least-loaded вместо просто "следующего"
            current_key = f"{assigned_account}:{service}"
            reason = "no bridge" if not bridge else f"status={bridge.status}"
            new_bridge = self._pick_least_loaded(service, exclude_key=current_key)
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

        # Нет привязки — least-loaded
        bridge = self._pick_least_loaded(service)
        if bridge is None:
            raise RuntimeError(f"No healthy accounts for service={service}")
        return bridge

    # === Для send_media (по user_id / username, без chat_id) ==================

    def pick_for_recipient(self, service: str = "send_media",
                           user_id=None, username=None) -> TelethonBridge:
        """
        Для отправки медиа — может быть как группа, так и личка.
        Если user_id есть в реестре чатов → используем привязанный аккаунт.
        Иначе → least-loaded bridge для сервиса.
        """
        if user_id is not None:
            chat_str = str(user_id)
            assigned = self.registry.get_account(chat_str)
            if assigned:
                bridge = self.pool.get_by_account(assigned, service)
                if bridge and bridge.is_healthy:
                    return bridge
                # Failover на least-loaded
                current_key = f"{assigned}:{service}"
                new_bridge = self._pick_least_loaded(
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

        bridge = self._pick_least_loaded(service)
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
