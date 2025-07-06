# bot/plugins/admin/log_text_cmds.py
"""
Yangi, tahrirlangan va o'chirilgan xabarlarni maxsus log kanaliga
yuborish orqali akkaunt faoliyatini kuzatuvchi plagin.
"""

import asyncio
import html
import io
from collections import defaultdict
from typing import Dict, Set, Optional

from diff_match_patch import diff_match_patch
from loguru import logger
from telethon import TelegramClient, events
from telethon.tl.custom import Message
from telethon.tl.types import User, Channel, Chat

from core.app_context import AppContext
from bot.decorators import userbot_cmd
from bot.lib.auth import admin_only, owner_only
from bot.lib.telegram import get_account_id, get_user, resolve_entity, get_display_name, get_me
from bot.lib.ui import format_error, format_success

# --- Konstanta va sozlamalar ---
LOG_CACHE_TTL: int = 3 * 24 * 60 * 60  # 3 kun
MSG_CACHE_NAMESPACE: str = "log_text:msg"
DELETED_MAP_NAMESPACE: str = "log_text:del_map"
PM_LOGGING_MARKER: int = 0
DELETE_BATCH_WINDOW: float = 2.5  # O'chirilgan xabarlarni guruhlash uchun kutish vaqti
LARGE_TEXT_THRESHOLD: int = 3900 # Faylga yuborish uchun chegara

# --- Global o'zgaruvchilar (faqat shu modul uchun) ---
deleted_ids_batch: Dict[int, Set[int]] = defaultdict(set)
deleted_batch_lock: asyncio.Lock = asyncio.Lock()
deleted_batch_tasks: Dict[int, asyncio.Task] = {}

# ===== YORDAMCHI FUNKSIYALAR =====

async def _get_log_channel_id(context: AppContext) -> Optional[int]:
    channel_id_str = context.config.get("TEXT_LOG_CHANNEL")
    return int(channel_id_str) if channel_id_str and str(channel_id_str).lstrip('-').isdigit() else None

async def _send_to_log_channel(context: AppContext, client: TelegramClient, text: str, *, file: Optional[io.BytesIO] = None) -> None:
    log_channel_id = await _get_log_channel_id(context)
    if not log_channel_id:
        return logger.warning("Log kanaliga yuborib bo'lmadi: TEXT_LOG_CHANNEL o'rnatilmagan.")
    try:
        if file:
            await client.send_file(log_channel_id, file=file, caption=text, parse_mode="html")
        else:
            await client.send_message(log_channel_id, text, parse_mode="html", link_preview=False)
    except Exception:
        logger.exception(f"Log kanaliga ({log_channel_id}) yuborishda kutilmagan xatolik.")

def _generate_diff_html(text1: str, text2: str) -> str:
    dmp = diff_match_patch()
    diffs = dmp.diff_main(str(text1 or ""), str(text2 or ""))
    dmp.diff_cleanupSemantic(diffs)
    return dmp.diff_prettyHtml(diffs)

async def _get_log_header(context: AppContext, client: TelegramClient, peer_id: int, sender_id: Optional[int]) -> str:
    me = await get_me(context, client)
    account_info = f"<a href='tg://user?id={me.id}'>{get_display_name(me)}</a>" if me else "<i>Noma'lum Akkaunt</i>"

    sender_info = "<i>Noma'lum</i>"
    if sender_id:
        sender = await resolve_entity(context, client, sender_id)
        sender_info = f"<a href='tg://user?id={sender.id}'>{get_display_name(sender)}</a>" if sender else f"<code>{sender_id}</code>"

    chat_info = f"<code>{peer_id}</code>"
    chat = await resolve_entity(context, client, peer_id)
    if chat:
        chat_title = get_display_name(chat)
        # Pylance xatosini tuzatish: `Chat` obyektida `username` yo'q
        chat_username = getattr(chat, 'username', None)
        if chat_username:
            chat_info = f"<a href='https://t.me/{chat_username}'>{chat_title}</a>"
        elif isinstance(chat, (Channel, Chat)) and str(chat.id).startswith('-100'):
            chat_info = f"<a href='https://t.me/c/{str(chat.id).replace('-100', '')}/1'>{chat_title}</a>"
        else:
            chat_info = f"<b>{chat_title}</b>"
            
    return f"<b>🆔 Akkaunt:</b> {account_info}\n<b>👤 Kimdan:</b> {sender_info}\n<b>📍 Chat:</b> {chat_info}"



