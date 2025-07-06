# bot/plugins/admin/health.py
"""
Userbot akkauntining salomatligi va statistikasi haqida umumiy hisobot
olish uchun mo'ljallangan admin plagini.
"""

import html
import time
from datetime import datetime, timezone
from typing import Dict, Union

from loguru import logger
from telethon import TelegramClient
from telethon.tl.custom import Message
from telethon.tl.functions.account import GetAuthorizationsRequest
from telethon.tl.types import User, Dialog
from telethon.tl.types.account import Authorizations as AccountAuthorizations

from core.app_context import AppContext
from bot.decorators import userbot_cmd
from bot.lib.auth import admin_only
from bot.lib.telegram import get_me, get_display_name

# ===== YORDAMCHI FUNKSIYALAR =====

def _is_muted(dialog: Dialog, now: datetime) -> bool:
    """Dialog ovozsiz qilinganini tekshiradi."""
    if (
        hasattr(dialog, "notify_settings")
        and dialog.notify_settings
        and hasattr(dialog.notify_settings, "mute_until")
        and dialog.notify_settings.mute_until
    ):
        return dialog.notify_settings.mute_until > now
    return False

async def _get_dialog_stats(client: TelegramClient, now: datetime) -> Dict[str, int]:
    """Dialoglar (chat, guruh, kanal) statistikasini hisoblaydi."""
    stats = {"users": 0, "groups": 0, "channels": 0, "muted": 0, "total": 0}
    async for dialog in client.iter_dialogs():
        if dialog.is_user:
            stats["users"] += 1
        elif dialog.is_group:
            stats["groups"] += 1
        elif dialog.is_channel:
            stats["channels"] += 1
        if _is_muted(dialog, now):
            stats["muted"] += 1
    stats["total"] = stats["users"] + stats["groups"] + stats["channels"]
    return stats

async def _get_session_info(client: TelegramClient) -> Dict[str, Union[int, str]]:
    """Faol seanslar soni va data markaz (DC) ID'sini oladi."""
    try:
        authorizations = await client(GetAuthorizationsRequest())
        if not isinstance(authorizations, AccountAuthorizations):
            logger.warning(f"Avtorizatsiyalar ro'yxatini olib bo'lmadi. Olingan tur: {type(authorizations)}")
            active_sessions = 0
        else:
            active_sessions = len(authorizations.authorizations)
    except Exception as e:
        logger.error(f"Faol seanslarni olishda xato: {e}")
        active_sessions = 0

    dc_id = getattr(client.session, 'dc_id', 'N/A')
    return {"dc_id": dc_id, "active_sessions": active_sessions}

def _generate_report_text(me: User, dialog_stats: dict, session_info: dict, duration: float) -> str:
    """Yakuniy hisobot matnini formatlaydi."""
    # TUZATISH: Ismni xavfsiz `get_display_name` orqali olamiz
    user_name = html.escape(get_display_name(me))
    
    return (
        f"🩺 <b>Akkaunt Salomatligi Hisoboti</b>\n\n"
        f"👤 <b>Foydalanuvchi:</b> <a href='tg://user?id={me.id}'>{user_name}</a>\n"
        f"🆔 <b>ID:</b> <code>{me.id}</code>\n"
        f"🌐 <b>Data Markaz (DC):</b> <code>{session_info['dc_id']}</code>\n\n"
        f"💬 <u><b>Dialoglar:</b></u>\n"
        f"  - <b>Jami:</b> <code>{dialog_stats['total']}</code>\n"
        f"  - <b>Shaxsiy chatlar:</b> <code>{dialog_stats['users']}</code>\n"
        f"  - <b>Guruhlar:</b> <code>{dialog_stats['groups']}</code>\n"
        f"  - <b>Kanallar:</b> <code>{dialog_stats['channels']}</code>\n"
        f"🤫 <b>Ovozsiz chatlar:</b> <code>{dialog_stats['muted']}</code>\n\n"
        f"💻 <b>Faol seanslar (shu qurilma bn birga):</b> <code>{session_info['active_sessions']}</code> ta\n\n"
        f"⏱️ <b>Tekshiruv vaqti:</b> <code>{duration:.2f}</code> soniya"
    )

# ===== ASOSIY BUYRUQ =====

@userbot_cmd(command="health", description="Akkaunt salomatligi haqida to'liq hisobot.")
@admin_only
async def health_check_handler(event: Message, context: AppContext):
    clients = context.client_manager.get_all_clients()
    if not clients:
        # TUZATISH: `parse_mode` qo'shildi
        return await event.edit("<b>❌ Hech qanday faol klient topilmadi.</b>", parse_mode='html')
    
    client = clients[0]
    start_time = time.time()
    # TUZATISH: `parse_mode` qo'shildi
    await event.edit("🩺 <b>Akkaunt salomatligi tekshirilmoqda...</b>\n\n<code>Dialoglar soni hisoblanmoqda...</code>", parse_mode='html')

    try:
        me = await get_me(context, client)
        if not me:
            raise TypeError("Foydalanuvchi ma'lumotlarini (get_me) olib bo'lmadi.")

        now = datetime.now(timezone.utc)
        dialog_stats = await _get_dialog_stats(client, now)

        # TUZATISH: `parse_mode` qo'shildi
        await event.edit(
            f"🩺 <b>Akkaunt salomatligi tekshirilmoqda...</b>\n\n"
            f"<code>Jami {dialog_stats['total']} ta dialog topildi.</code>\n"
            f"<code>Faol seanslar olinmoqda...</code>",
            parse_mode='html'
        )

        session_info = await _get_session_info(client)
        duration = time.time() - start_time
        report = _generate_report_text(me, dialog_stats, session_info, duration)

        # TUZATISH: `parse_mode` qo'shildi
        await event.edit(report, link_preview=False, parse_mode='html')

    except Exception as e:
        logger.exception("Salomatlik tekshiruvi plaginida xatolik yuz berdi.")
        # TUZATISH: `parse_mode` qo'shildi
        await event.edit(f"❌ <b>Xatolik yuz berdi:</b>\n<code>{html.escape(type(e).__name__)}: {html.escape(str(e))}</code>", parse_mode='html')

