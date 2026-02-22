# -*- coding: utf-8 -*-
"""
services/create_chat.py — POST /create_chat

Создание супергруппы, приглашение участников, повышение ботов.
Привязывает созданный чат к аккаунту в реестре.

JSON запрос (не меняется):
{
    "title": "Тест-драйв. Имя. Дата",
    "usernames": ["@acc1", "@acc2"]
}
"""
import asyncio
import logging
import threading
from typing import Any, Dict, List, Optional

import requests as http_requests
from flask import Blueprint, request, jsonify
from telethon import functions, types
from telethon.utils import get_peer_id

from core.bridge import TelethonBridge
from core.router import AccountRouter
from core.retry import run_with_retry
import config

logger = logging.getLogger("svc.create_chat")

bp = Blueprint("create_chat", __name__)
_router: Optional[AccountRouter] = None
_loop: Optional[asyncio.AbstractEventLoop] = None


def init(router: AccountRouter, loop: asyncio.AbstractEventLoop):
    global _router, _loop
    _router = router
    _loop = loop


def _run(coro, timeout=120):
    return asyncio.run_coroutine_threadsafe(coro, _loop).result(timeout=timeout)


# === Helpers (из оригинального create_chat) ===================================

async def _resolve_idents(bridge: TelethonBridge, idents: List[str]) -> Dict[str, Any]:
    out: Dict[str, Any] = {}
    for raw in idents:
        s = (raw or "").strip()
        if not s:
            continue
        try:
            ent = await bridge.get_entity(s)
            out[s] = ent
        except Exception as e:
            out[s] = {"error": str(e)}
    return out


async def _export_invite(bridge: TelethonBridge, channel: Any) -> Optional[str]:
    try:
        r = await bridge.client(
            functions.messages.ExportChatInviteRequest(peer=channel)
        )
        return getattr(r, "link", None)
    except Exception:
        return None


async def _promote_bot_admin(bridge: TelethonBridge, channel_peer: Any,
                             bot_user: types.User) -> str:
    rights_variants = []
    try:
        rights_variants.append(types.ChatAdminRights(
            change_info=True, post_messages=True, edit_messages=True,
            delete_messages=True, ban_users=True, invite_users=True,
            pin_messages=True, add_admins=True, anonymous=False,
            manage_call=True, manage_topics=True,
            post_stories=True, edit_stories=True, delete_stories=True,
        ))
    except TypeError:
        pass
    try:
        rights_variants.append(types.ChatAdminRights(
            change_info=True, post_messages=True, edit_messages=True,
            delete_messages=True, ban_users=True, invite_users=True,
            pin_messages=True, add_admins=True, anonymous=False,
            manage_call=True, manage_topics=True,
        ))
    except TypeError:
        pass
    try:
        rights_variants.append(types.ChatAdminRights(
            change_info=True, post_messages=True, edit_messages=True,
            delete_messages=True, ban_users=True, invite_users=True,
            pin_messages=True, add_admins=True, anonymous=False,
            manage_call=True,
        ))
    except TypeError:
        pass
    if not rights_variants:
        rights_variants.append(types.ChatAdminRights(
            change_info=True, delete_messages=True, ban_users=True,
            invite_users=True, pin_messages=True, add_admins=True,
            anonymous=False, manage_call=True,
        ))

    last_error = None
    for rights in rights_variants:
        try:
            iu = types.InputUser(bot_user.id, bot_user.access_hash)
            await bridge.client(functions.channels.EditAdminRequest(
                channel=channel_peer, user_id=iu,
                admin_rights=rights, rank="Admin Bot",
            ))
            return "ok"
        except Exception as e:
            last_error = e
    return f"error:{last_error}"


# === Основная логика ==========================================================

