# -*- coding: utf-8 -*-
"""
config.py — Единый конфиг для всей платформы.

Все аккаунты, порты, таймауты, пути к БД — здесь.
"""
import os

# === Telegram API (общий для всех аккаунтов) ================================
API_ID = int(os.environ.get("TG_API_ID", 36091011))
API_HASH = os.environ.get("TG_API_HASH", "72fa475b3b4f5124b9f165672dca423b")

# === Пул аккаунтов ==========================================================
# Каждый аккаунт = один session-файл = один телеграм-юзер.
# priority: 1 — основной, 2+ — резервы. Чем меньше — тем приоритетнее.
# session: путь к .session файлу (без расширения), как в TelegramClient(session=...).
ACCOUNTS = [
    {"name": "main",     "session": "rumyantsev_create_chat", "priority": 1},
    # Раскомментируй и добавь реальные сессии:
    # {"name": "backup_1", "session": "rumyantsev_backup",     "priority": 2},
    # {"name": "backup_2", "session": "rumyantsev_backup_2",   "priority": 3},
    # {"name": "backup_3", "session": "rumyantsev_backup_3",   "priority": 4},
]

# === Порты (не менять — Make/n8n привязаны к ним) ============================
PORTS = {
    "create_chat": 5021,
    "send_text":   5022,
    "send_media":  5023,
    "leave_chat":  5024,
    "dashboard":   5099,
}

# === SQLite (реестр чатов, логи операций) ====================================
DB_PATH = os.environ.get("REGISTRY_DB", "chat_registry.db")

# === Retry / Reconnect ======================================================
MAX_RETRIES = 3
RETRY_DELAY = 2  # секунд между попытками

# === Кэш диалогов ===========================================================
CACHE_WARMUP_INTERVAL = 1800    # полный прогрев каждые 30 мин
MINI_REFRESH_COOLDOWN = 30      # мини-прогрев не чаще раз в 30 сек

# === FloodWait ===============================================================
FLOOD_WAIT_AUTO_SWITCH = 60     # если FloodWait > N сек, переключаем на резерв

# === Dashboard ===============================================================
DASHBOARD_USER = os.environ.get("MONITOR_USER", "admin")
DASHBOARD_PASS = os.environ.get("MONITOR_PASS", "telethon2026")

# === Logging =================================================================
LOG_LEVEL = os.environ.get("LOG_LEVEL", "INFO")
