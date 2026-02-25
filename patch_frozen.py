#!/usr/bin/env python3
"""
patch_frozen.py — Патч для добавления обработки FrozenParticipantMissingError.
Запуск: python3 /root/Egor_fix_python/patch_frozen.py
"""
import os

BASE = "/root/Egor_fix_python"


def patch_retry():
    path = os.path.join(BASE, "core", "retry.py")
    with open(path) as f:
        content = f.read()
    if "is_frozen_error" in content:
        print("[retry.py] Already patched")
        return
    marker = 'return "persistenttimestamp" in name or "persistent timestamp" in text'
    new_func = (
        '\n\n\ndef is_frozen_error(e: Exception) -> bool:\n'
        '    """FrozenParticipantMissingError — аккаунт заморожен Telegram\'ом."""\n'
        '    name = type(e).__name__.lower()\n'
        '    text = str(e).lower()\n'
        '    return "frozenparticipant" in name or "frozen" in text'
    )
    content = content.replace(marker, marker + new_func)
    with open(path, "w") as f:
        f.write(content)
    print("[retry.py] PATCHED — added is_frozen_error()")


def patch_bridge():
    path = os.path.join(BASE, "core", "bridge.py")
    with open(path) as f:
        content = f.read()
    changed = False

    # 1. Add STATUS_FROZEN
    if "STATUS_FROZEN" not in content:
        content = content.replace(
            '    STATUS_BANNED = "banned"',
            '    STATUS_BANNED = "banned"\n    STATUS_FROZEN = "frozen"',
        )
        changed = True

    # 2. Add mark_frozen() after mark_banned()
    if "def mark_frozen" not in content:
        mark_banned_block = (
            '    def mark_banned(self):\n'
            '        self.status = self.STATUS_BANNED\n'
            '        self.last_error = "Account banned"\n'
            '        logger.error("Bridge %s: BANNED", self.name)'
        )
        mark_frozen_block = (
            '\n\n    def mark_frozen(self):\n'
            '        self.status = self.STATUS_FROZEN\n'
            '        self.last_error = "Account frozen (FrozenParticipantMissingError)"\n'
            '        logger.error("Bridge %s: FROZEN", self.name)'
        )
        content = content.replace(mark_banned_block, mark_banned_block + mark_frozen_block)
        changed = True

    # 3. Patch periodic_warmup to skip frozen/banned
    old_warmup = (
        '    async def periodic_warmup(self):\n'
        '        """Бесконечный цикл: прогреваем кэш каждые CACHE_WARMUP_INTERVAL секунд."""\n'
        '        while True:\n'
        '            await asyncio.sleep(config.CACHE_WARMUP_INTERVAL)\n'
        '            try:\n'
        '                await self.warmup_cache()\n'
        '            except Exception as e:\n'
        '                logger.error("Bridge %s: periodic warmup failed: %s", self.name, e)'
    )
    new_warmup = (
        '    async def periodic_warmup(self):\n'
        '        """Бесконечный цикл: прогреваем кэш каждые CACHE_WARMUP_INTERVAL секунд."""\n'
        '        while True:\n'
        '            await asyncio.sleep(config.CACHE_WARMUP_INTERVAL)\n'
        '            # Не прогреваем кэш для заблокированных/замороженных bridge\'ей\n'
        '            if self.status in (self.STATUS_BANNED, self.STATUS_FROZEN):\n'
        '                continue\n'
        '            try:\n'
        '                await self.warmup_cache()\n'
        '            except Exception as e:\n'
        '                err_lower = str(e).lower()\n'
        '                if "frozen" in err_lower:\n'
        '                    self.mark_frozen()\n'
        '                elif "banned" in err_lower or "deactivated" in err_lower:\n'
        '                    self.mark_banned()\n'
        '                elif "disconnected" in err_lower and self.status in (self.STATUS_FROZEN, self.STATUS_BANNED):\n'
        '                    pass  # уже помечен, не спамим логи\n'
        '                else:\n'
        '                    logger.error("Bridge %s: periodic warmup failed: %s", self.name, e)'
    )
    if "STATUS_FROZEN, self.STATUS_BANNED" not in content and old_warmup in content:
        content = content.replace(old_warmup, new_warmup)
        changed = True

    if changed:
        with open(path, "w") as f:
            f.write(content)
        print("[bridge.py] PATCHED — added STATUS_FROZEN, mark_frozen(), warmup skip")
    else:
        print("[bridge.py] Already patched")


