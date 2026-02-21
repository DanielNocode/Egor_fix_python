#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
check_sessions.py -- Check which sessions are actually authorized.

Run on server:
    cd /root
    /root/venv/bin/python3 /root/Egor_fix_python/check_sessions.py
"""

import asyncio
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from config import ACCOUNTS, SERVICE_TYPES

try:
    from telethon import TelegramClient
except ImportError:
    print("Telethon not installed.")
    sys.exit(1)


async def check_one(acc, svc, session_name):
    path = f"{session_name}.session"
    if not os.path.exists(path):
        return session_name, "MISSING", None

    size = os.path.getsize(path)
    client = TelegramClient(session_name, acc["api_id"], acc["api_hash"])
    try:
        await client.connect()
        if await client.is_user_authorized():
            me = await client.get_me()
            username = me.username or me.first_name or "?"
            return session_name, "OK", f"@{username} ({size} bytes)"
        else:
            return session_name, "NOT AUTH", f"file exists but not authorized ({size} bytes)"
    except Exception as e:
        return session_name, "ERROR", str(e)
    finally:
        await client.disconnect()


async def main():
    print("=" * 70)
    print("  SESSION AUTHORIZATION CHECK")
    print("=" * 70)
    print(f"  Directory: {os.getcwd()}\n")

    ok = 0
    fail = 0

    for acc in ACCOUNTS:
        print(f"  {acc['name']} ({acc['username']}, {acc['phone']})")

        for svc in SERVICE_TYPES:
            session_name = acc["sessions"].get(svc)
            if not session_name:
                print(f"    {svc:15s}  -- not in config")
                fail += 1
                continue

            name, status, detail = await check_one(acc, svc, session_name)

            if status == "OK":
                print(f"    {svc:15s}  [OK]       {detail}")
                ok += 1
            elif status == "MISSING":
                print(f"    {svc:15s}  [MISSING]  file not found")
                fail += 1
            elif status == "NOT AUTH":
                print(f"    {svc:15s}  [NO AUTH]  {detail}")
                fail += 1
            else:
                print(f"    {svc:15s}  [ERROR]    {detail}")
                fail += 1

        print()

    print("-" * 70)
    print(f"  OK: {ok}   |   Failed/Missing: {fail}   |   Total: {ok + fail}")
    print("=" * 70)


if __name__ == "__main__":
    asyncio.run(main())