async def _should_log(context: AppContext, account_id: int, chat_id: int, user_id: Optional[int], is_private: bool) -> bool:
    ignored_users = await context.db.fetchall("SELECT user_id FROM text_log_ignored_users WHERE account_id = ?", (account_id,))
    if user_id and user_id in {u['user_id'] for u in ignored_users}:
        return False
        
    specific_setting = await context.db.fetchone("SELECT is_enabled FROM text_log_settings WHERE account_id = ? AND chat_id = ?", (account_id, chat_id))
    if specific_setting is not None:
        return bool(specific_setting['is_enabled'])
        
    pm_enabled = await context.db.fetchone("SELECT is_enabled FROM text_log_settings WHERE account_id = ? AND chat_id = ?", (account_id, PM_LOGGING_MARKER))
    return is_private and bool(pm_enabled and pm_enabled['is_enabled'])

# ===== HODISA ISHLOVCHILARI =====

@userbot_cmd(listen=events.NewMessage(incoming=True, forwards=False), description="Yangi xabarlarni log qiladi.")
async def on_new_message_handler(event: events.NewMessage.Event, context: AppContext):
    msg, client = event.message, event.client
    if not (client and msg and msg.text and event.chat_id and msg.sender_id and not msg.out):
        return

    account_id = await get_account_id(context, client)
    if not account_id: return
    
    # Pylance xatosini tuzatish: event.is_private None bo'lishi mumkin
    if event.is_private is None: return

    if not await _should_log(context, account_id, event.chat_id, msg.sender_id, event.is_private):
        return

    logger.debug(f"Yangi xabar (msg_id={msg.id}) log qilinmoqda...")
    # ... (qolgan qismi o'zgarishsiz)
    try:
        await context.cache.set(f"{account_id}:{event.chat_id}:{msg.id}", {"text": msg.text, "sender": msg.sender_id}, namespace=MSG_CACHE_NAMESPACE, ttl=LOG_CACHE_TTL)
        await context.cache.set(f"{account_id}:{msg.id}", event.chat_id, namespace=DELETED_MAP_NAMESPACE, ttl=LOG_CACHE_TTL)
        header = await _get_log_header(context, client, event.chat_id, msg.sender_id)
        log_body = f"{header}\n<a href='{msg.link}'>Yangi xabar keldi:</a>\n<blockquote>{html.escape(msg.text)}</blockquote>"
        await _send_to_log_channel(context, client, log_body)
    except Exception as e:
        logger.exception(f"Yangi xabarni log qilishda xato: {e}")




@userbot_cmd(listen=events.MessageEdited(incoming=True), description="Tahrirlangan xabarlarni log qiladi.")
async def on_message_edited_handler(event: events.MessageEdited.Event, context: AppContext):
    msg, client = event.message, event.client
    if not (client and msg and msg.text and event.chat_id and msg.sender_id and not msg.out):
        return

    account_id = await get_account_id(context, client)
    if not account_id: return

    # Pylance xatosini tuzatish: event.is_private None bo'lishi mumkin
    if event.is_private is None: return

    if not await _should_log(context, account_id, event.chat_id, msg.sender_id, event.is_private):
        return
        
    logger.debug(f"Tahrirlangan xabar (msg_id={msg.id}) log qilinmoqda...")
    try:
        cache_key = f"{account_id}:{event.chat_id}:{msg.id}"
        cached_data = await context.cache.get(cache_key, namespace=MSG_CACHE_NAMESPACE)
        if not (cached_data and 'text' in cached_data):
            return

        old_text, new_text = cached_data['text'], msg.text
        if old_text == new_text: return

        header = await _get_log_header(context, client, event.chat_id, msg.sender_id)
        diff_html = _generate_diff_html(old_text, new_text)
        log_body = f"{header}\n<a href='{msg.link}'>Xabar tahrirlandi:</a>\n\n{diff_html}"
        
        await _send_to_log_channel(context, client, log_body)
        cached_data['text'] = new_text
        await context.cache.set(cache_key, cached_data, namespace=MSG_CACHE_NAMESPACE, ttl=LOG_CACHE_TTL)
    except Exception as e:
        logger.exception(f"Tahrirlangan xabarni log qilishda xato: {e}")



# ===== HODISA ISHLOVCHILARI (DAVOMI) =====

@userbot_cmd(listen=events.MessageDeleted, description="O'chirilgan xabarlarni log qiladi.")
async def on_message_deleted_handler(event: events.MessageDeleted.Event, context: AppContext):
    # Bu hodisada `client` to'g'ridan-to'g'ri bo'lmasligi mumkin, uni `context`dan olamiz
    if not event.deleted_ids or not context.client_manager:
        return

    # Qaysi akkauntga tegishli ekanligini aniqlay olmaymiz,
    # shuning uchun barcha faol akkauntlar uchun tekshiramiz.
    # Kelajakda bu qismni optimallashtirish mumkin.
    for client in context.client_manager.get_all_clients():
        account_id = await get_account_id(context, client)
        if not account_id:
            continue
        
        async with deleted_batch_lock:
            deleted_ids_batch[account_id].update(event.deleted_ids)
            if account_id not in deleted_batch_tasks or deleted_batch_tasks[account_id].done():
                task = asyncio.create_task(process_deleted_batch(context, account_id))
                deleted_batch_tasks[account_id] = task

