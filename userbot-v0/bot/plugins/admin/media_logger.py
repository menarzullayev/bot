# bot/plugins/admin/media_logger.py
"""
Belgilangan chatlardan kelgan media fayllarni (rasm, video, hujjat)
maxsus log kanaliga saqlaydigan plagin. Albomlarni qo'llab-quvvatlaydi
va himoyalangan kontentni yuklab olib qayta yuboradi.
"""

import asyncio
import html
from collections import defaultdict
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Tuple, cast

from loguru import logger
from telethon import TelegramClient, events
from telethon.tl.custom import Message
from telethon.tl.types import User, DocumentAttributeFilename

from core.app_context import AppContext
from bot.decorators import userbot_cmd
from bot.lib.auth import admin_only, owner_only
from bot.lib.telegram import get_account_id, get_user, resolve_entity, get_display_name, get_message_link
from bot.lib.ui import format_error, format_success, PaginationHelper

# --- Konfiguratsiya va Global o'zgaruvchilar ---
grouped_albums: Dict[Tuple[int, int], List[Message]] = defaultdict(list)
grouped_tasks: Dict[Tuple[int, int], asyncio.Task] = {}


# ===== Asosiy Mantiq =====

async def _should_log_media(context: AppContext, event: events.NewMessage.Event) -> Optional[Dict]:
    """Medialarni loglash uchun asosiy filtr funksiyasi."""
    if not (event.media and event.sender_id and event.client and not event.out):
        return None

    sender = await event.get_sender()
    if not isinstance(sender, User) or sender.bot:
        return None
        
    account_id = await get_account_id(context, event.client)
    if not account_id:
        return None

    settings = await context.db.fetchone("SELECT * FROM media_logger_account_settings WHERE account_id = ?", (account_id,))
    log_channel_id = settings.get("log_channel_id") if settings else None
    if not log_channel_id:
        return None

    chat_setting = await context.db.fetchone("SELECT is_enabled FROM media_log_chat_settings WHERE account_id = ? AND chat_id = ?", (account_id, event.chat_id))
    
    should_log = False
    if chat_setting is not None:
        should_log = bool(chat_setting['is_enabled'])
    elif event.is_private and settings:
        should_log = bool(settings.get("log_all_private", False))

    if should_log:
        return {'acc_id': account_id, 'sender': sender, 'log_channel_id': log_channel_id}
    return None

@userbot_cmd(listen=events.NewMessage(incoming=True, forwards=False))
async def global_media_logger(event: events.NewMessage.Event, context: AppContext):
    """Barcha kiruvchi medialarni tutib oluvchi asosiy handler."""
    log_data = await _should_log_media(context, event)
    if not log_data:
        return

    album_key = (log_data['acc_id'], event.grouped_id) if event.grouped_id else None

    if album_key:
        if album_key in grouped_tasks:
            grouped_tasks[album_key].cancel()
        
        grouped_albums[album_key].append(event.message)
        
        async def process_album_after_timeout():
            await asyncio.sleep(2.5)
            items = grouped_albums.pop(album_key, [])
            grouped_tasks.pop(album_key, None)
            if not items: return
            await _process_media_group(context, items, log_data['sender'], log_data['log_channel_id'], log_data['acc_id'])
        
        grouped_tasks[album_key] = asyncio.create_task(process_album_after_timeout())
    else:
        await _process_media_group(context, [event.message], log_data['sender'], log_data['log_channel_id'], log_data['acc_id'])


async def _process_media_group(context: AppContext, messages: List[Message], sender: User, log_channel_id: int, acc_id: int):
    """Media guruhini (yoki yagona mediani) qayta ishlaydi."""
    first_msg = messages[0]
    client = first_msg.client
    if not client: return

    is_ttl = first_msg.ttl_period is not None

    try:
        if not first_msg.chat: return
        
        fwd_msgs = await client.forward_messages(log_channel_id, messages=messages, from_peer=first_msg.chat)
        if not fwd_msgs: raise ValueError("Forwarding returned no messages.")

        reply_to_msg = cast(Message, fwd_msgs[-1] if isinstance(fwd_msgs, list) else fwd_msgs)
        info_text = await _create_log_caption(context, client, sender, first_msg, is_ttl)
        
        await client.send_message(log_channel_id, info_text, reply_to=reply_to_msg.id, parse_mode="html", link_preview=False)
        for msg in messages: await _log_media_to_db(context, acc_id, msg)
        return
    except Exception as err:
        logger.warning(f"Media forward qilinmadi ({len(messages)}ta): {err}. Yuklab yuborishga uriniladi.")
        for msg in messages:
            await _download_and_resend(context, msg, sender, log_channel_id, acc_id, is_ttl)
            
