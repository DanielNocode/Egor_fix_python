import asyncio
import logging
import threading
from typing import Any, Dict, List, Optional

import requests as http_requests
from flask import Flask, request, jsonify
from telethon import TelegramClient, functions, types
from telethon.utils import get_peer_id

logger = logging.getLogger("legacy.create_chat")

# === КОНФИГ ===============================================================
API_ID = 36091011
API_HASH = "72fa475b3b4f5124b9f165672dca423b"
SESSION_PATH = "rumyantsev_create_chat"  # сессия нужного аккаунта

SALEBOT_CALLBACK_URL = "https://chatter.salebot.pro/api/17fb55a49883fb26bef73b6429fc4cf1/tg_callback"
SALEBOT_GROUP_ID = "alex_rumhelp_bot"

# === ГЛОБАЛЬНЫЕ ПЕРЕМЕННЫЕ ================================================
app = Flask(__name__)
_loop = asyncio.new_event_loop()
_client: Optional[TelegramClient] = None

# === ХЕЛПЕРЫ ==============================================================

def run_coro(coro, timeout: int = 120):
    """Запуск корутины в нашем loop из потока Flask."""
    return asyncio.run_coroutine_threadsafe(coro, _loop).result(timeout=timeout)

async def resolve_idents(client: TelegramClient, idents: List[str]) -> Dict[str, Any]:
    out: Dict[str, Any] = {}
    for raw in idents:
        s = (raw or "").strip()
        if not s:
            continue
        try:
            if s.startswith("@"):
                ent = await client.get_entity(s)
            elif s.isdigit():
                ent = await client.get_entity(int(s))
            else:
                ent = await client.get_entity(s)
            out[s] = ent
        except Exception as e:
            out[s] = {"error": str(e)}
    return out

async def export_invite_for_channel(client: TelegramClient, channel: Any) -> Optional[str]:
    try:
        r = await client(functions.messages.ExportChatInviteRequest(peer=channel))
        return getattr(r, "link", None)
    except Exception:
        return None

async def promote_bot_admin(client: TelegramClient, channel_peer: Any, bot_user: types.User) -> str:
    """
    Делает БОТА админом со ВСЕМИ возможными правами (насколько позволяет версия Telethon/Telegram).
    Безопасно деградирует, если каких-то флагов нет в текущей версии.
    """
    rights_variants = []
    try:
        rights_variants.append(
            types.ChatAdminRights(
                change_info=True,
                post_messages=True,
                edit_messages=True,
                delete_messages=True,
                ban_users=True,
                invite_users=True,
                pin_messages=True,
                add_admins=True,
                anonymous=False,
                manage_call=True,
                manage_topics=True,   # форумы/топики
                post_stories=True,
                edit_stories=True,
                delete_stories=True,
            )
        )
    except TypeError:
        pass

    try:
        rights_variants.append(
            types.ChatAdminRights(
                change_info=True,
                post_messages=True,
                edit_messages=True,
                delete_messages=True,
                ban_users=True,
                invite_users=True,
                pin_messages=True,
                add_admins=True,
                anonymous=False,
                manage_call=True,
                manage_topics=True,
            )
        )
    except TypeError:
        pass

    try:
        rights_variants.append(
            types.ChatAdminRights(
                change_info=True,
                post_messages=True,
                edit_messages=True,
                delete_messages=True,
                ban_users=True,
                invite_users=True,
                pin_messages=True,
                add_admins=True,
                anonymous=False,
                manage_call=True,
            )
        )
    except TypeError:
        pass

    if not rights_variants:
        rights_variants.append(
            types.ChatAdminRights(
                change_info=True,
                delete_messages=True,
                ban_users=True,
                invite_users=True,
                pin_messages=True,
                add_admins=True,
                anonymous=False,
                manage_call=True,
            )
        )

    last_error = None
    for rights in rights_variants:
        try:
            iu = types.InputUser(bot_user.id, bot_user.access_hash)
            await client(functions.channels.EditAdminRequest(
                channel=channel_peer,
                user_id=iu,
                admin_rights=rights,
                rank="Admin Bot"
            ))
            return "ok"
        except Exception as e:
            last_error = e

    return f"error:{last_error}"

# === ТЕЛЕГРАМ-ПОТОК =======================================================
def telethon_thread():
    global _client
    asyncio.set_event_loop(_loop)

    _client = TelegramClient(SESSION_PATH, API_ID, API_HASH)
    started = _client.start()
    if asyncio.iscoroutine(started):
        _loop.run_until_complete(started)

    # ВНИМАНИЕ: Никаких обработчиков событий и отправки сообщений не регистрируем
    _loop.run_forever()

threading.Thread(target=telethon_thread, name="telethon-loop", daemon=True).start()

# === Salebot callback =====================================================

