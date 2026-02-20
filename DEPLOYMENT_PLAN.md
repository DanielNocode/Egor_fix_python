# Deployment Plan: Rumyantsev Unified Telethon Platform

**Дата:** 2026-02-20
**Сервер:** root@wfoxxidthq
**Репо:** Egor_fix_python

---

## 1. СТАТУС РЕПО

### Вердикт: НЕ ГОТОВО к деплою as-is. Требуются доработки.

**Критические проблемы (блокеры):**

| # | Проблема | Влияние |
|---|---|---|
| 1 | **12 из 16 session-файлов не существуют** | `TelegramClient.start()` повиснет, ожидая интерактивную авторизацию — процесс зависнет навсегда |
| 2 | **Нет requirements.txt** для основной платформы | Непонятно какие зависимости ставить |
| 3 | **Консолидация портов: было 7 портов → стало 4** | n8n/Make вызывает конкретные порты для разных аккаунтов — нужна перенастройка |
| 4 | **5-й аккаунт (API_ID 32292929) не в config.py** | Скрипты `leave_chat_2`, `send_text_2`, `send_media_2` используют аккаунт, которого нет в новой платформе |
| 5 | **Скрипт `create_chat_5` (five_akk_rum) отброшен** | Если используется n8n — потеряется функционал |

---

## 2. ПОЛНАЯ КАРТА СЕРВЕРА

### 2.1 Занятые порты (Rumyantsev-скрипты)

| Порт | Скрипт | Аккаунт | API_ID | Сессия | Запуск |
|---|---|---|---|---|---|
| 5021 | **СВОБОДЕН** | — | — | — | — |
| 5022 | `send_text_rumyantsev_webhook` | Main RU | 36091011 | `rumyantsev_send_text` | **systemd** |
| 5023 | `send_media_rumyantsev_webhook` | Main RU | 36091011 | `rumuantsev_media` | **systemd** |
| 5024 | `leave_chat_rumyantsev_webhook` | Main RU | 36091011 | `rumyantsev_leave` | orphaned gunicorn |
| 5025 | `create_chat_2_rumyantsev_webhook` | TR backup_1 | 30517734 | `rum_create_chat_2` | orphaned gunicorn |
| 5028 | `leave_chat_2_rumyantsev_webhook` | **НЕИЗВЕСТНЫЙ** | **32292929** | `rumyantsev_leave_2` | orphaned gunicorn |
| 5029 | `create_chat_3_rumyantsev_webhook` | US backup_2 | 36215511 | `rum_create_chat_3` | orphaned gunicorn |
| 5030 | `create_chat_4_rumyantsev_webhook` | TM backup_3 | 38343394 | `rum_create_chat_4` | orphaned gunicorn |
| 5099 | `/root/PROtehnik/dashboard_server.py` | Дашборд (наш) | — | — | orphaned python3 |

### Другие порты (НЕ rumyantsev, не трогаем):

| Порт | Скрипт |
|---|---|
| 5000 | неизвестный python |
| 5020 | `leave_ivan:app` (другой проект) |
| 5031 | `create_one_chat_4_webhook` (другой проект) |
| 5034 | `create_one_chat_6_webhook` (другой проект) |
| 5035 | `create_one_chat_7_webhook` (другой проект) |
| 5036 | `create_one_chat_8_webhook` (другой проект) |

### 2.2 Systemd-сервисы

| Сервис | Статус | Примечание |
|---|---|---|
| `send-text-rumyantsev.service` | active, running | WorkingDirectory=/root, gunicorn с gevent |
| `send-media-rumyantsev.service` | active, running | WorkingDirectory=/root, gunicorn с gevent |
| `telethon-monitor.service` | **crash loop** | Порт 5099 занят PROtehnik dashboard, бесконечный restart |

### 2.3 Скрипты на сервере

Все в `/root/`:

