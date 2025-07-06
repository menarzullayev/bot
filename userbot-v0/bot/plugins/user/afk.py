# bot/plugins/user/afk.py
"""
AFK (Away From Keyboard) rejimini boshqarish uchun plagin (To'liq modernizatsiya qilingan).
"""

import html
from collections import defaultdict
from datetime import datetime
from typing import Dict, List, Optional

from loguru import logger
from telethon import TelegramClient, events
from telethon.tl.custom import Message
from telethon.tl.types import User

from core.app_context import AppContext
from bot.decorators import userbot_cmd
from bot.lib.telegram import get_account_id, get_user, get_display_name, resolve_entity, get_message_link
from bot.lib.ui import format_error, format_success, send_as_file_if_long, PaginationHelper

DEFAULT_AFK_REASON = "Hozir bandman. Tez orada javob beraman."


# ===== Asosiy Mantiq (Hodisa Ishlovchisi) =====

async def _should_reply_afk(context: AppContext, event: events.NewMessage.Event) -> Optional[Dict]:
    """AFK javob berish kerak yoki kerakmasligini tekshiruvchi filtr."""
    client = event.client
    if not (client and event.message and event.sender_id and not event.out):
        return None

    account_id = await get_account_id(context, client)
    if not account_id: return None

    logger.debug(f"[AFK_CHECK] AccID {account_id} uchun AFK holati tekshirilmoqda...")
    afk_settings = await context.db.fetchone("SELECT * FROM afk_settings WHERE account_id = ? AND is_afk = 1", (account_id,))
    if not afk_settings:
        logger.debug("[AFK_CHECK] AFK rejimi aktiv emas.")
        return None
    logger.debug(f"[AFK_CHECK] AFK sozlamalari topildi: {dict(afk_settings)}")

    sender = await event.get_sender()
    if not isinstance(sender, User) or sender.bot or sender.is_self:
        logger.debug(f"[AFK_CHECK] Yuboruvchi yaroqsiz (bot, self, or not User): {sender.id if sender else 'N/A'}")
        return None

    is_private = event.is_private
    is_mentioned = event.mentioned and afk_settings.get("groups_enabled", False)
    logger.debug(f"[AFK_CHECK] is_private={is_private}, is_mentioned={is_mentioned}")
    if not (is_private or is_mentioned):
        return None

    is_ignored = await context.db.fetchone("SELECT 1 FROM afk_ignored_users WHERE owner_account_id = ? AND ignored_user_id = ?", (account_id, sender.id))
    if is_ignored:
        logger.debug(f"[AFK_CHECK] Foydalanuvchi {sender.id} istisnolarda.")
        return None
    
    return {'settings': dict(afk_settings), 'sender': sender, 'account_id': account_id}


@userbot_cmd(listen=events.NewMessage(incoming=True, forwards=False))
async def afk_response_handler(event: events.NewMessage.Event, context: AppContext):
    """AFK rejimida bo'lganda kelgan xabarlarga javob beradi."""
    reply_data = await _should_reply_afk(context, event)
    if not reply_data:
        return

    afk_settings = reply_data['settings']
    sender = reply_data['sender']
    account_id = reply_data['account_id']
    
    try:
        mentions_count = await context.db.fetch_val(
            "SELECT COUNT(id) FROM afk_mentions WHERE afk_account_id = ? AND chatter_id = ?",
            (account_id, sender.id)
        ) or 0

        if mentions_count < 50:
            afk_since_str = afk_settings.get('afk_since')
            afk_since = datetime.fromisoformat(afk_since_str) if afk_since_str else datetime.now()
            reason = html.escape(afk_settings.get("reason") or DEFAULT_AFK_REASON)
            
            if mentions_count == 0:
                response_text = (
                    f"Salom! Men hozir bandman (<b>AFK</b>).\n\n"
                    f"<b>Sabab:</b> {reason}\n\n"
                    f"<i>{afk_since.strftime('%Y-%m-%d %H:%M')} dan beri</i>"
                )
                await event.reply(response_text, parse_mode='html')
            else:
                await event.reply(f"Sizga <b>{mentions_count + 1}-marta</b> eslatilmoqda, men hozir bandman (<b>AFK</b>).", parse_mode='html')

        await context.db.execute(
            "INSERT INTO afk_mentions (afk_account_id, chatter_id, chat_id, message_id, message_text) VALUES (?, ?, ?, ?, ?)",
            (account_id, sender.id, event.chat_id, event.id, event.text or "[Media]")
        )
    except Exception as e:
        logger.error(f"AFK javobini yuborishda xatolik: {e}")