async def _create_chat_impl(bridge: TelethonBridge, title: str,
                             usernames: List[str]) -> Dict[str, Any]:
    debug: Dict[str, Any] = {"account": bridge.name, "idents_sample": usernames[:2]}

    # 1) Resolve users
    resolved = await _resolve_idents(bridge, usernames)
    ok_users: List[Any] = []
    resolve_failed: List[str] = []
    for k, v in resolved.items():
        if isinstance(v, dict) and "error" in v:
            resolve_failed.append(f"{k}: {v['error']}")
        else:
            ok_users.append(v)
    debug["resolve_failed"] = resolve_failed
    if not ok_users:
        return {"error": "no resolvable users", "debug": debug}

    # 2) Create supergroup
    upd = await bridge.client(functions.channels.CreateChannelRequest(
        title=title, about="", megagroup=True, for_import=False,
    ))

    # 3) Get channel entity
    channel_ent = None
    if getattr(upd, "chats", None):
        for c in upd.chats:
            if isinstance(c, types.Channel) and getattr(c, "megagroup", True):
                channel_ent = c
                break
    if channel_ent is None:
        return {"error": "cannot determine created supergroup", "debug": debug}

    channel_peer = channel_ent
    watched_id = get_peer_id(channel_ent)

    # 4) Open history
    try:
        await bridge.client(functions.channels.TogglePreHistoryHiddenRequest(
            channel=channel_peer, enabled=False,
        ))
        debug["open_history"] = "ok"
    except Exception as e:
        debug["open_history"] = f"error:{e}"

    # 5) Invite users + promote bots
    invite_failed: List[str] = []
    users_meta: List[types.User] = []
    try:
        batch = []
        for u in ok_users:
            ent = u
            if not hasattr(ent, "access_hash"):
                ent = await bridge.get_entity(u)
            if isinstance(ent, types.User):
                users_meta.append(ent)
            batch.append(types.InputUser(ent.id, ent.access_hash))
        if batch:
            await bridge.client(functions.channels.InviteToChannelRequest(
                channel=channel_peer, users=batch,
            ))
        debug["invite"] = "ok"
    except Exception as e:
        debug["invite"] = "error"
        invite_failed.append(str(e))
    debug["invite_failed"] = invite_failed

    # 5.1) Promote bots
    try:
        await asyncio.sleep(1)
        promote_results: List[str] = []
        for usr in users_meta:
            if getattr(usr, "bot", False):
                res = await _promote_bot_admin(bridge, channel_peer, usr)
                promote_results.append(f"@{usr.username or usr.id}: {res}")
        debug["promote_bots"] = promote_results or ["no_bots_detected"]
    except Exception as e:
        debug["promote_bots_error"] = str(e)

    # 5.2) Invite AMO observer (if chat created by non-main account)
    if config.AMO_OBSERVER_USERNAME and bridge.account_name != "main":
        try:
            amo_user = await bridge.get_entity(config.AMO_OBSERVER_USERNAME)
            amo_input = types.InputUser(amo_user.id, amo_user.access_hash)
            invite_result = await bridge.client(functions.channels.InviteToChannelRequest(
                channel=channel_peer, users=[amo_input],
            ))
            # Check missing_invitees — users blocked by privacy settings
            missing = getattr(invite_result, 'missing_invitees', [])
            if missing:
                debug["amo_invite"] = f"missing:{[getattr(m,'user_id','?') for m in missing]}"
                logger.warning("AMO observer %s MISSING (privacy?) in chat %s: %s",
                               config.AMO_OBSERVER_USERNAME, watched_id, missing)
            else:
                debug["amo_invite"] = "ok"
                logger.info("AMO observer %s invited OK into chat %s (bridge=%s)",
                            config.AMO_OBSERVER_USERNAME, watched_id, bridge.name)
        except Exception as e:
            debug["amo_invite"] = f"error:{e}"
            logger.warning("Failed to invite AMO observer %s into chat %s: %s",
                           config.AMO_OBSERVER_USERNAME, watched_id, e)
    else:
        logger.info("AMO observer skip: username=%s, account=%s",
                    config.AMO_OBSERVER_USERNAME, bridge.account_name)

    # 6) Invite link
    invite_link = await _export_invite(bridge, channel_peer) or None
    debug["export_invite"] = "ok" if invite_link else "none"

    return {
        "status": "ok",
        "title": title,
        "chat_id": str(watched_id),
        "invite_link": invite_link,
        "debug": debug,
    }