| Файл | API_ID | Сессия | Порт (gunicorn) | Запущен? |
|---|---|---|---|---|
| `create_chat_rumyantsev_webhook.py` | 36091011 | `rumyantsev_create_chat` | был 5021 | **НЕТ** |
| `send_text_rumyantsev_webhook.py` | 36091011 | `rumyantsev_send_text` | 5022 | ДА (systemd) |
| `send_media_rumyantsev_webhook.py` | 36091011 | `rumuantsev_media` | 5023 | ДА (systemd) |
| `leave_chat_rumyantsev_webhook.py` | 36091011 | `rumyantsev_leave` | 5024 | ДА |
| `create_chat_2_rumyantsev_webhook.py` | 30517734 | `rum_create_chat_2` | 5025 | ДА |
| `create_chat_3_rumyantsev_webhook.py` | 36215511 | `rum_create_chat_3` | 5029 | ДА |
| `create_chat_4_rumyantsev_webhook.py` | 38343394 | `rum_create_chat_4` | 5030 | ДА |
| `create_chat_5_rumyantsev_webhook.py` | 36215511 | `five_akk_rum` | ? | **НЕТ** |
| `send_text_2_rumyantsev_webhook.py` | **32292929** | `rumyantsev_send_text_2` | ? | **НЕТ** |
| `send_media_2_rumyantsev_webhook.py` | **32292929?** | ? | ? | **НЕТ** |
| `leave_chat_2_rumyantsev_webhook.py` | **32292929** | `rumyantsev_leave_2` | 5028 | ДА |

---

## 3. ТАБЛИЦА СРАВНЕНИЯ: РЕПО vs СЕРВЕР

### 3.1 Порты

| Сервис | Репо (новое) | Сервер (текущее) | Совпадает? |
|---|---|---|---|
| create_chat (все аккаунты) | **5021** (единый) | 5025, 5029, 5030 (раздельно) | **НЕТ** |
| send_text | 5022 | 5022 | ✅ |
| send_media | 5023 | 5023 | ✅ |
| leave_chat | 5024 | 5024, 5028 (раздельно) | **ЧАСТИЧНО** |
| dashboard | 5099 | 5099 (PROtehnik) | ✅ (замена) |

### 3.2 Эндпоинты

| Эндпоинт | Репо | Сервер | Совпадает? |
|---|---|---|---|
| POST /create_chat | порт 5021 | порт 5025/5029/5030 per account | **НЕТ** |
| POST /send_text | порт 5022 | порт 5022 | ✅ |
| POST /send_media | порт 5023 | порт 5023 | ✅ |
| POST /leave_chat | порт 5024 | порт 5024 | ✅ |
| GET /health | все порты | 5022, 5023, 5024 | ✅ |

### 3.3 Session-файлы

| config.py имя | На сервере? | Аккаунт | Проблема |
|---|---|---|---|
| `rumyantsev_create_chat` | ✅ 978KB | main | — |
| `rumyantsev_send_text` | ✅ 1093KB | main | — |
| `rumuantsev_media` | ✅ 1064KB | main | — |
| `rumyantsev_leave` | ✅ 946KB | main | — |
| `rum_create_chat_2` | ✅ 159KB | backup_1 | — |
| `rum_send_text_2` | ❌ | backup_1 | Не существует. Есть `rumyantsev_send_text_2` (API_ID **32292929** ≠ 30517734) |
| `rum_media_2` | ❌ | backup_1 | Не существует. Есть `rumuantsev_media_2` (36KB, неизвестный API_ID) |
| `rum_leave_2` | ❌ | backup_1 | Не существует. Есть `rumyantsev_leave_2` (API_ID **32292929** ≠ 30517734) |
| `rum_create_chat_3` | ✅ 774KB | backup_2 | — |
| `rum_send_text_3` | ❌ | backup_2 | Не существует |
| `rum_media_3` | ❌ | backup_2 | Не существует |
| `rum_leave_3` | ❌ | backup_2 | Не существует |
| `rum_create_chat_4` | ✅ 45KB | backup_3 | — |
| `rum_send_text_4` | ❌ | backup_3 | Не существует |
| `rum_media_4` | ❌ | backup_3 | Не существует |
| `rum_leave_4` | ❌ | backup_3 | Не существует |