async def _download_and_resend(context: AppContext, msg: Message, sender: User, log_channel_id: int, acc_id: int, is_ttl: bool):
    """Medianı serverga yuklab olib, log kanaliga qayta yuboradi."""
    try:
        media_content = await msg.download_media(file=bytes)
        if not (media_content and msg.client): return

        caption = await _create_log_caption(context, msg.client, sender, msg, is_ttl)
        
        file_name = "media"
        if msg.document and msg.document.attributes:
            for attr in msg.document.attributes:
                if isinstance(attr, DocumentAttributeFilename):
                    file_name = attr.file_name
                    break
        
        await msg.client.send_file(log_channel_id, file=media_content, caption=caption, parse_mode="html", attributes=msg.document.attributes if msg.document else None, force_document=True)
        await _log_media_to_db(context, acc_id, msg)
    except Exception as err:
        logger.critical(f"Faylni qayta yuborishda xatolik: {err}")

async def _log_media_to_db(context: AppContext, acc_id: int, msg: Message):
    """Media haqidagi ma'lumotni ma'lumotlar bazasiga yozadi."""
    m_type = msg.file.mime_type if msg.file else "unknown"
    await context.db.execute(
        "INSERT INTO logged_media (account_id, source_chat_id, sender_id, media_type, file_name, file_size) VALUES (?, ?, ?, ?, ?, ?)",
        (acc_id, msg.chat_id, msg.sender_id, m_type, getattr(msg.file, 'name', 'N/A'), getattr(msg.file, 'size', 0)),
    )

async def _create_log_caption(context: AppContext, client: TelegramClient, sender: User, msg: Message, is_ttl: bool) -> str:
    """Log xabari uchun sarlavha (caption) yaratadi."""
    if not msg.chat_id: return ""
    
    chat = await resolve_entity(context, client, msg.chat_id)
    chat_info = f"<a href='{get_message_link(msg)}'>{get_display_name(chat)}</a>" if chat else f"<code>{msg.chat_id}</code>"
    
    header = "⚠️ <b>Vaqtinchalik media saqlandi</b>" if is_ttl else "ℹ️ <b>Media saqlandi</b>"
    
    return "\n".join(filter(None, [
        header, "",
        f"👤 <b>Kimdan:</b> <a href='tg://user?id={sender.id}'>{get_display_name(sender)}</a>",
        f"📍 <b>Chat:</b> {chat_info}",
        f"📝 <b>Text:</b> {html.escape(msg.text)}" if msg.text else None,
        f"📅 <b>Vaqt:</b> <code>{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}</code>"
    ]))


# ===== Boshqaruv Buyruqlari =====

@userbot_cmd(command="setmedialog", description="Har bir akkaunt uchun alohida media log kanalini o'rnatadi.")
@owner_only
async def set_media_log_channel_handler(event: Message, context: AppContext):
    """ .setmedialog @MyLogChannel """
    if not event.text or not event.client: return
    
    target_str = event.text.split(maxsplit=1)[1] if len(event.text.split()) > 1 else ""
    if not target_str:
        return await event.edit(format_error("Log kanalining ID yoki @username'ini kiriting."))

    account_id = await get_account_id(context, event.client)
    if not account_id:
        return await event.edit(format_error("Akkauntni aniqlab bo'lmadi."))

    await event.edit(f"<code>🔄 {html.escape(target_str)} tekshirilmoqda...</code>")
    try:
        entity = await resolve_entity(context, event.client, target_str)
        if not entity:
            return await event.edit(format_error(f"Kanal topilmadi: `{target_str}`"))
        
        await context.db.execute(
            "REPLACE INTO media_logger_account_settings (account_id, log_channel_id) VALUES (?, ?)",
            (account_id, entity.id)
        )
        await event.edit(format_success(f"Media-log kanali o'rnatildi!\n<b>Kanal:</b> {get_display_name(entity)}"))
    except Exception as err:
        await event.edit(format_error(f"Kanalni o'rnatishda xato: {err}"))

@userbot_cmd(command="logmedia", description="Chatlar uchun loglashni yoqadi/o'chiradi.")
@admin_only
async def media_logger_manager_handler(event: Message, context: AppContext):
    """
    .logmedia on/off          # Joriy chat uchun
    .logmedia pm on/off       # Barcha shaxsiy xabarlar uchun
    """
    if not event.text or not event.client or not event.chat_id: return

    parts = event.text.split()
    if len(parts) < 2:
        return await event.edit(format_error("Noto'g'ri format. Misol: <code>.logmedia on</code>"))

    action, target = parts[1].lower(), (parts[2].lower() if len(parts) > 2 else "current")
    if action not in ["on", "off"]:
        action, target = target, action

    account_id = await get_account_id(context, event.client)
    if not account_id:
        return await event.edit(format_error("Akkaunt topilmadi. "))

    is_enabled = action == 'on'
    status_txt = "✅ Yoqildi" if is_enabled else "❌ O'chirildi"

    if target == 'pm':
        await context.db.execute("REPLACE INTO media_logger_account_settings (account_id, log_all_private) VALUES (?, ?)", (account_id, is_enabled))
        return await event.edit(format_success(f"Barcha shaxsiy xabarlar uchun media-log: {status_txt}"))

    await context.db.execute(
        "REPLACE INTO media_log_chat_settings (account_id, chat_id, is_enabled) VALUES (?, ?, ?)",
        (account_id, event.chat_id, is_enabled)
    )
    await event.edit(format_success(f"Ushbu chat uchun media-logger: {status_txt}"))


