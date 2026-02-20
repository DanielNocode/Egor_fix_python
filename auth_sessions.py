#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
auth_sessions.py — Интерактивное создание Telethon-сессий для backup-аккаунтов.

Запускать на сервере:
    cd /root/Egor_fix_python
    source /root/venv/bin/activate
    python auth_sessions.py

Скрипт покажет, какие сессии уже есть, а какие нужно создать.
Для каждой недостающей сессии — предложит авторизоваться (код из Telegram).
"""

import asyncio
import os
import sys

# Импортируем конфиг из этой же папки
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from config import ACCOUNTS, SERVICE_TYPES

try:
    from telethon import TelegramClient
except ImportError:
    print("Telethon не установлен. Выполните:")
    print("  source /root/venv/bin/activate")
    print("  pip install telethon")
    sys.exit(1)


def get_session_path(session_name: str) -> str:
    """Путь к .session файлу (относительно CWD)."""
    return f"{session_name}.session"


def check_existing_sessions():
    """Показать таблицу: какие сессии есть, каких нет."""
    print("\n" + "=" * 70)
    print("СТАТУС СЕССИЙ")
    print("=" * 70)

    missing = []

    for acc in ACCOUNTS:
        print(f"\n  Аккаунт: {acc['name']} ({acc['username']}, {acc['phone']})")
        print(f"  API_ID:  {acc['api_id']}")

        for svc in SERVICE_TYPES:
            session_name = acc["sessions"].get(svc)
            if session_name:
                path = get_session_path(session_name)
                exists = os.path.exists(path)
                status = "OK" if exists else "НЕТ ФАЙЛА"
                symbol = "+" if exists else "!"
                print(f"    [{symbol}] {svc:15s} -> {session_name}.session  [{status}]")
                if not exists:
                    missing.append((acc, svc, session_name))
            else:
                print(f"    [-] {svc:15s} -> (не указана в config.py)")
                missing.append((acc, svc, None))

    print("\n" + "-" * 70)
    if not missing:
        print("Все сессии на месте! Ничего создавать не нужно.")
    else:
        print(f"Недостаёт {len(missing)} сессий:")
        for acc, svc, name in missing:
            label = name or f"(нужно добавить в config.py)"
            print(f"  - {acc['name']} / {svc} -> {label}")

    return missing


async def create_session(acc: dict, svc: str, session_name: str):
    """Создать одну сессию интерактивно."""
    print(f"\n{'=' * 70}")
    print(f"Создание сессии: {session_name}")
    print(f"  Аккаунт:  {acc['name']} ({acc['username']})")
    print(f"  Телефон:  {acc['phone']}")
    print(f"  API_ID:   {acc['api_id']}")
    print(f"  Сервис:   {svc}")
    print(f"{'=' * 70}")

    client = TelegramClient(session_name, acc["api_id"], acc["api_hash"])

    try:
        await client.connect()

        if await client.is_user_authorized():
            me = await client.get_me()
            print(f"\nСессия уже авторизована как @{me.username} ({me.phone})")
            print("Пропускаем.")
        else:
            print(f"\nОтправляем код на {acc['phone']}...")
            await client.send_code_request(acc["phone"])

            code = input("Введите код из Telegram: ").strip()

            try:
                await client.sign_in(acc["phone"], code)
            except Exception as e:
                if "Two-step verification" in str(e) or "password" in str(e).lower():
                    password = input("Требуется 2FA пароль: ").strip()
                    await client.sign_in(password=password)
                else:
                    raise

            me = await client.get_me()
            print(f"\nУспешно авторизован как @{me.username} ({me.phone})")

        print(f"Файл сессии: {session_name}.session")

    finally:
        await client.disconnect()


async def main():
    print("=" * 70)
    print("  СОЗДАНИЕ TELETHON-СЕССИЙ ДЛЯ BACKUP-АККАУНТОВ")
    print("=" * 70)

    # Проверяем из какой директории запущен скрипт
    cwd = os.getcwd()
    print(f"\nТекущая директория: {cwd}")

    # Также проверяем сессии в /root/ (где они обычно лежат)
    root_dir = "/root"
    if cwd != root_dir and os.path.isdir(root_dir):
        print(f"\nВНИМАНИЕ: Сессии ищутся в {cwd}")
        print(f"Если сессии лежат в {root_dir}, запустите скрипт оттуда")
        print(f"или создайте симлинки.")

    missing = check_existing_sessions()

    if not missing:
        print("\nВсе сессии на месте. Выход.")
        return

    # Фильтруем: только те, у которых есть имя сессии в конфиге
    to_create = [(acc, svc, name) for acc, svc, name in missing if name]
    no_config = [(acc, svc) for acc, svc, name in missing if not name]

    if no_config:
        print(f"\n{'!' * 70}")
        print("ВНИМАНИЕ: Следующие сессии не указаны в config.py.")
        print("Сначала добавьте имена сессий в config.py, потом запустите скрипт снова.")
        for acc, svc in no_config:
            print(f"  - {acc['name']} / {svc}")
        print(f"{'!' * 70}")

    if not to_create:
        print("\nНечего создавать (все недостающие сессии без имени в конфиге).")
        return

    print(f"\nГотов создать {len(to_create)} сессий:")
    for acc, svc, name in to_create:
        print(f"  - {acc['name']} / {svc} -> {name}.session")

    answer = input("\nПродолжить? (y/n): ").strip().lower()
    if answer != "y":
        print("Отменено.")
        return

    for acc, svc, name in to_create:
        try:
            await create_session(acc, svc, name)
        except Exception as e:
            print(f"\nОШИБКА при создании {name}: {e}")
            skip = input("Пропустить и продолжить? (y/n): ").strip().lower()
            if skip != "y":
                print("Прервано.")
                return

    print(f"\n{'=' * 70}")
    print("ГОТОВО! Проверяем финальный статус:")
    check_existing_sessions()


if __name__ == "__main__":
    asyncio.run(main())