# === Salebot callback =========================================================

def _send_salebot_callback(client_tg_id: str, invite_link: str):
    """Отправляет callback в salebot с invite_link (в фоновом потоке, не блокирует ответ)."""
    def _do_send():
        payload = {
            "message": "send_invite_link",
            "user_id": client_tg_id,
            "group_id": config.SALEBOT_GROUP_ID,
            "tg_business": 1,
            "invite_link": invite_link,
        }
        try:
            resp = http_requests.post(
                config.SALEBOT_CALLBACK_URL,
                json=payload,
                timeout=15,
            )
            logger.info("salebot callback sent: status=%s body=%s", resp.status_code, resp.text[:200])
        except Exception as e:
            logger.error("salebot callback failed: %s", e)
            try:
                _router.registry.save_failed_request(
                    service="salebot_callback", endpoint=config.SALEBOT_CALLBACK_URL,
                    request_payload=payload, error=str(e),
                    direction="outbound",
                )
            except Exception:
                pass

    threading.Thread(target=_do_send, daemon=True).start()


# === HTTP endpoint ============================================================

@bp.route("/create_chat", methods=["POST"])
def create_chat():
    if _router is None:
        return jsonify({"error": "not initialized"}), 503

    data = request.get_json(force=True, silent=True) or {}
    title: str = (data.get("title") or "").strip()
    usernames: List[str] = data.get("usernames") or []
    client_tg_id: str = str(data.get("client_tg_id") or "").strip()

    if not title:
        return jsonify({"error": "title is required"}), 400
    if not usernames or not isinstance(usernames, list):
        return jsonify({"error": "usernames (array) is required"}), 400

    try:
        bridge = _router.pick_for_create(service="create_chat")
    except RuntimeError as e:
        return jsonify({"error": str(e)}), 503

    try:
        result = _run(
            run_with_retry(_create_chat_impl, bridge.client, bridge, title, usernames),
            timeout=120,
        )

        if "error" in result and result.get("status") != "ok":
            return jsonify(result), 400 if "no resolvable" in result.get("error", "") else 500

        # Привязываем чат к аккаунту
        chat_id = result.get("chat_id", "")
        if chat_id:
            _router.registry.assign(
                chat_id, bridge.account_name,
                title=title,
                invite_link=result.get("invite_link") or "",
            )
        _router.handle_success(bridge, chat_id, "create_chat")

        # Отправляем callback в salebot
        invite_link = result.get("invite_link") or ""
        if client_tg_id and invite_link:
            _send_salebot_callback(client_tg_id, invite_link)

        return jsonify(result)

    except Exception as e:
        _router.handle_error(bridge, e, "", "create_chat")

        # Попробовать failover через ВСЕ оставшиеся здоровые аккаунты
        fallbacks = _router.pool.get_all_healthy_except("create_chat", exclude_key=bridge.name)
        for fallback in fallbacks:
            try:
                logger.warning("create_chat failover: %s → %s", bridge.name, fallback.name)
                result = _run(
                    run_with_retry(
                        _create_chat_impl, fallback.client,
                        fallback, title, usernames,
                    ),
                    timeout=120,
                )
                if result.get("status") == "ok":
                    chat_id = result.get("chat_id", "")
                    if chat_id:
                        _router.registry.assign(
                            chat_id, fallback.account_name,
                            title=title,
                            invite_link=result.get("invite_link") or "",
                        )
                    _router.handle_success(fallback, chat_id, "create_chat")

                    invite_link = result.get("invite_link") or ""
                    if client_tg_id and invite_link:
                        _send_salebot_callback(client_tg_id, invite_link)

                    return jsonify(result)
            except Exception as e2:
                _router.handle_error(fallback, e2, "", "create_chat")
                continue

        # Все аккаунты отказали — сохраняем для повтора
        try:
            _router.registry.save_failed_request(
                service="create_chat", endpoint="/create_chat",
                request_payload=data, error=str(e),
            )
        except Exception:
            pass
        return jsonify({"error": str(e)}), 500