**Итого: 7 из 16 есть ✅, 9 НЕ существуют ❌**

### 3.4 Аккаунты

| Аккаунт | В config.py? | На сервере? | Проблема |
|---|---|---|---|
| Main RU (36091011) | ✅ priority=1 | ✅ send_text, send_media, leave_chat, create_chat | — |
| TR backup_1 (30517734) | ✅ priority=2 | ✅ только create_chat_2 (порт 5025) | Нет send_text/media/leave сессий |
| US backup_2 (36215511) | ✅ priority=3 | ✅ только create_chat_3 (порт 5029) | Нет send_text/media/leave сессий |
| TM backup_3 (38343394) | ✅ priority=4 | ✅ только create_chat_4 (порт 5030) | Нет send_text/media/leave сессий |
| **??? (32292929)** | ❌ НЕТ | ✅ leave_chat_2 (5028), send_text_2, send_media_2 | **5-й аккаунт не мигрирован!** |
| US/five_akk (36215511) | ❌ как отдельный | ✅ create_chat_5 (не запущен) | Скрипт не запущен, можно игнорировать |

### 3.5 Зависимости

| Пакет | На сервере | Нужен для app.py? |
|---|---|---|
| Flask 2.2.5 | ✅ | ✅ |
| Telethon 1.41.2 | ✅ | ✅ |
| Werkzeug 3.1.3 | ✅ | ✅ |
| gunicorn 23.0.0 | ✅ | Нет (app.py использует werkzeug.serving) |
| gevent 25.9.1 | ✅ | Нет |
| requests 2.32.5 | ✅ | Для monitor |

---

## 4. РИСКИ И КОНФЛИКТЫ

### КРИТИЧЕСКИЕ (блокеры деплоя)

#### РИСК 1: Зависание на несуществующих сессиях
**Что:** config.py описывает 16 bridge'ей (4 аккаунта × 4 сервиса). Из них 9 session-файлов не существуют.
**Почему опасно:** `TelegramClient.start()` на новой сессии запрашивает ввод номера телефона интерактивно. В фоновом сервисе процесс повиснет навсегда.
**Решение:** Убрать из config.py сессии, которых нет на сервере. Backup-аккаунты оставить только для create_chat.

#### РИСК 2: Консолидация портов ломает n8n/Make
**Что:** Сейчас n8n вызывает create_chat на порты 5025 (TR), 5029 (US), 5030 (TM) для разных аккаунтов. Новая платформа всё принимает на порт 5021 и сама выбирает аккаунт по приоритету.
**Почему опасно:** n8n-сценарии, привязанные к портам 5025/5029/5030, перестанут работать.
**Решение:** Два варианта:
- (A) Перенастроить n8n — все create_chat → порт 5021
- (B) Запустить app.py только для main-аккаунта (порты 5021-5024), а backup create_chat оставить как есть

#### РИСК 3: Потеря 5-го аккаунта (API_ID 32292929)
**Что:** `leave_chat_2_rumyantsev_webhook.py` на порту 5028 использует API_ID 32292929, которого нет в config.py.
**Почему опасно:** Если n8n/Make использует этот эндпоинт — функционал пропадёт.
**Решение:** Выяснить нужен ли этот аккаунт. Если да — добавить в config.py.

### ВЫСОКИЕ (требуют внимания)

#### РИСК 4: telethon-monitor.service в crash loop
**Что:** Сервис бесконечно перезапускается (>111 раз), занимает ресурсы.
**Решение:** `systemctl stop telethon-monitor && systemctl disable telethon-monitor` — новая платформа включает дашборд.