async def process_deleted_batch(context: AppContext, account_id: int):
    """O'chirilgan xabarlar to'plamini ma'lum bir vaqtdan so'ng qayta ishlaydi."""
    await asyncio.sleep(DELETE_BATCH_WINDOW)
    
    async with deleted_batch_lock:
        if account_id not in deleted_ids_batch: return
        message_ids = list(deleted_ids_batch.pop(account_id, set()))
        logger.info(f"{len(message_ids)} ta o'chirilgan xabar qayta ishlanmoqda (AccID: {account_id})")

    client = context.client_manager.get_client(account_id)
    if not client or not message_ids: return

    try:
        log_parts = []
        for msg_id in sorted(message_ids):
            map_key = f"{account_id}:{msg_id}"
            chat_id = await context.cache.get(key=map_key, namespace=DELETED_MAP_NAMESPACE)
            if not chat_id: continue

            cache_key = f"{account_id}:{chat_id}:{msg_id}"
            cached_data = await context.cache.get(key=cache_key, namespace=MSG_CACHE_NAMESPACE)
            if not cached_data: continue
            
            sender_id = cached_data.get("sender")
            if not await _should_log(context, account_id, chat_id, sender_id, chat_id > 0):
                continue
            
            header = await _get_log_header(context, client, chat_id, sender_id)
            message_text = html.escape(cached_data.get('text', ''))
            log_parts.append(f"{header}\n<blockquote>{message_text}</blockquote>")
        
        if log_parts:
            me = await get_me(context, client)
            account_name = get_display_name(me) if me else f"ID: {account_id}"
            log_header = f"🗑️ <b>{account_name}</b> akkauntida <b>{len(log_parts)} ta</b> xabar o'chirildi:\n{'-'*25}"
            full_log_body = log_header + "\n\n".join(log_parts)
            await _send_to_log_channel(context, client, full_log_body)
    except Exception as e:
        logger.exception(f"O'chirilgan xabarlarni qayta ishlashda xatolik: {e}")
    finally:
        async with deleted_batch_lock:
            deleted_batch_tasks.pop(account_id, None)

# ===== BOSHqaruv BUYRUQLARI =====

@userbot_cmd(command="logtext", description="Matn loggerini boshqaradi.")
@admin_only
async def logtext_manager_handler(event: Message, context: AppContext):
    """
    .logtext on [nishon]
    .logtext off pm
    .logtext status @username
    .logtext ignore @someuser
    .logtext unignore 12345678
    .logtext ignorelist
    .logtext help
    """
    if not (event.text and event.client): return
    
    parts = event.text.split(maxsplit=2)
    action = parts[1].lower() if len(parts) > 1 else "help"
    arg = parts[2] if len(parts) > 2 else ""
    
    account_id = await get_account_id(context, event.client)
    if not account_id:
        return await event.edit(format_error("Akkaunt ID'sini aniqlab bo'lmadi."))

    # .logtext on/off
    if action in ("on", "off"):
        enabled = action == "on"
        target_str = arg or "current"
        
        try:
            if target_str.lower() == "pm":
                target_id, chat_name = PM_LOGGING_MARKER, "barcha shaxsiy xabarlar"
            else:
