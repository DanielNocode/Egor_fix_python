# -*- coding: utf-8 -*-
"""
config.py — Единый конфиг для всей платформы.

Все аккаунты, порты, таймауты, пути к БД — здесь.
"""
import os

# === Пул аккаунтов ==========================================================
# Каждый аккаунт = один телеграм-юзер с api_id / api_hash.
# priority: 1 — основной, 2+ — резервы. Чем меньше — тем приоритетнее.
# sessions: словарь {service_name: session_file} — у каждого скрипта СВОЯ сессия.
#   Это критически важно: Telethon лочит .session файл, поэтому нельзя
#   шарить одну сессию между несколькими скриптами/bridge'ами.
# Если у аккаунта нет сессии для сервиса — он для этого сервиса не используется.
ACCOUNTS = [
    {
        "name": "main",
        "api_id": 36091011,
        "api_hash": "72fa475b3b4f5124b9f165672dca423b",
        "phone": "+79808625417",
        "username": "rumyancev_alex",
        "priority": 1,
        "sessions": {
            "create_chat": "rumyantsev_create_chat",
            "send_media":  "rumuantsev_media",
            "send_text":   "rumyantsev_send_text",
            "leave_chat":  "rumyantsev_leave",
        },
    },
    {
        "name": "backup_1",
        "api_id": 30517734,
        "api_hash": "3f7c45927d1eadc9bb8c1d2117eda432",
        "phone": "+905053544048",
        "username": "rumPRodar",
        "priority": 2,
        "sessions": {
            "create_chat": "rum_create_chat_2",
            "send_text":   "rum_send_text_2",
            "send_media":  "rum_media_2",
            "leave_chat":  "rum_leave_2",
        },
    },
    {
        "name": "backup_2",
        "api_id": 36215511,
        "api_hash": "d48299050413bf020ec911bf74f7bf56",
        "phone": "+18177669809",
        "username": "aleksrumi",
        "priority": 3,
        "sessions": {
            "create_chat": "rum_create_chat_3",
            "send_text":   "rum_send_text_3",
            "send_media":  "rum_media_3",
            "leave_chat":  "rum_leave_3",
        },
    },
    {
        "name": "backup_3",
        "api_id": 38343394,
        "api_hash": "a211f75e849a77558ca4fe54b41b2b2b",
        "phone": "+99362724797",
        "username": "ProdarAl",
        "priority": 4,
        "sessions": {
            "create_chat": "rum_create_chat_4",
            "send_text":   "rum_send_text_4",
            "send_media":  "rum_media_4",
            "leave_chat":  "rum_leave_4",
        },
    },
]

# Все типы сервисов
SERVICE_TYPES = ["create_chat", "send_text", "send_media", "leave_chat"]

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

# === AMO CRM Observer ========================================================
# Этот аккаунт добавляется во ВСЕ чаты (даже созданные бэкапами),
# чтобы AmoCRM видела переписки.
AMO_OBSERVER_USERNAME = "@rumyancev_alex"

# === Salebot Callback ========================================================
SALEBOT_CALLBACK_URL = os.environ.get(
    "SALEBOT_CALLBACK_URL",
    "https://chatter.salebot.pro/api/17fb55a49883fb26bef73b6429fc4cf1/tg_callback",
)
SALEBOT_GROUP_ID = os.environ.get("SALEBOT_GROUP_ID", "alex_rumhelp_bot")

# === Bot API Fallback ========================================================
# Токен бота @alex_rumhelp_bot — используется как fallback для отправки
# сообщений, когда все Telethon-аккаунты недоступны (бан, FloodWait и т.д.)
BOT_TOKEN = os.environ.get("BOT_TOKEN", "8509333133:AAGYhLFHc1YYl5uyLB1gui5rDHzkYOE0nS4")

# === Logging =================================================================
LOG_LEVEL = os.environ.get("LOG_LEVEL", "INFO")