@userbot_cmd(command="logmedialist", description="Media-logger sozlamalari ro'yxatini ko'rsatadi.")
@admin_only
async def media_logger_lister_handler(event: Message, context: AppContext):
    if not event.client: return
    
    account_id = await get_account_id(context, event.client)
    if not account_id:
        return await event.edit(format_error("Akkaunt topilmadi."))
    
    await event.edit("<code>🔄 Sozlamalar ro'yxati olinmoqda...</code>")
    
    acc_settings = await context.db.fetchone("SELECT log_all_private FROM media_logger_account_settings WHERE account_id = ?", (account_id,))
    pm_status = "✅ Yoqilgan" if acc_settings and acc_settings.get("log_all_private") else "❌ O'chirilgan"
    
    resp_parts = [f"📝 <b>Media-logger Sozlamalari:</b>\n\nGlobal (Shaxsiy): <b>{pm_status}</b>\n"]
    
    chat_settings = await context.db.fetchall("SELECT chat_id, is_enabled FROM media_log_chat_settings WHERE account_id = ?", (account_id,))
    if not chat_settings:
        return await event.edit(resp_parts[0] + "\nMaxsus chat sozlamalari yo'q.")
        
    enabled, disabled = [], []
    for item in chat_settings:
        try:
            chat = await resolve_entity(context, event.client, item['chat_id'])
            if not chat: continue
            info = f"• {get_display_name(chat)} (<code>{item['chat_id']}</code>)"
            (enabled if item['is_enabled'] else disabled).append(info)
        except Exception: continue
    
    if enabled: resp_parts.append("\n<b>Maxsus Yoqilgan:</b>\n" + "\n".join(enabled))
    if disabled: resp_parts.append("\n<b>Maxsus O'chirilgan:</b>\n" + "\n".join(disabled))
    
    await event.edit("\n".join(resp_parts))

@userbot_cmd(command="logmedia purge", description="Ma'lumotlar bazasidan eski media yozuvlarini o'chiradi.")
@owner_only
async def purge_media_logs_handler(event: Message, context: AppContext):
    if not event.client: return
    account_id = await get_account_id(context, event.client)
    if not account_id:
        return await event.edit(format_error("Akkaunt topilmadi."))
    
    await event.edit("🔄 Ma'lumotlar bazasidan eski yozuvlar o'chirilmoqda...")
    
    success = await context.tasks.run_task_manually('media.purge_old_logs', account_id=account_id)
    
    if success:
        await event.edit(format_success("✅ Baza tozalash vazifasi navbatga qo'yildi. Natija birozdan so'ng loglarda ko'rinadi."))
    else:
        await event.edit(format_error("Vazifani ishga tushirib bo'lmadi."))


# ===== Tizim Vazifalari =====

async def purge_old_media_logs_task(context: AppContext, **kwargs) -> int:
    """
    Bu fon vazifasi. `context` obyekti unga avtomatik uzatiladi.
    `kwargs` ichida `account_id` bo'lishi mumkin.
    """
    cleanup_days = context.config.get("MEDIA_LOG_PURGE_DAYS", 7)
    three_days_ago = datetime.now() - timedelta(days=cleanup_days)
    
    account_id = kwargs.get('account_id')
    
    if account_id:
        sql, params = "DELETE FROM logged_media WHERE timestamp < ? AND account_id = ?", (three_days_ago, account_id)
        logger.info(f"{account_id}-akkaunt uchun eski media loglari o'chirilmoqda...")
    else:
        sql, params = "DELETE FROM logged_media WHERE timestamp < ?", (three_days_ago,)
        logger.info("Barcha akkauntlar uchun eski media loglari o'chirilmoqda...")

    deleted_rows = await context.db.execute(sql, params)
    logger.success(f"✅ Media loglar bazasi tozalandi. {deleted_rows} ta eski yozuv o'chirildi.")
    return deleted_rows


def register_plugin_tasks(context: AppContext):
    """Bu plaginga tegishli fon vazifalarini ro'yxatdan o'tkazadi."""
    context.tasks.register(
        key="media.purge_old_logs",
        description="DBdan eski media yozuvlarini o'chiradigan fon vazifasi."
    )(purge_old_media_logs_task)