# ===== Boshqaruv Buyruqlari =====

async def _generate_afk_report(context: AppContext, client: TelegramClient, account_id: int) -> str:
    """AFK rejimidan chiqqanda yig'ilgan murojaatlar haqida hisobot yaratadi."""
    mentions = await context.db.fetchall("SELECT * FROM afk_mentions WHERE afk_account_id = ? ORDER BY chatter_id, id", (account_id,))
    if not mentions:
        return "✅ <b>AFK rejimi o'chirildi.</b>\n\nSiz yo'g'ingizda hech kim bezovta qilmadi."

    report_parts = ["✅ <b>AFK rejimi o'chirildi.</b>\n\nSiz yo'g'ingizda quyidagilar esladi:"]
    mentions_by_user: Dict[int, List] = defaultdict(list)
    for m in mentions:
        mentions_by_user[m["chatter_id"]].append(m)

    chat_titles_cache: Dict[int, str] = {}

    for user_id, messages in mentions_by_user.items():
        user = await resolve_entity(context, client, user_id)
        user_link = f"<a href='tg://user?id={user_id}'>{html.escape(get_display_name(user))}</a>" if user else f"Noma'lum (<code>{user_id}</code>)"
        report_parts.append(f"\n• {user_link} ({len(messages)} marta):")
        
        for msg in messages:
            display_text = html.escape((msg["message_text"] or "[Media]")[:40])
            if len(msg["message_text"] or "") > 40: display_text += "..."
            
            chat_id = msg['chat_id']
            message_id = msg['message_id']
            chat_info_html = ""
            
            # YECHIM: Havolani to'g'ridan-to'g'ri shu yerda, aniq mantiq bilan yaratamiz
            if chat_id < 0:  # Guruh yoki kanal
                link_chat_id = str(chat_id).replace('-100', '')
                msg_link = f"https://t.me/c/{link_chat_id}/{message_id}"
                
                if chat_id not in chat_titles_cache:
                    try:
                        chat_entity = await resolve_entity(context, client, chat_id)
                        chat_titles_cache[chat_id] = get_display_name(chat_entity) if chat_entity else f"ID: {chat_id}"
                    except Exception:
                        chat_titles_cache[chat_id] = f"ID: {chat_id}"
                
                chat_name = chat_titles_cache.get(chat_id, "Noma'lum guruh")
                # Guruh nomini ham bosiladigan havola qilamiz
                chat_info_html = f" (<a href='{msg_link}'><b>{html.escape(chat_name)}</b></a>'da)"
            else:  # Shaxsiy xabar
                # Shaxsiy xabarlar uchun to'g'ridan-to'g'ri havola yo'q, shuning uchun havola shart emas
                msg_link = f"tg://user?id={user_id}"

            # Xabar matnini va guruh nomini (agar mavjud bo'lsa) bitta havola ichiga joylaymiz
            report_parts.append(f"   - <a href='{msg_link}'><i>{display_text}</i></a>{chat_info_html}")
    
    return "\n".join(report_parts)





