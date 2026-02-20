# -*- coding: utf-8 -*-
"""
config.py — Единый конфиг для всей платформы.

Все аккаунты, порты, таймауты, пути к БД — здесь.
"""
import os

# === Пул аккаунтов ==========================================================
# Каждый аккаунт = один session-файл = один телеграм-юзер.
# У каждого аккаунта свои api_id / api_hash.
# priority: 1 — основной, 2+ — резервы. Чем меньше — тем приоритетнее.
# session: путь к .session файлу (без расширения), как в TelegramClient(session=...).
# ВАЖНО: имена session-файлов нужно уточнить на сервере (ls ~/*.session).
ACCOUNTS = [
    {
        "name": "main",
        "session": "rumyantsev_create_chat",
        "api_id": 36091011,
        "api_hash": "72fa475b3b4f5124b9f165672dca423b",
        "phone": "+79808625417",
        "username": "rumyancev_alex",
        "priority": 1,
    },
    {
        "name": "backup_1",
        "session": "rumPRodar",
        "api_id": 30517734,
        "api_hash": "3f7c45927d1eadc9bb8c1d2117eda432",
        "phone": "+905053544048",
        "username": "rumPRodar",
        "priority": 2,
    },
    {
        "name": "backup_2",
        "session": "aleksrumi",
        "api_id": 36215511,
        "api_hash": "d48299050413bf020ec911bf74f7bf56",
        "phone": "+18177669809",
        "username": "aleksrumi",
        "priority": 3,
    },
    {
        "name": "backup_3",
        "session": "ProdarAl",
        "api_id": 38343394,
        "api_hash": "a211f75e849a77558ca4fe54b41b2b2b",
        "phone": "+99362724797",
        "username": "ProdarAl",
        "priority": 4,
    },
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
