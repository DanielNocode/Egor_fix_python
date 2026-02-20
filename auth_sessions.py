#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
auth_sessions.py -- Create Telethon sessions for backup accounts.

Run on server:
    cd /root
    /root/venv/bin/python3 /root/Egor_fix_python/auth_sessions.py
"""

import asyncio
import os
import sys

# Fix encoding for non-UTF-8 terminals
import io
if sys.stdout.encoding != "utf-8":
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8", errors="replace")
if sys.stdin.encoding != "utf-8":
    sys.stdin = io.TextIOWrapper(sys.stdin.buffer, encoding="utf-8", errors="replace")

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from config import ACCOUNTS, SERVICE_TYPES

try:
    from telethon import TelegramClient
except ImportError:
    print("Telethon not installed. Run:")
    print("  /root/venv/bin/pip install telethon")
    sys.exit(1)


def get_session_path(session_name):
    return f"{session_name}.session"


def check_existing_sessions():
    print("\n" + "=" * 70)
    print("SESSION STATUS")
    print("=" * 70)

    missing = []

    for acc in ACCOUNTS:
        print(f"\n  Account: {acc['name']} ({acc['username']}, {acc['phone']})")
        print(f"  API_ID:  {acc['api_id']}")

        for svc in SERVICE_TYPES:
            session_name = acc["sessions"].get(svc)
            if session_name:
                path = get_session_path(session_name)
                exists = os.path.exists(path)
                status = "OK" if exists else "MISSING"
                symbol = "+" if exists else "!"
                print(f"    [{symbol}] {svc:15s} -> {session_name}.session  [{status}]")
                if not exists:
                    missing.append((acc, svc, session_name))
            else:
                print(f"    [-] {svc:15s} -> (not in config.py)")
                missing.append((acc, svc, None))

    print("\n" + "-" * 70)
    if not missing:
        print("All sessions exist! Nothing to create.")
    else:
        print(f"Missing {len(missing)} sessions:")
        for acc, svc, name in missing:
            label = name or "(add to config.py first)"
            print(f"  - {acc['name']} / {svc} -> {label}")

    return missing


async def create_session(acc, svc, session_name):
    print(f"\n{'=' * 70}")
    print(f"Creating session: {session_name}")
    print(f"  Account:  {acc['name']} ({acc['username']})")
    print(f"  Phone:    {acc['phone']}")
    print(f"  API_ID:   {acc['api_id']}")
    print(f"  Service:  {svc}")
    print(f"{'=' * 70}")

    client = TelegramClient(session_name, acc["api_id"], acc["api_hash"])

    try:
        await client.connect()

        if await client.is_user_authorized():
            me = await client.get_me()
            print(f"\nAlready authorized as @{me.username} ({me.phone})")
            print("Skipping.")
        else:
            print(f"\nSending code to {acc['phone']}...")
            await client.send_code_request(acc["phone"])

            code = input("Enter Telegram code: ").strip()

            try:
                await client.sign_in(acc["phone"], code)
            except Exception as e:
                err_str = str(e)
                if "Two-step verification" in err_str or "password" in err_str.lower():
                    password = input("2FA password required: ").strip()
                    try:
                        await client.sign_in(password=password)
                    except UnicodeDecodeError as ue:
                        print(f"\nENCODING ERROR: {ue}")
                        print("The password likely contains non-ASCII characters (Cyrillic?).")
                        print("Try setting terminal encoding: export LANG=en_US.UTF-8")
                        print("Or check if the password was typed in the wrong keyboard layout.")
                        raise
                else:
                    raise

            me = await client.get_me()
            print(f"\nAuthorized as @{me.username} ({me.phone})")

        print(f"Session file: {session_name}.session")

    finally:
        await client.disconnect()


async def main():
    print("=" * 70)
    print("  CREATE TELETHON SESSIONS FOR BACKUP ACCOUNTS")
    print("=" * 70)

    cwd = os.getcwd()
    print(f"\nCurrent directory: {cwd}")

    if cwd != "/root" and os.path.isdir("/root"):
        print(f"\nWARNING: Sessions are searched in {cwd}")
        print(f"If sessions are in /root/, run this script from /root/")

    missing = check_existing_sessions()

    if not missing:
        print("\nAll sessions exist. Done.")
        return

    to_create = [(acc, svc, name) for acc, svc, name in missing if name]
    no_config = [(acc, svc) for acc, svc, name in missing if not name]

    if no_config:
        print(f"\n{'!' * 70}")
        print("WARNING: These sessions are not defined in config.py:")
        for acc, svc in no_config:
            print(f"  - {acc['name']} / {svc}")
        print(f"{'!' * 70}")

    if not to_create:
        print("\nNothing to create.")
        return

    print(f"\nReady to create {len(to_create)} sessions:")
    for acc, svc, name in to_create:
        print(f"  - {acc['name']} / {svc} -> {name}.session")

    answer = input("\nContinue? (y/n): ").strip().lower()
    if answer != "y":
        print("Cancelled.")
        return

    for acc, svc, name in to_create:
        try:
            await create_session(acc, svc, name)
        except Exception as e:
            print(f"\nERROR creating {name}: {e}")
            skip = input("Skip and continue? (y/n): ").strip().lower()
            if skip != "y":
                print("Aborted.")
                return

    print(f"\n{'=' * 70}")
    print("DONE! Final status:")
    check_existing_sessions()


if __name__ == "__main__":
    asyncio.run(main())
