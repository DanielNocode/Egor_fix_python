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

| Скрипт | Сессия (.session) | Назначение |
|---|---|---|
| `create_chat_rumyantsev_webhook.py` | `rumyantsev_create_chat` | Создание чатов |
| `send_media_rumyantsev_webhook.py` | `rumuantsev_media` | Отправка медиа |
| `send_text_rumyantsev_webhook.py` | `rumyantsev_send_text` | Отправка текста |

**Статус:** ✅ Живой. Сессии media и send_text были залочены (скрипты активно работают).

---

## Аккаунт 2 — Турция (TR)

- **Телефон:** +905053544048
- **Имя:** Александр
- **Username:** @rumPRodar
- **API_ID:** 30517734
- **API_HASH:** 3f7c45927d1eadc9bb8c1d2117eda432

| Скрипт | Сессия (.session) | Назначение |
|---|---|---|
| `create_chat_2_rumyantsev_webhook.py` | `rum_create_chat_2` | Создание чатов |

**Статус:** ✅ Живой.

---

## Аккаунт 3 — США (US)

- **Телефон:** +18177669809
- **Имя:** Александр Румянцев
- **Username:** @aleksrumi
- **API_ID:** 36215511
- **API_HASH:** d48299050413bf020ec911bf74f7bf56

| Скрипт | Сессия (.session) | Назначение |
|---|---|---|
| `create_chat_5_rumyantsev_webhook.py` | `five_akk_rum` | Создание чатов |
| `create_chat_3_rumyantsev_webhook.py` | `rum_create_chat_3` | Создание чатов |

**Статус:** ✅ Живой. Сессия `rum_create_chat_3` была залочена (скрипт активно работает). Оба скрипта используют один и тот же API_ID/HASH, предположительно один аккаунт.

---

## Аккаунт 4 — Туркменистан (TM)

- **Телефон:** +99362724797
- **Имя:** Саша
- **Username:** @ProdarAl
- **API_ID:** 38343394
- **API_HASH:** a211f75e849a77558ca4fe54b41b2b2b

| Скрипт | Сессия (.session) | Назначение |
|---|---|---|
| `create_chat_4_rumyantsev_webhook.py` | `rum_create_chat_4` | Создание чатов |

**Статус:** ✅ Живой.

---

## Мёртвые сессии (NOT AUTHORIZED)

- **API_ID:** 32292929
- **API_HASH:** d125cce996bd21d5bba9eb522dbc2087

| Скрипт | Сессия (.session) | Назначение | Статус |
|---|---|---|---|
| `send_media_2_rumyantsev_webhook.py` | `rumuantsev_media_2` | Отправка медиа | ⚠️ Требует переавторизации |
| `send_text_2_rumyantsev_webhook.py` | `rumyantsev_send_text_2` | Отправка текста | ⚠️ Требует переавторизации |

**Аккаунт не определён** — сессии протухли, `get_me()` недоступен. Для восстановления нужна повторная авторизация по номеру телефона.

---

## Дополнительные сессии на сервере (не привязаны к rumyantsev-скриптам)

На сервере также найдены `.session` файлы, не используемые в текущих webhook-скриптах:

- `rumyantsev_leave.session`, `rumyantsev_leave_2.session` — выход из чатов
- `rumyantsev_text.session` — текст (отдельная)
- `rumyantsev_create_chat_2.session`, `rumyantsev_create_chat_3.session`, `rumyantsev_create_chat_4.session` — дубли/альтернативные сессии создания чатов
- Множество `backup_*`, `anon_*`, `main_*` сессий — другие проекты

---

## Сводная таблица: Скрипт → Аккаунт

| Скрипт | Аккаунт | Телефон |
|---|---|---|
| `create_chat_rumyantsev_webhook.py` | RU основной | +79808625417 |
| `send_media_rumyantsev_webhook.py` | RU основной | +79808625417 |
| `send_text_rumyantsev_webhook.py` | RU основной | +79808625417 |
| `create_chat_2_rumyantsev_webhook.py` | TR | +905053544048 |
| `create_chat_3_rumyantsev_webhook.py` | US | +18177669809 |
| `create_chat_4_rumyantsev_webhook.py` | TM | +99362724797 |
| `create_chat_5_rumyantsev_webhook.py` | US | +18177669809 |
| `send_media_2_rumyantsev_webhook.py` | ❌ мёртвая сессия | неизвестен |
| `send_text_2_rumyantsev_webhook.py` | ❌ мёртвая сессия | неизвестен |
