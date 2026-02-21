# -*- coding: utf-8 -*-
"""
core/registry.py — ChatRegistry: SQLite-реестр привязки чатов к аккаунтам.

Таблицы:
  chat_assignments  — chat_id → account_name
  operations_log    — лог всех операций
  failover_log      — лог переключений аккаунтов
"""
import sqlite3
import time
import threading
import logging
from typing import Optional, List, Dict, Any

import config

logger = logging.getLogger("core.registry")


class ChatRegistry:
    """Thread-safe SQLite registry."""

    def __init__(self, db_path: Optional[str] = None):
        self._db_path = db_path or config.DB_PATH
        self._local = threading.local()
        self._init_db()

    # === Connection (per-thread) ==============================================

    def _get_conn(self) -> sqlite3.Connection:
        if not hasattr(self._local, "conn") or self._local.conn is None:
            self._local.conn = sqlite3.connect(self._db_path, timeout=10)
            self._local.conn.row_factory = sqlite3.Row
            self._local.conn.execute("PRAGMA journal_mode=WAL")
            self._local.conn.execute("PRAGMA busy_timeout=5000")
        return self._local.conn

    def _init_db(self):
        conn = self._get_conn()
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS chat_assignments (
                chat_id       TEXT PRIMARY KEY,
                account_name  TEXT NOT NULL,
                title         TEXT DEFAULT '',
                invite_link   TEXT DEFAULT '',
                created_at    REAL NOT NULL,
                status        TEXT DEFAULT 'active'
            );

            CREATE TABLE IF NOT EXISTS operations_log (
                id            INTEGER PRIMARY KEY AUTOINCREMENT,
                ts            REAL NOT NULL,
                account_name  TEXT NOT NULL,
                chat_id       TEXT DEFAULT '',
                operation     TEXT NOT NULL,
                status        TEXT NOT NULL,
                detail        TEXT DEFAULT ''
            );

            CREATE TABLE IF NOT EXISTS failover_log (
                id            INTEGER PRIMARY KEY AUTOINCREMENT,
                ts            REAL NOT NULL,
                chat_id       TEXT DEFAULT '',
                from_account  TEXT NOT NULL,
                to_account    TEXT NOT NULL,
                reason        TEXT DEFAULT ''
            );

            CREATE INDEX IF NOT EXISTS idx_ops_ts ON operations_log(ts);
            CREATE INDEX IF NOT EXISTS idx_ops_chat ON operations_log(chat_id);
            CREATE INDEX IF NOT EXISTS idx_fo_ts ON failover_log(ts);
        """)
        conn.commit()

    # === Chat Assignments =====================================================

    def assign(self, chat_id: str, account_name: str,
               title: str = "", invite_link: str = ""):
        conn = self._get_conn()
        conn.execute(
            """INSERT OR REPLACE INTO chat_assignments
               (chat_id, account_name, title, invite_link, created_at, status)
               VALUES (?, ?, ?, ?, ?, 'active')""",
            (str(chat_id), account_name, title, invite_link, time.time()),
        )
        conn.commit()
        logger.info("Assigned chat %s → account %s", chat_id, account_name)

    def get_account(self, chat_id: str) -> Optional[str]:
        conn = self._get_conn()
        row = conn.execute(
            "SELECT account_name FROM chat_assignments WHERE chat_id = ? AND status = 'active'",
            (str(chat_id),),
        ).fetchone()
        return row["account_name"] if row else None

    def update_account(self, chat_id: str, new_account: str):
        conn = self._get_conn()
        conn.execute(
            "UPDATE chat_assignments SET account_name = ? WHERE chat_id = ?",
            (new_account, str(chat_id)),
        )
        conn.commit()

    def mark_left(self, chat_id: str):
        conn = self._get_conn()
        conn.execute(
            "UPDATE chat_assignments SET status = 'left' WHERE chat_id = ?",
            (str(chat_id),),
        )
        conn.commit()

    def is_left(self, chat_id: str) -> bool:
        conn = self._get_conn()
        row = conn.execute(
            "SELECT status FROM chat_assignments WHERE chat_id = ?",
            (str(chat_id),),
        ).fetchone()
        return row is not None and row["status"] == "left"

    def get_all_assignments(self, limit: int = 200) -> List[Dict[str, Any]]:
        conn = self._get_conn()
        rows = conn.execute(
            "SELECT * FROM chat_assignments ORDER BY created_at DESC LIMIT ?",
            (limit,),
        ).fetchall()
        return [dict(r) for r in rows]

    def get_active_count(self) -> int:
        conn = self._get_conn()
        row = conn.execute(
            "SELECT COUNT(*) as cnt FROM chat_assignments WHERE status = 'active'"
        ).fetchone()
        return row["cnt"]

    def get_account_chat_counts(self) -> Dict[str, int]:
        """Количество активных чатов на каждый аккаунт."""
        conn = self._get_conn()
        rows = conn.execute(
            "SELECT account_name, COUNT(*) as cnt FROM chat_assignments "
            "WHERE status = 'active' GROUP BY account_name"
        ).fetchall()
        return {row["account_name"]: row["cnt"] for row in rows}

    # === Operations Log =======================================================

    def log_operation(self, account_name: str, chat_id: str,
                      operation: str, status: str, detail: str = ""):
        conn = self._get_conn()
        conn.execute(
            """INSERT INTO operations_log (ts, account_name, chat_id, operation, status, detail)
               VALUES (?, ?, ?, ?, ?, ?)""",
            (time.time(), account_name, str(chat_id), operation, status, detail),
        )
        conn.commit()

    def get_recent_operations(self, limit: int = 100) -> List[Dict[str, Any]]:
        conn = self._get_conn()
        rows = conn.execute(
            "SELECT * FROM operations_log ORDER BY ts DESC LIMIT ?",
            (limit,),
        ).fetchall()
        return [dict(r) for r in rows]

    # === Failover Log =========================================================

    def log_failover(self, chat_id: str, from_account: str,
                     to_account: str, reason: str = ""):
        conn = self._get_conn()
        conn.execute(
            """INSERT INTO failover_log (ts, chat_id, from_account, to_account, reason)
               VALUES (?, ?, ?, ?, ?)""",
            (time.time(), str(chat_id), from_account, to_account, reason),
        )
        conn.commit()
        logger.warning(
            "FAILOVER chat %s: %s → %s (reason: %s)",
            chat_id, from_account, to_account, reason,
        )

    def get_failover_log(self, limit: int = 50) -> List[Dict[str, Any]]:
        conn = self._get_conn()
        rows = conn.execute(
            "SELECT * FROM failover_log ORDER BY ts DESC LIMIT ?",
            (limit,),
        ).fetchall()
        return [dict(r) for r in rows]

    def get_last_active_times(self) -> Dict[str, float]:
        """Последняя успешная операция для каждого аккаунта (из operations_log)."""
        conn = self._get_conn()
        rows = conn.execute(
            "SELECT account_name, MAX(ts) as last_ts "
            "FROM operations_log WHERE status = 'ok' "
            "GROUP BY account_name"
        ).fetchall()
        return {row["account_name"]: row["last_ts"] for row in rows}

    # === Stats ================================================================

    def get_stats(self) -> Dict[str, Any]:
        conn = self._get_conn()
        active = conn.execute(
            "SELECT COUNT(*) as c FROM chat_assignments WHERE status='active'"
        ).fetchone()["c"]
        total_ops = conn.execute(
            "SELECT COUNT(*) as c FROM operations_log"
        ).fetchone()["c"]
        errors = conn.execute(
            "SELECT COUNT(*) as c FROM operations_log WHERE status='error'"
        ).fetchone()["c"]
        failovers = conn.execute(
            "SELECT COUNT(*) as c FROM failover_log"
        ).fetchone()["c"]
        return {
            "active_chats": active,
            "total_operations": total_ops,
            "total_errors": errors,
            "total_failovers": failovers,
        }

    # === Cleanup ==============================================================

    def cleanup_old_logs(self, days: int = 30):
        cutoff = time.time() - days * 86400
        conn = self._get_conn()
        conn.execute("DELETE FROM operations_log WHERE ts < ?", (cutoff,))
        conn.execute("DELETE FROM failover_log WHERE ts < ?", (cutoff,))
        conn.commit()
