# Полное саммари: Репо + Сервер

**Дата аудита:** 2026-02-20
**Сервер:** root@wfoxxidthq

---

## РЕПО — что внутри

### Архитектура

Репо содержит **полностью переписанную платформу**. Вместо 8 отдельных standalone-скриптов (каждый — свой Flask + свой TelegramClient) — **один процесс `app.py`**, который:

- Запускает единый asyncio event loop в фоновом потоке
- Создаёт пул TelegramClient'ов (bridge) для каждой пары "аккаунт + сервис"
- Поднимает 4 Flask-сервера на портах 5021-5024 + дашборд на 5099
- Автоматически выбирает аккаунт по приоритету и состоянию здоровья
- При флуде/бане — failover на резервный аккаунт
- Ведёт SQLite-реестр: какой чат за каким аккаунтом закреплён

### Структура файлов

```
app.py                          — Точка входа, запуск всего
config.py                       — Все аккаунты, порты, таймауты
core/
  bridge.py                     — TelethonBridge: обёртка над одним клиентом
  pool.py                       — AccountPool: управление пулом bridge'ей
  registry.py                   — ChatRegistry: SQLite БД привязок чатов
  router.py                     — AccountRouter: выбор аккаунта + failover
  retry.py                      — Retry/reconnect логика
services/
  create_chat.py                — POST /create_chat (порт 5021)
  send_text.py                  — POST /send_text (порт 5022)
  send_media.py                 — POST /send_media (порт 5023)
  leave_chat.py                 — POST /leave_chat (порт 5024)
dashboard/                      — Встроенный веб-дашборд (порт 5099)
monitor/                        — Старый отдельный монитор (legacy)
*_rumyantsev_webhook.py (4шт)   — Старые standalone-скрипты (для справки)
```

### 4 аккаунта в config.py

| # | Имя | API_ID | Телефон | Username | Приоритет |
|---|---|---|---|---|---|
| 1 | main | 36091011 | +79808625417 | @rumyancev_alex | 1 (основной) |
| 2 | backup_1 | 30517734 | +905053544048 | @rumPRodar | 2 |
| 3 | backup_2 | 36215511 | +18177669809 | @aleksrumi | 3 |
| 4 | backup_3 | 38343394 | +99362724797 | @ProdarAl | 4 |

### 5 портов

| Порт | Сервис | Эндпоинты |
|---|---|---|
| 5021 | create_chat | `POST /create_chat` |
| 5022 | send_text | `POST /send_text`, `GET /health`, `GET /stats`, `POST /reload_cache` |
| 5023 | send_media | `POST /send_media`, `GET /health`, `GET /stats`, `POST /reload_cache` |
| 5024 | leave_chat | `POST /leave_chat`, `GET /health` |
| 5099 | dashboard | Веб-интерфейс (admin/telethon2026) |

### Ключевые фичи новой платформы

- **Автоматический failover** — если основной аккаунт во flood wait или забанен, запрос идёт на резервный
- **SQLite-реестр** — чат привязывается к аккаунту при создании, дальнейшие операции идут через тот же аккаунт
- **Кэш диалогов** — полный прогрев при старте, обновление каждые 30 мин, мини-refresh на промах
- **`catch_up=False`** — убирает PersistentTimestampOutdatedError
- **Встроенный дашборд** — статусы всех bridge'ей, логи операций, failover-логи

### Проблемы, найденные в репо (и исправленные)

1. **Не было requirements.txt** — создан
2. **config.py содержал 16 сессий, 9 из которых не существуют на сервере** — убраны несуществующие, оставлены только подтверждённые
3. **Нет deploy.sh для основной платформы** — `deploy.sh` в репо только для монитора
4. **Нет systemd unit-файла** — нужно создать на сервере (шаблон в DEPLOYMENT_PLAN.md)
5. **Относительные пути к сессиям** — `TelegramClient("rumyantsev_create_chat", ...)` ищет файл относительно CWD, поэтому запускать нужно из `/root/`