#### РИСК 5: Осиротевшие gunicorn-процессы с Feb06
**Что:** Процессы PID 804037, 804129, 804253, 804366, 804497 висят с 6 февраля. Каждый занимает fd и держит сокет.
**Решение:** Убить перед деплоем вместе с новыми worker'ами.

#### РИСК 6: Порт 5099 занят PROtehnik dashboard
**Что:** PROtehnik dashboard занимает порт 5099, НАШ дашборд хочет тот же порт.
**Решение:** Остановить PROtehnik (`kill 1742259`), новая платформа займёт 5099.

### СРЕДНИЕ

#### РИСК 7: Нет systemd-сервиса для app.py
**Что:** Старые send_text/send_media управляются через systemd. Для app.py нет unit-файла.
**Решение:** Создать `telethon-platform.service`.

#### РИСК 8: WorkingDirectory и пути к сессиям
**Что:** Сессии в `/root/*.session`, config.py использует относительные имена. app.py должен запускаться из `/root/`.
**Решение:** Systemd unit с `WorkingDirectory=/root`.

---

## 5. РЕКОМЕНДУЕМЫЙ ПЛАН ДЕПЛОЯ

### Вариант: БЕЗОПАСНЫЙ (поэтапный, без потери функционала)

**Идея:** Заменяем только скрипты основного аккаунта (порты 5021-5024 + 5099). Backup create_chat скрипты (5025, 5029, 5030) и leave_chat_2 (5028) оставляем как есть до перенастройки n8n.

---

### Подготовка (на локальной машине)

Нужно внести изменения в config.py — убрать несуществующие сессии у backup-аккаунтов. Это делается в репо перед деплоем.

**Изменённый config.py (backup-аккаунты только с create_chat):**

```python
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
        },
    },
]
```

---

### ШАГ 0. Бэкап (на сервере)

```bash
# Бэкап всех скриптов и сессий
mkdir -p /root/backup_20260220
cp /root/*rumyantsev*.py /root/backup_20260220/
cp /root/leave_chat_2_rumyantsev_webhook.py /root/backup_20260220/ 2>/dev/null
cp /root/*rumyantsev*.session /root/backup_20260220/
cp /root/rum_create_chat_*.session /root/backup_20260220/
cp /root/rumuantsev_media*.session /root/backup_20260220/
cp /root/five_akk_rum.session /root/backup_20260220/ 2>/dev/null

# Бэкап systemd unit файлов
cp /etc/systemd/system/send-text-rumyantsev.service /root/backup_20260220/
cp /etc/systemd/system/send-media-rumyantsev.service /root/backup_20260220/
cp /etc/systemd/system/telethon-monitor.service /root/backup_20260220/

# Проверяем бэкап
ls -la /root/backup_20260220/
echo "Backup done: $(ls /root/backup_20260220/ | wc -l) files"
```

### ШАГ 1. Клонируем репо (на сервере)

```bash
cd /root
git clone https://github.com/DanielNocode/Egor_fix_python.git
ls -la /root/Egor_fix_python/
```

### ШАГ 2. Останавливаем ТОЛЬКО заменяемые процессы

```bash
# 2a. Systemd-сервисы (send_text, send_media)
systemctl stop send-text-rumyantsev.service
systemctl stop send-media-rumyantsev.service
systemctl disable send-text-rumyantsev.service
systemctl disable send-media-rumyantsev.service

# 2b. Crash-looping monitor
systemctl stop telethon-monitor.service
systemctl disable telethon-monitor.service

# 2c. Orphaned gunicorn — leave_chat на порту 5024
kill $(ss -tlnp | grep ":5024 " | grep -oP 'pid=\K[0-9]+' | sort -u | tr '\n' ' ') 2>/dev/null
# Ждём и проверяем
sleep 2
ss -tlnp | grep ":5024 " && echo "ПОРТ 5024 ВСЁ ЕЩЁ ЗАНЯТ — нужен kill -9" || echo "OK: порт 5024 свободен"

# 2d. PROtehnik dashboard на 5099
kill 1742259 2>/dev/null
sleep 2
ss -tlnp | grep ":5099 " && echo "ПОРТ 5099 ВСЁ ЕЩЁ ЗАНЯТ" || echo "OK: порт 5099 свободен"

# НЕ ТРОГАЕМ: 5025 (create_chat_2), 5028 (leave_chat_2), 5029 (create_chat_3), 5030 (create_chat_4)
# Эти продолжат работать на старых скриптах пока не перенастроим n8n

# Проверяем что нужные порты свободны
echo "=== Проверка портов ==="
for port in 5021 5022 5023 5024 5099; do
    ss -tlnp | grep ":${port} " && echo "ЗАНЯТ: ${port}" || echo "СВОБОДЕН: ${port}"
done
```