def patch_router():
    path = os.path.join(BASE, "core", "router.py")
    with open(path) as f:
        content = f.read()
    changed = False

    # 1. Add import
    old_import = "from core.retry import is_flood_wait, flood_wait_seconds"
    new_import = "from core.retry import is_flood_wait, flood_wait_seconds, is_frozen_error"
    if "is_frozen_error" not in content:
        content = content.replace(old_import, new_import)
        changed = True

    # 2. Add frozen handling in handle_error
    old_banned = (
        '        elif "banned" in str(error).lower() or "deactivated" in str(error).lower():\n'
        '            bridge.mark_banned()\n'
        '            self.registry.log_operation(\n'
        '                bridge.account_name, chat_id, operation, "banned",\n'
        '                detail=str(error),\n'
        '            )'
    )
    new_frozen_and_banned = (
        '        elif is_frozen_error(error):\n'
        '            bridge.mark_frozen()\n'
        '            self.registry.log_operation(\n'
        '                bridge.account_name, chat_id, operation, "frozen",\n'
        '                detail=str(error),\n'
        '            )\n'
        '        elif "banned" in str(error).lower() or "deactivated" in str(error).lower():\n'
        '            bridge.mark_banned()\n'
        '            self.registry.log_operation(\n'
        '                bridge.account_name, chat_id, operation, "banned",\n'
        '                detail=str(error),\n'
        '            )'
    )
    if "is_frozen_error(error)" not in content and old_banned in content:
        content = content.replace(old_banned, new_frozen_and_banned)
        changed = True

    if changed:
        with open(path, "w") as f:
            f.write(content)
        print("[router.py] PATCHED — added frozen error handling")
    else:
        print("[router.py] Already patched")


def patch_routes():
    path = os.path.join(BASE, "dashboard", "routes.py")
    with open(path) as f:
        content = f.read()

    if '"clear_frozen"' in content:
        print("[routes.py] Already has clear_frozen")
        return

    # Add clear_frozen action after clear_flood
    old_return = '        return jsonify({"error": "unknown action"}), 400'
    new_actions = (
        '        elif action == "clear_frozen":\n'
        '            if account:\n'
        '                bridge = _pool.get(account)\n'
        '                if bridge and bridge.status == bridge.STATUS_FROZEN:\n'
        '                    bridge.error_count = 0\n'
        '                    bridge.last_error = None\n'
        '                    bridge.status = bridge.STATUS_HEALTHY\n'
        '                    return jsonify({"status": "ok"})\n'
        '            return jsonify({"error": "unknown bridge or not frozen"}), 400\n'
        '\n'
        '        elif action == "git_pull":\n'
        '            try:\n'
        '                result = subprocess.run(\n'
        '                    ["git", "pull", "origin", "main"],\n'
        '                    cwd="/root/Egor_fix_python",\n'
        '                    capture_output=True, text=True, timeout=30,\n'
        '                )\n'
        '                return jsonify({\n'
        '                    "status": "ok",\n'
        '                    "stdout": result.stdout,\n'
        '                    "stderr": result.stderr,\n'
        '                    "returncode": result.returncode,\n'
        '                })\n'
        '            except Exception as e:\n'
        '                return jsonify({"error": str(e)}), 500\n'
        '\n'
        '        elif action == "deploy":\n'
        '            """git pull + restart service."""\n'
        '            try:\n'
        '                pull = subprocess.run(\n'
        '                    ["git", "pull", "origin", "main"],\n'
        '                    cwd="/root/Egor_fix_python",\n'
        '                    capture_output=True, text=True, timeout=30,\n'
        '                )\n'
        '                if pull.returncode != 0:\n'
        '                    return jsonify({\n'
        '                        "error": "git pull failed",\n'
        '                        "stdout": pull.stdout,\n'
        '                        "stderr": pull.stderr,\n'
        '                    }), 500\n'
        '                subprocess.Popen(\n'
        '                    ["systemctl", "restart", "telethon-platform"],\n'
        '                    stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,\n'
        '                )\n'
        '                return jsonify({\n'
        '                    "status": "ok",\n'
        '                    "git_output": pull.stdout,\n'
        '                })\n'
        '            except Exception as e:\n'
        '                return jsonify({"error": str(e)}), 500\n'
        '\n'
        '        return jsonify({"error": "unknown action"}), 400'
    )
    content = content.replace(old_return, new_actions)
    with open(path, "w") as f:
        f.write(content)
    print("[routes.py] PATCHED — added clear_frozen, git_pull, deploy actions")


if __name__ == "__main__":
    patch_retry()
    patch_bridge()
    patch_router()
    patch_routes()
    print("\nAll patches applied! Restart service: systemctl restart telethon-platform")
