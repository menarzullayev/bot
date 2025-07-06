# bot/plugins/user/info.py
"""
Foydalanuvchi, chat yoki kanal haqida to'liq ma'lumot olish uchun mo'ljallangan plagin.
"""

import html
import io
import json
from datetime import datetime, timezone
from typing import Optional, Union

from loguru import logger
from telethon.tl.custom import Message
from telethon.tl import functions
from telethon.tl.types import (
    Channel, Chat, User,
    UserStatusOffline, UserStatusOnline, UserStatusRecently, UserFull
)

from core.app_context import AppContext
from bot.decorators import userbot_cmd
from bot.lib.telegram import (
    get_user, resolve_entity, get_display_name
)
from bot.lib.ui import format_error, send_as_file_if_long, bold, code

# --- YORDAMCHI FUNKSIYALAR ---

def _format_timedelta(delta: Optional[datetime]) -> str:
    """Vaqt oralig'ini (timedelta) o'qish uchun qulay formatga o'tkazadi."""
    if not delta:
        return "uzoq vaqt oldin"
    
    now = datetime.now(timezone.utc)
    diff = now - delta
    seconds = diff.total_seconds()
    
    if seconds < 60: return "hozir onlayn"
    if seconds < 3600: return f"{int(seconds / 60)} daqiqa oldin"
    if seconds < 86400: return f"{int(seconds / 3600)} soat oldin"
    return delta.strftime('%Y-%m-%d %H:%M')

def _format_user_info(user: User, full_user_info: Optional[UserFull]) -> str:
    """Foydalanuvchi ma'lumotlarini formatlab, matn ko'rinishida qaytaradi."""
    display_name = html.escape(get_display_name(user))
    
    lines = [f"<b>ℹ️ Foydalanuvchi:</b> {bold(display_name)}"]
    lines.append(f"<b>ID:</b> {code(user.id)}")
    if user.username:
        lines.append(f"<b>Username:</b> @{user.username}")

    status = user.status
    if isinstance(status, UserStatusOnline):
        lines.append("<b>Status:</b> 🟢 Onlayn")
    elif isinstance(status, UserStatusOffline):
        lines.append(f"<b>Oxirgi faollik:</b> ⚪️ {_format_timedelta(status.was_online)}")
    elif isinstance(status, UserStatusRecently):
        lines.append("<b>Status:</b> 🟡 Yaqinda onlayn bo'lgan")
    
    # YECHIM: `full_user_info` obyektidan to'g'ridan-to'g'ri foydalanamiz
    if full_user_info and (about := getattr(full_user_info, 'about', None)):
        lines.append(f"<b>Bio:</b> <i>{html.escape(about)}</i>")
        
    lines.append(f"<b>Bot:</b> {'Ha' if user.bot else 'Yoʻq'}")
    if user.scam: lines.append("<b>Scam:</b> ❗️ Ha")
    
    if full_user_info and (common_chats := getattr(full_user_info, 'common_chats_count', None)) is not None:
        lines.append(f"<b>Umumiy chatlar:</b> {common_chats}")
    
    lines.append(f"<b>Havola:</b> <a href='tg://user?id={user.id}'>profilga o'tish</a>")
    return "\n".join(lines)


def _format_chat_info(chat: Union[Chat, Channel], full_chat_info) -> str:
    """Chat/Kanal ma'lumotlarini formatlab, matn ko'rinishida qaytaradi."""
    chat_type = "Kanal" if isinstance(chat, Channel) and not getattr(chat, 'megagroup', False) else "Guruh"
    
    lines = [f"<b>ℹ️ {chat_type}:</b> {bold(html.escape(get_display_name(chat)))}"]
    lines.append(f"<b>ID:</b> {code(chat.id)}")
    
    if username := getattr(chat, 'username', None):
        lines.append(f"<b>Username:</b> @{username}")

    full_chat = getattr(full_chat_info, 'full_chat', None)
    if full_chat:
        if about := getattr(full_chat, 'about', None):
            lines.append(f"<b>Tavsif:</b> <i>{html.escape(about)}</i>")
        if participants_count := getattr(full_chat, 'participants_count', None):
            lines.append(f"<b>A'zolar:</b> {participants_count}")
            
    return "\n".join(lines)


# --- ASOSIY BUYRUQLAR ---