### ШАГ 3. Создаём systemd-сервис для новой платформы

```bash
cat > /etc/systemd/system/telethon-platform.service << 'EOF'
[Unit]
Description=Telethon Unified Platform (Rumyantsev)
After=network.target

[Service]
Type=simple
User=root
WorkingDirectory=/root
ExecStart=/root/telethon_env/bin/python3 /root/Egor_fix_python/app.py
Restart=always
RestartSec=10
KillMode=mixed
TimeoutStopSec=30

# Environment
Environment=REGISTRY_DB=/root/chat_registry.db
Environment=MONITOR_USER=admin
Environment=MONITOR_PASS=telethon2026
Environment=LOG_LEVEL=INFO

# Logging
StandardOutput=journal
StandardError=journal
SyslogIdentifier=telethon-platform

[Install]
WantedBy=multi-user.target
EOF

systemctl daemon-reload
```

### ШАГ 4. Запуск новой платформы

```bash
systemctl start telethon-platform.service

# Ждём старта (прогрев кэша занимает 30-60 секунд)
echo "Ждём запуска..."
sleep 15

# Проверяем статус
systemctl status telethon-platform.service --no-pager

# Проверяем логи (ищем "All bridges started" и "All services started")
journalctl -u telethon-platform.service --no-pager -n 50
```

### ШАГ 5. Проверка health-check'ов

```bash
echo "=== Health Checks ==="
curl -s http://localhost:5021/create_chat 2>/dev/null; echo " ← create_chat (POST only, ожидаем 405 или ошибку)"
curl -s http://localhost:5022/health; echo " ← send_text"
curl -s http://localhost:5023/health; echo " ← send_media"
curl -s http://localhost:5024/health; echo " ← leave_chat"
curl -s -u admin:telethon2026 http://localhost:5099/ | head -5; echo " ← dashboard"
```

### ШАГ 6. Включаем автозапуск

```bash
# Только после успешной проверки!
systemctl enable telethon-platform.service
echo "Done! Платформа включена в автозапуск."
```

---

## 6. ЧЕКЛИСТ ПРОВЕРКИ ПОСЛЕ ДЕПЛОЯ

- [ ] `systemctl status telethon-platform` — active (running)
- [ ] Порт 5021 слушает: `ss -tlnp | grep :5021`
- [ ] Порт 5022 слушает: `ss -tlnp | grep :5022`
- [ ] Порт 5023 слушает: `ss -tlnp | grep :5023`
- [ ] Порт 5024 слушает: `ss -tlnp | grep :5024`
- [ ] Порт 5099 слушает: `ss -tlnp | grep :5099`
- [ ] `/health` на 5022 возвращает `{"status": "ok"}`
- [ ] `/health` на 5023 возвращает `{"status": "ok"}`
- [ ] `/health` на 5024 возвращает `{"status": "ok"}`
- [ ] Дашборд `https://rumyantsevdash.other-digital.ru` открывается
- [ ] В логах нет ошибок авторизации: `journalctl -u telethon-platform -n 100 | grep -iE "(error|failed|banned)"`
- [ ] Тест send_text из n8n/Make — сообщение доставляется
- [ ] Тест send_media из n8n/Make — медиа доставляется
- [ ] Тест create_chat (порт 5021) — чат создаётся
- [ ] Тест leave_chat — выход из чата работает
- [ ] Старые backup-скрипты на 5025/5029/5030 всё ещё работают
- [ ] leave_chat_2 на 5028 всё ещё работает