---

## СЕРВЕР — что на нём

### Полная карта процессов Rumyantsev

| Порт | Скрипт | Аккаунт | API_ID | Сессия | Как запущен |
|---|---|---|---|---|---|
| **5021** | **ПУСТО** | — | — | — | — |
| 5022 | `send_text_rumyantsev_webhook` | Main RU | 36091011 | `rumyantsev_send_text` | **systemd** (`send-text-rumyantsev.service`) |
| 5023 | `send_media_rumyantsev_webhook` | Main RU | 36091011 | `rumuantsev_media` | **systemd** (`send-media-rumyantsev.service`) |
| 5024 | `leave_chat_rumyantsev_webhook` | Main RU | 36091011 | `rumyantsev_leave` | orphaned gunicorn (с Feb06!) |
| 5025 | `create_chat_2_rumyantsev_webhook` | TR | 30517734 | `rum_create_chat_2` | orphaned gunicorn |
| 5028 | `leave_chat_2_rumyantsev_webhook` | **???** | **32292929** | `rumyantsev_leave_2` | orphaned gunicorn |
| 5029 | `create_chat_3_rumyantsev_webhook` | US | 36215511 | `rum_create_chat_3` | orphaned gunicorn |
| 5030 | `create_chat_4_rumyantsev_webhook` | TM | 38343394 | `rum_create_chat_4` | orphaned gunicorn |
| 5099 | `PROtehnik/dashboard_server.py` | — | — | — | orphaned python3 |

### Прочие процессы (НЕ rumyantsev, не трогаем)

| Порт | Что |
|---|---|
| 5000 | неизвестный python |
| 5020 | `leave_ivan:app` (другой проект) |
| 5031, 5034, 5035, 5036 | `create_one_chat_*_webhook` (другой проект) |

### Скрипты на сервере (все в `/root/`)

| Файл | API_ID | Запущен? |
|---|---|---|
| `create_chat_rumyantsev_webhook.py` | 36091011 | **НЕТ** (порт 5021 пуст) |
| `send_text_rumyantsev_webhook.py` | 36091011 | ДА (5022, systemd) |
| `send_media_rumyantsev_webhook.py` | 36091011 | ДА (5023, systemd) |
| `leave_chat_rumyantsev_webhook.py` | 36091011 | ДА (5024) |
| `create_chat_2_rumyantsev_webhook.py` | 30517734 | ДА (5025) |
| `create_chat_3_rumyantsev_webhook.py` | 36215511 | ДА (5029) |
| `create_chat_4_rumyantsev_webhook.py` | 38343394 | ДА (5030) |
| `create_chat_5_rumyantsev_webhook.py` | 36215511 | **НЕТ** |
| `leave_chat_2_rumyantsev_webhook.py` | **32292929** | ДА (5028) |
| `send_text_2_rumyantsev_webhook.py` | **32292929** | **НЕТ** |
| `send_media_2_rumyantsev_webhook.py` | **32292929?** | **НЕТ** |

### Systemd-сервисы

| Сервис | Статус |
|---|---|
| `send-text-rumyantsev.service` | ✅ active, running (gunicorn + gevent, WorkingDirectory=/root) |
| `send-media-rumyantsev.service` | ✅ active, running (gunicorn + gevent, WorkingDirectory=/root) |
| `telethon-monitor.service` | ❌ **crash loop** — порт 5099 занят PROtehnik, 111+ рестартов |

### Session-файлы: что есть, а чего нет

**Нужны для новой платформы (7 штук) — все есть:**

| Сессия | Размер | Аккаунт |
|---|---|---|
| `rumyantsev_create_chat.session` | 978KB | main |
| `rumyantsev_send_text.session` | 1093KB | main |
| `rumuantsev_media.session` | 1064KB | main |
| `rumyantsev_leave.session` | 946KB | main |
| `rum_create_chat_2.session` | 159KB | backup_1 TR |
| `rum_create_chat_3.session` | 774KB | backup_2 US |
| `rum_create_chat_4.session` | 45KB | backup_3 TM |