def _send_salebot_callback(client_tg_id: str, invite_link: str):
    """Отправляет callback в salebot с invite_link после создания чата."""
    payload = {
        "message": "send_invite_link",
        "user_id": client_tg_id,
        "group_id": SALEBOT_GROUP_ID,
        "tg_business": 1,
        "invite_link": invite_link,
    }
    try:
        resp = http_requests.post(
            SALEBOT_CALLBACK_URL,
            json=payload,
            timeout=15,
        )
        logger.info("salebot callback sent: status=%s body=%s", resp.status_code, resp.text[:200])
    except Exception as e:
        logger.error("salebot callback failed: %s", e)


# === HTTP: создание супергруппы (без отправки сообщений) ==================
@app.route("/create_chat", methods=["POST"])
def create_chat():
    """
    JSON:
    {
      "title": "Тест-драйв. Имя. Дата",
      "usernames": ["@acc1","@acc2"],
      "client_tg_id": "123456789"      # TG ID клиента для callback в salebot
    }
    """
    if _client is None:
        return jsonify({"error": "telethon client not ready"}), 503

    data = request.get_json(force=True, silent=True) or {}
    title: str = (data.get("title") or "").strip()
    usernames: List[str] = data.get("usernames") or []
    client_tg_id: str = str(data.get("client_tg_id") or "").strip()

    if not title:
        return jsonify({"error": "title is required"}), 400
    if not usernames or not isinstance(usernames, list):
        return jsonify({"error": "usernames (array) is required"}), 400

    debug: Dict[str, Any] = {"idents_sample": usernames[:2]}

    try:
        # 1) резолвим пользователей
        resolved = run_coro(resolve_idents(_client, usernames), timeout=40)
        ok_users: List[Any] = []
        resolve_failed: List[str] = []
        for k, v in resolved.items():
            if isinstance(v, dict) and "error" in v:
                resolve_failed.append(f"{k}: {v['error']}")
            else:
                ok_users.append(v)
        debug["resolve_failed"] = resolve_failed
        if not ok_users:
            return jsonify({"error": "no resolvable users", "debug": debug}), 400

        # 2) создаём супергруппу
        upd = run_coro(
            _client(functions.channels.CreateChannelRequest(
                title=title,
                about="",
                megagroup=True,
                for_import=False
            )),
            timeout=40
        )

        # 3) получаем сущность канала
        channel_ent = None
        if getattr(upd, "chats", None):
            for c in upd.chats:
                if isinstance(c, types.Channel) and (getattr(c, "megagroup", True)):
                    channel_ent = c
                    break
        if channel_ent is None:
            return jsonify({"error": "cannot determine created supergroup", "debug": debug}), 500

        channel_peer = channel_ent
        watched_id = get_peer_id(channel_ent)  # «-100…»

        # 4) открываем историю для новых участников
        try:
            run_coro(_client(functions.channels.TogglePreHistoryHiddenRequest(
                channel=channel_peer,
                enabled=False
            )), 20)
            debug["open_history"] = "ok"
        except Exception as e:
            debug["open_history"] = f"error:{e}"

        # 5) приглашаем пользователей + повышаем ботов в админы
        invite_failed: List[str] = []
        users_meta: List[types.User] = []
        try:
            batch = []
            for u in ok_users:
                ent = u
                if not hasattr(ent, "access_hash"):
                    ent = run_coro(_client.get_entity(u), 20)
                if isinstance(ent, types.User):
                    users_meta.append(ent)
                batch.append(types.InputUser(ent.id, ent.access_hash))

            if batch:
                run_coro(_client(functions.channels.InviteToChannelRequest(
                    channel=channel_peer,
                    users=batch
                )), 30)
            debug["invite"] = "ok"
        except Exception as e:
            debug["invite"] = "error"
            invite_failed.append(str(e))
        debug["invite_failed"] = invite_failed

        # 5.1) ПОВЫШАЕМ ТОЛЬКО БОТОВ в АДМИНЫ (ВСЕ ПРАВА)
        try:
            run_coro(asyncio.sleep(1), 5)
            promote_results: List[str] = []
            for usr in users_meta:
                if getattr(usr, "bot", False):
                    res = run_coro(promote_bot_admin(_client, channel_peer, usr), 60)
                    promote_results.append(f"@{usr.username or usr.id}: {res}")
            debug["promote_bots"] = promote_results or ["no_bots_detected"]
        except Exception as e:
            debug["promote_bots_error"] = str(e)

        # 6) инвайт-ссылка (на будущее/отладку)
        invite_link = run_coro(export_invite_for_channel(_client, channel_peer), 20) or None
        debug["export_invite"] = "ok" if invite_link else "none"

        # Отправляем callback в salebot
        if client_tg_id and invite_link:
            _send_salebot_callback(client_tg_id, invite_link)

        return jsonify({
            "status": "ok",
            "title": title,
            "chat_id": str(watched_id),       # «-100…»
            "invite_link": invite_link,
            "debug": debug
        })
    except Exception as e:
        return jsonify({"error": str(e)}), 500

# === ЛОКАЛЬНЫЙ ЗАПУСК =====================================================
if __name__ == "__main__":
    # Локально, без gunicorn
    app.run(host="0.0.0.0", port=5021)