@userbot_cmd(command="info", description="Foydalanuvchi yoki chat haqida to'liq ma'lumot oladi.")
async def info_handler(event: Message, context: AppContext):
    if not event.client or not event.text: return
    
    args_raw = event.text.split(maxsplit=1)[1] if len(event.text.split()) > 1 else ""
    is_json = '--json' in args_raw
    args = args_raw.replace('--json', '').strip()

    await event.edit("<i>🔄 Ma'lumotlar olinmoqda...</i>", parse_mode='html')

    entity_resolvable = args or event.reply_to_msg_id or event.chat_id
    if not entity_resolvable:
        return await event.edit(format_error("Nishonni aniqlab bo'lmadi."), parse_mode='html')

    try:
        target_entity = await resolve_entity(context, event.client, entity_resolvable)
    except Exception as e:
        return await event.edit(format_error(f"Nishonni aniqlashda xato: {e}"), parse_mode='html')
        
    if not target_entity:
        return await event.edit(format_error("Nishon topilmadi yoki unga kirish imkoni yo'q."), parse_mode='html')

    full_object = None
    try:
        input_entity = await event.client.get_input_entity(target_entity)
        if isinstance(target_entity, User):
            full_object = await event.client(functions.users.GetFullUserRequest(id=input_entity))
        elif isinstance(target_entity, (Chat, Channel)):
            full_object = await event.client(functions.channels.GetFullChannelRequest(channel=input_entity))
    except Exception as e:
        logger.warning(f"To'liq ma'lumot olishda xato: {e}")

    if is_json:
        if full_object:
            json_data = json.dumps(full_object.to_dict(), indent=2, default=str, ensure_ascii=False)
            return await send_as_file_if_long(event, json_data, filename=f"info_{getattr(target_entity, 'id', 'unknown')}.json", caption="To'liq ma'lumotlar.")
        return await event.edit(format_error("JSON ma'lumotlarni yaratib bo'lmadi."), parse_mode='html')
    
    info_text = "Ma'lumot topilmadi."
    if isinstance(target_entity, User):
        info_text = _format_user_info(target_entity, full_object)
    elif isinstance(target_entity, (Chat, Channel)):
        info_text = _format_chat_info(target_entity, full_object)
        
    try:
        photo_bytes = await event.client.download_profile_photo(target_entity, file=bytes)
        if photo_bytes:
            await event.delete()
            return await event.client.send_file(
                event.chat_id, file=photo_bytes, caption=info_text, reply_to=event.reply_to_msg_id, parse_mode='html'
            )
    except Exception as e:
        logger.warning(f"Profil rasmini yuklab bo'lmadi: {e}")

    await event.edit(info_text, parse_mode='html')


@userbot_cmd(command="id", description="Joriy chat, javob berilgan xabar/foydalanuvchi ID'sini yuboradi.")
async def id_handler(event: Message, context: AppContext):
    sender = await event.get_sender()
    reply_to_msg = await event.get_reply_message()

    parts = [f"<b>🆔 Joriy chat ID:</b> {code(event.chat_id)}"]
    if sender:
        parts.append(f"<b>👤 Sizning ID:</b> {code(sender.id)}")
    if reply_to_msg:
        parts.append(f"<b>✉️ Javob berilgan xabar ID:</b> {code(reply_to_msg.id)}")
        if reply_to_msg.sender:
            parts.append(f"<b>👤 Javob berilgan foydalanuvchi ID:</b> {code(reply_to_msg.sender.id)}")

    await event.edit("\n".join(parts), parse_mode='html')


@userbot_cmd(command="pfp", description="Foydalanuvchining joriy yoki barcha profil rasmlarini yuboradi.")
async def pfp_handler(event: Message, context: AppContext):
    if not event.client or not event.text: return
    
    show_all = "all" in event.text.split()
    
    replied_msg = await event.get_reply_message()
    if replied_msg and replied_msg.sender:
        target_user = replied_msg.sender
    else:
        target_user = await event.get_chat()

    if not isinstance(target_user, (User, Chat, Channel)):
        return await event.edit(format_error("Nishon yaroqsiz."), parse_mode='html')

    await event.edit("<i>🖼️ Rasmlar qidirilmoqda...</i>", parse_mode='html')
    
    try:
        photos = await event.client.get_profile_photos(target_user, limit=None if show_all else 1)
        if not photos:
            return await event.edit("<b>Bu foydalanuvchida profil rasmlari yo'q.</b>", parse_mode='html')

        caption = f"<b>{html.escape(get_display_name(target_user))}ning {'barcha' if show_all else 'joriy'} rasmi</b>"
        file_to_send = photos if show_all else photos[0]
        
        await event.delete()
        await event.client.send_file(event.chat_id, file_to_send, caption=caption, reply_to=event.reply_to_msg_id, parse_mode='html')
    except Exception as e:
        await event.edit(format_error(f"Rasmlarni olib bo'lmadi: {e}"), parse_mode='html')