**Были в config.py, но НЕ существуют (9 штук) — удалены из конфига:**

`rum_send_text_2`, `rum_media_2`, `rum_leave_2`, `rum_send_text_3`, `rum_media_3`, `rum_leave_3`, `rum_send_text_4`, `rum_media_4`, `rum_leave_4`

**Есть на сервере, но с другим API_ID (32292929, не в нашей платформе):**

`rumyantsev_send_text_2.session`, `rumuantsev_media_2.session`, `rumyantsev_leave_2.session`

**Есть на сервере с паттерном `main_*`/`backup_*` — от предыдущей попытки деплоя:**

`main_create_chat`, `main_send_text`, `main_send_media`, `main_leave`, `backup_create_chat`, `backup_send_text`, и т.д. — неизвестно каким API_ID авторизованы.

### Зависимости (venv на сервере)

Всё необходимое установлено: Flask 2.2.5, Telethon 1.41.2, Werkzeug 3.1.3, gunicorn 23.0.0, gevent 25.9.1.

### NPM (Nginx Proxy Manager)

| Домен | Куда проксирует |
|---|---|
| `rumyantsevdash.other-digital.ru` | `172.17.0.1:5099` (наш дашборд) |
| `n8n.other-digital.ru` | `217.114.3.145:5678` |
| `npm.other-digital.ru` | `nginx_proxy_manager:81` |
| `portainer.other-digital.ru` | `portainer:9443` |
| `dashvps.other-digital.ru` | `dashboard:5555` |
| `webhooks.other-digital.ru` | `172.17.0.1:6000` |

Webhook-скрипты (5022-5030) вызываются напрямую по IP:PORT, не через NPM.

---

## КЛЮЧЕВЫЕ РАСХОЖДЕНИЯ РЕПО vs СЕРВЕР

### 1. Порты create_chat — полное несовпадение

**Репо:** Один порт 5021 для ВСЕХ create_chat, платформа сама выбирает аккаунт.
**Сервер:** 3 отдельных порта — 5025 (TR), 5029 (US), 5030 (TM), n8n явно выбирает аккаунт по порту.
**Порт 5021 свободен** — create_chat основного аккаунта вообще не запущен.

### 2. 5-й аккаунт (API_ID 32292929) — не мигрирован

На сервере есть 3 скрипта с этим API_ID (`leave_chat_2`, `send_text_2`, `send_media_2`). В новой платформе этого аккаунта нет вообще. `leave_chat_2` запущен на порту 5028.

### 3. Способ запуска — полная разница

**Репо:** `python app.py` — один процесс, werkzeug.serving, dev-сервер.
**Сервер:** gunicorn + gevent per-script, systemd для send_text/send_media, остальные orphaned.

### 4. Осиротевшие процессы

На сервере висят gunicorn master-процессы с **6 февраля** (PID 804037, 804129, 804253, 804366, 804497) — 14 дней. Рядом с ними работают свежие worker-процессы. Это мусор, который нужно убить.

---

## ЧТО СДЕЛАНО В ЭТОМ КОММИТЕ

1. **`config.py`** — убраны 9 несуществующих сессий у backup-аккаунтов (без этого платформа зависнет при старте)
2. **`requirements.txt`** — создан для основной платформы
3. **`DEPLOYMENT_PLAN.md`** — полный отчёт: таблицы сравнения, риски, пошаговые copy-paste команды для деплоя и отката
4. **`SUMMARY.md`** — этот файл

---

## НЕРЕШЁННЫЕ ВОПРОСЫ

1. **Что делать с портами 5025/5029/5030?** Новая платформа принимает всё на 5021. Нужна перенастройка n8n — или оставить старые скрипты параллельно?
2. **Кому принадлежит API_ID 32292929?** Это 5-й аккаунт, не описанный нигде. Нужен ли он?
3. **Нужен ли create_chat_5 (five_akk_rum)?** Не запущен, но сессия живая.