---

## 7. ПЛАН ОТКАТА

Если что-то пошло не так — откат за 30 секунд:

```bash
# 1. Остановить новую платформу
systemctl stop telethon-platform.service
systemctl disable telethon-platform.service

# 2. Вернуть старые systemd-сервисы
cp /root/backup_20260220/send-text-rumyantsev.service /etc/systemd/system/
cp /root/backup_20260220/send-media-rumyantsev.service /etc/systemd/system/
systemctl daemon-reload
systemctl enable send-text-rumyantsev.service
systemctl enable send-media-rumyantsev.service
systemctl start send-text-rumyantsev.service
systemctl start send-media-rumyantsev.service

# 3. Вернуть leave_chat (gunicorn)
cd /root && nohup /root/telethon_env/bin/gunicorn --bind 0.0.0.0:5024 leave_chat_rumyantsev_webhook:app &

# 4. Вернуть PROtehnik dashboard
nohup /root/telethon_env/bin/python3 /root/PROtehnik/dashboard_server.py &

# 5. Проверить
sleep 5
curl -s http://localhost:5022/health && echo " OK" || echo " FAIL"
curl -s http://localhost:5023/health && echo " OK" || echo " FAIL"
```

---

## 8. СЛЕДУЮЩИЕ ШАГИ (после успешного деплоя)

### Фаза 2: Миграция backup create_chat на единую платформу

1. Перенастроить n8n/Make: все create_chat → порт 5021 (вместо 5025/5029/5030)
2. После перенастройки — остановить старые create_chat скрипты:
   ```bash
   kill $(ss -tlnp | grep ":5025 " | grep -oP 'pid=\K[0-9]+' | sort -u)
   kill $(ss -tlnp | grep ":5029 " | grep -oP 'pid=\K[0-9]+' | sort -u)
   kill $(ss -tlnp | grep ":5030 " | grep -oP 'pid=\K[0-9]+' | sort -u)
   ```
3. Проверить что create_chat через порт 5021 работает для всех аккаунтов

### Фаза 3: Добавить send_text/media/leave для backup-аккаунтов

Для каждого backup-аккаунта создать недостающие сессии:
```bash
# Пример для backup_1 (TR):
cd /root
/root/telethon_env/bin/python3 -c "
from telethon.sync import TelegramClient
c = TelegramClient('rum_send_text_2', 30517734, '3f7c45927d1eadc9bb8c1d2117eda432')
c.start(phone='+905053544048')
print('User:', c.get_me().username)
c.disconnect()
"
# Повторить для rum_media_2, rum_leave_2
# Повторить для backup_2 и backup_3
```

После создания сессий — обновить config.py и перезапустить платформу.

### Фаза 4: Разобраться с 5-м аккаунтом (API_ID 32292929)

Выяснить:
- Кому принадлежит аккаунт с API_ID 32292929?
- Используется ли leave_chat_2 на порту 5028 в n8n/Make?
- Если да — добавить в config.py как backup аккаунт

---

## 9. ВОПРОСЫ, ТРЕБУЮЩИЕ РЕШЕНИЯ

1. **Консолидация create_chat:** Готовы ли вы перенастроить n8n/Make для create_chat → единый порт 5021? Или пока оставить backup create_chat как есть?

2. **5-й аккаунт (32292929):** Нужен ли он? Используется ли leave_chat_2 / send_text_2 / send_media_2?

3. **create_chat_5 (five_akk_rum):** Скрипт не запущен, но сессия есть. Нужен ли он в новой платформе?
