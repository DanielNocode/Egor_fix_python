# Rumyantsev Telethon Sessions — Полный контекст

**Сервер:** root@wfoxxidthq
**Расположение сессий:** `/root/*.session`
**Python с Telethon:** `/root/telethon_env/bin/python3`
**Все скрипты:** в `/root/`

---

## Аккаунт 1 — Основной (RU)

- **Телефон:** +79808625417
- **Имя:** Александр
- **Username:** @rumyancev_alex
- **API_ID:** 36091011
- **API_HASH:** 72fa475b3b4f5124b9f165672dca423b

| Скрипт | Путь к скрипту | Сессия | Путь к сессии | Назначение |
|---|---|---|---|---|
| `create_chat_rumyantsev_webhook.py` | `/root/create_chat_rumyantsev_webhook.py` | `rumyantsev_create_chat` | `/root/rumyantsev_create_chat.session` | Создание чатов |
| `send_media_rumyantsev_webhook.py` | `/root/send_media_rumyantsev_webhook.py` | `rumuantsev_media` | `/root/rumuantsev_media.session` | Отправка медиа |
| `send_text_rumyantsev_webhook.py` | `/root/send_text_rumyantsev_webhook.py` | `rumyantsev_send_text` | `/root/rumyantsev_send_text.session` | Отправка текста |
| `leave_chat_rumyantsev_webhook.py` | `/root/leave_chat_rumyantsev_webhook.py` | `rumyantsev_leave` | `/root/rumyantsev_leave.session` | Выход из чатов |

**Статус:** ✅ Живой. Сессии media и send_text были залочены (скрипты активно работают).

---

## Аккаунт 2 — Турция (TR)

- **Телефон:** +905053544048
- **Имя:** Александр
- **Username:** @rumPRodar
- **API_ID:** 30517734
- **API_HASH:** 3f7c45927d1eadc9bb8c1d2117eda432

| Скрипт | Путь к скрипту | Сессия | Путь к сессии | Назначение |
|---|---|---|---|---|
| `create_chat_2_rumyantsev_webhook.py` | `/root/create_chat_2_rumyantsev_webhook.py` | `rum_create_chat_2` | `/root/rum_create_chat_2.session` | Создание чатов |

**Статус:** ✅ Живой.

---

## Аккаунт 3 — США (US)

- **Телефон:** +18177669809
- **Имя:** Александр Румянцев
- **Username:** @aleksrumi
- **API_ID:** 36215511
- **API_HASH:** d48299050413bf020ec911bf74f7bf56

| Скрипт | Путь к скрипту | Сессия | Путь к сессии | Назначение |
|---|---|---|---|---|
| `create_chat_5_rumyantsev_webhook.py` | `/root/create_chat_5_rumyantsev_webhook.py` | `five_akk_rum` | `/root/five_akk_rum.session` | Создание чатов |
| `create_chat_3_rumyantsev_webhook.py` | `/root/create_chat_3_rumyantsev_webhook.py` | `rum_create_chat_3` | `/root/rum_create_chat_3.session` | Создание чатов |

**Статус:** ✅ Живой. Сессия `rum_create_chat_3` была залочена (скрипт активно работает). Оба скрипта используют один и тот же API_ID/HASH, предположительно один аккаунт.

---

## Аккаунт 4 — Туркменистан (TM)

- **Телефон:** +99362724797
- **Имя:** Саша
- **Username:** @ProdarAl
- **API_ID:** 38343394
- **API_HASH:** a211f75e849a77558ca4fe54b41b2b2b

| Скрипт | Путь к скрипту | Сессия | Путь к сессии | Назначение |
|---|---|---|---|---|
| `create_chat_4_rumyantsev_webhook.py` | `/root/create_chat_4_rumyantsev_webhook.py` | `rum_create_chat_4` | `/root/rum_create_chat_4.session` | Создание чатов |

**Статус:** ✅ Живой.

---

## Дополнительные сессии на сервере (не привязаны к rumyantsev-скриптам)

На сервере также найдены `.session` файлы, не используемые в текущих webhook-скриптах:

- `rumyantsev_leave.session`, `rumyantsev_leave_2.session` — выход из чатов
- `rumyantsev_text.session` — текст (отдельная)
- `rumyantsev_create_chat_2.session`, `rumyantsev_create_chat_3.session`, `rumyantsev_create_chat_4.session` — дубли/альтернативные сессии создания чатов
- Множество `backup_*`, `anon_*`, `main_*` сессий — другие проекты

---

## Сводная таблица: Скрипт → Аккаунт

| Скрипт | Путь | Аккаунт | Телефон | Сессия |
|---|---|---|---|---|
| `create_chat_rumyantsev_webhook.py` | `/root/` | RU основной | +79808625417 | `/root/rumyantsev_create_chat.session` |
| `send_media_rumyantsev_webhook.py` | `/root/` | RU основной | +79808625417 | `/root/rumuantsev_media.session` |
| `send_text_rumyantsev_webhook.py` | `/root/` | RU основной | +79808625417 | `/root/rumyantsev_send_text.session` |
| `leave_chat_rumyantsev_webhook.py` | `/root/` | RU основной | +79808625417 | `/root/rumyantsev_leave.session` |
| `create_chat_2_rumyantsev_webhook.py` | `/root/` | TR | +905053544048 | `/root/rum_create_chat_2.session` |
| `create_chat_3_rumyantsev_webhook.py` | `/root/` | US | +18177669809 | `/root/rum_create_chat_3.session` |
| `create_chat_4_rumyantsev_webhook.py` | `/root/` | TM | +99362724797 | `/root/rum_create_chat_4.session` |
| `create_chat_5_rumyantsev_webhook.py` | `/root/` | US | +18177669809 | `/root/five_akk_rum.session` |