# Pylance xatosini tuzatish: event.chat_id None bo'lishi mumkinligini tekshiramiz
                target_entity_resolvable = target_str if target_str != "current" else event.chat_id
                if not target_entity_resolvable:
                    return await event.edit(format_error("Joriy chatni aniqlab bo'lmadi."))

                entity = await resolve_entity(context, event.client, target_entity_resolvable)
                if not entity: return await event.edit(format_error(f"Nishon topilmadi: `{target_str}`"))
                target_id, chat_name = entity.id, get_display_name(entity)
        except Exception as e:
            return await event.edit(format_error(f"Nishonni aniqlashda xato: {e}"))

        await context.db.execute(
            "REPLACE INTO text_log_settings (account_id, chat_id, is_enabled) VALUES (?, ?, ?)",
            (account_id, target_id, enabled)
        )
        status_text = '✅ Yoqildi' if enabled else '🛑 O\'chirildi'
        return await event.edit(format_success(f"Matn loggeri <code>{html.escape(chat_name)}</code> uchun {status_text}."))

    # .logtext status
    if action == "status":
        target_str = arg or "current"
        try:
            if target_str.lower() == "pm":
                is_enabled = await _should_log(context, account_id, 0, None, True)
                chat_name, reason = "Barcha shaxsiy xabarlar", "Umumiy PM sozlamasi"
            else:
                target_entity_resolvable = target_str if target_str != "current" else event.chat_id
                if not target_entity_resolvable:
                    return await event.edit(format_error("Joriy chatni aniqlab bo'lmadi."))

                entity = await resolve_entity(context, event.client, target_entity_resolvable)
                if not entity: return await event.edit(format_error(f"Nishon topilmadi: `{target_str}`"))
                chat_name = get_display_name(entity)
                is_enabled = await _should_log(context, account_id, entity.id, None, isinstance(entity, User))
                reason = "Maxsus sozlama" if await context.db.fetchone("SELECT 1 FROM text_log_settings WHERE account_id=? AND chat_id=?", (account_id, entity.id)) else "Standart"

            status_text = '✅ Faol' if is_enabled else '🛑 Faol emas'
            return await event.edit(f"<b>📊 Logger holati:</b> <code>{html.escape(chat_name)}</code>\n<b>Natija:</b> {status_text} ({reason})")
        except Exception as e:
            return await event.edit(format_error(f"Holatni tekshirishda xato: {e}"))
            
    # .logtext ignore/unignore
    if action in ("ignore", "unignore"):
        user, error_msg = await get_user(context, event, arg)
        if not user:
            return await event.edit(error_msg or format_error("Foydalanuvchi topilmadi."))
        
        if action == "ignore":
            await context.db.execute("INSERT OR IGNORE INTO text_log_ignored_users (account_id, user_id) VALUES (?, ?)", (account_id, user.id))
            return await event.edit(format_success(f"🚫 {get_display_name(user)} e'tiborsizlar ro'yxatiga qo'shildi."))
        else: # unignore
            await context.db.execute("DELETE FROM text_log_ignored_users WHERE account_id = ? AND user_id = ?", (account_id, user.id))
            return await event.edit(format_success(f"✅ {get_display_name(user)} ro'yxatdan olindi."))

    # .logtext ignorelist
    if action == "ignorelist":
        ignored_rows = await context.db.fetchall("SELECT user_id FROM text_log_ignored_users WHERE account_id = ?", (account_id,))
        if not ignored_rows:
            return await event.edit("🚫 E'tiborsizlar ro'yxati bo'sh.")
        
        lines = ["<b>🚫 E'tiborsizlar ro'yxati:</b>"]
        for row in ignored_rows:
            user = await resolve_entity(context, event.client, row['user_id'])
            lines.append(f"- {get_display_name(user)} (<code>{row['user_id']}</code>)")
        return await event.edit("\n".join(lines))

    # .logtext help (or any other action)
    help_text = (
        "<b>Matnli Logger Plagini Yordami</b>\n\n"
        "• <code>.logtext on/off [nishon]</code> - Loggerni yoqish/o'chirish.\n"
        "• <code>.logtext status [nishon]</code> - Logger holatini tekshirish.\n"
        "• <code>.logtext ignore &lt;user&gt;</code> - Foydalanuvchini istisno qilish.\n"
        "• <code>.logtext unignore &lt;user&gt;</code> - Istisnodan chiqarish.\n"
        "• <code>.logtext ignorelist</code> - Istisno qilinganlar ro'yxati.\n"
        "• <code>.setlogchannel &lt;chat_id&gt;</code> - Loglar yuboriladigan kanalni o'rnatish.\n\n"
        "<b>[Nishon]:</b> <code>pm</code> (shaxsiy chatlar), <code>@username</code>, <code>chat_id</code>, yoki joriy chat."
    )
    await event.edit(help_text)


@userbot_cmd(command="setlogchannel", description="Matnli loglar uchun kanali o'rnatadi.")
@owner_only
async def set_text_log_channel_handler(event: Message, context: AppContext):
    if not event.text or not event.client: return
    
    channel_input = event.text.split(maxsplit=1)[1] if len(event.text.split()) > 1 else ""
    if not channel_input:
        return await event.edit(format_error("Kanal ID yoki @username kiriting."))

    await event.edit(f"<code>🔄 Kanal tekshirilmoqda: {channel_input}</code>")
    try:
        entity = await resolve_entity(context, event.client, channel_input)
        
        # Pylance xatosini tuzatish: to'g'ri tekshiruv `isinstance` bilan bajariladi
        if not isinstance(entity, (Chat, Channel)):
             return await event.edit(format_error("Ko'rsatilgan nishon kanal yoki guruh emas."))

        test_msg = await event.client.send_message(entity.id, "✅ Matn loggeri uchun log kanali muvaffaqiyatli o'rnatildi.")
        await context.config.set("TEXT_LOG_CHANNEL", str(entity.id))
        
        await test_msg.edit("✅ Matn loggeri uchun log kanali muvaffaqiyatli o'rnatildi.\nBarcha matnli loglar shu yerga yuboriladi.")
        await event.delete()
    except Exception as e:
        logger.exception("Log kanalini o'rnatishda xato")
        await event.edit(format_error(f"Kanalni o'rnatishda xato: {e}"))