@userbot_cmd(command="afk", description="AFK rejimini va uning sozlamalarini boshqaradi.")
async def afk_manager_handler(event: Message, context: AppContext):
    if not event.text or not event.client or not event.sender_id: return

    account_id = await get_account_id(context, event.client)
    if not account_id:
        return await event.edit(format_error("Akkauntni aniqlab bo'lmadi."), parse_mode='html')
    
    parts = event.text.split(maxsplit=1)
    args_str = parts[1] if len(parts) > 1 else ""
    subcommand = args_str.split()[0].lower() if args_str else "on"

    # YECHIM: Yagona va xavfsiz SQL so'rovini yaratish
    async def ensure_settings_exist():
        await context.db.execute("INSERT OR IGNORE INTO afk_settings (account_id) VALUES (?)", (account_id,))

    # OFF
    if subcommand == "off":
        if not await context.db.fetchone("SELECT 1 FROM afk_settings WHERE account_id = ? AND is_afk = 1", (account_id,)):
            return await event.delete()
        
        await event.edit("<code>🔄 AFK hisoboti tayyorlanmoqda...</code>", parse_mode='html')
        report_text = await _generate_afk_report(context, event.client, account_id)
        
        await context.db.execute("DELETE FROM afk_mentions WHERE afk_account_id = ?", (account_id,))
        await context.db.execute("UPDATE afk_settings SET is_afk = 0, reason = NULL, afk_since = NULL WHERE account_id = ?", (account_id,))
        return await send_as_file_if_long(event, report_text, filename="afk_report.html", parse_mode='html')

    # GROUPS
    elif subcommand == "groups":
        status_str = args_str.split()[1].lower() if len(args_str.split()) > 1 else ""
        if status_str not in ('on', 'off'):
            return await event.edit(format_error("<b>Format:</b> <code>.afk groups on|off</code>"), parse_mode='html')
        
        status = 1 if status_str == "on" else 0
        await ensure_settings_exist()
        await context.db.execute("UPDATE afk_settings SET groups_enabled = ? WHERE account_id = ?", (status, account_id))
        return await event.edit(format_success(f"Guruhlardagi AFK rejimi <b>{'yoqildi' if status else 'o\'chirildi'}</b>."), parse_mode='html')

    # IGNORELIST
    elif subcommand == "listignored":
        ignored_list_rows = await context.db.fetchall("SELECT ignored_user_id FROM afk_ignored_users WHERE owner_account_id = ?", (account_id,))
        if not ignored_list_rows:
            return await event.edit("ℹ️ AFK istisnolar ro'yxati bo'sh.", parse_mode='html')
        
        lines = []
        for item in ignored_list_rows:
            user_id = item['ignored_user_id']
            user_entity = await resolve_entity(context, event.client, user_id)
            user_link = f"<a href='tg://user?id={user_id}'>{html.escape(get_display_name(user_entity))}</a>" if user_entity else f"Noma'lum (<code>{user_id}</code>)"
            lines.append(f"• {user_link}")

        pagination = PaginationHelper(context=context, items=lines, title="🚫 AFK Istisnolar Ro'yxati", origin_event=event)
        return await pagination.start()

    # IGNORE / UNIGNORE
    elif subcommand in ("ignore", "unignore"):
        user_ref = args_str.split(maxsplit=1)[1] if len(args_str.split()) > 1 else ""
        if not user_ref:
            return await event.edit(format_error(f"Foydalanuvchi nomini yoki ID'sini kiriting."), parse_mode='html')
            
        user, error = await get_user(context, event, user_ref)
        if not user:
            return await event.edit(error or format_error("Foydalanuvchi topilmadi."), parse_mode='html')
            
        if subcommand == "ignore":
            await context.db.execute("REPLACE INTO afk_ignored_users (owner_account_id, ignored_user_id) VALUES (?, ?)", (account_id, user.id))
            return await event.edit(format_success(f"{get_display_name(user)} istisnolarga qo'shildi."), parse_mode='html')
        else: # unignore
            deleted_rows = await context.db.execute("DELETE FROM afk_ignored_users WHERE owner_account_id = ? AND ignored_user_id = ?", (account_id, user.id))
            if deleted_rows > 0:
                return await event.edit(format_success(f"{get_display_name(user)} istisnolardan o'chirildi."), parse_mode='html')
            else:
                return await event.edit(format_error(f"{get_display_name(user)} istisnolar ro'yxatida topilmadi."), parse_mode='html')
            
    # ON (AFK ni yoqish)
    else:
        reason = args_str or DEFAULT_AFK_REASON
        await ensure_settings_exist()
        await context.db.execute(
            "UPDATE afk_settings SET is_afk = 1, reason = ?, afk_since = ? WHERE account_id = ?",
            (reason, datetime.now(), account_id)
        )
        await event.edit(format_success(f"AFK rejimi yoqildi.\n<b>Sabab:</b> {html.escape(reason)}"), parse_mode='html')

