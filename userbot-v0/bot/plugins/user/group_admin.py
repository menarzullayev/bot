# userbot-v0/bot/plugins/user/group_admin.py
"""
Guruhlarni boshqarish uchun mo'ljallangan plagin (to'liq modernizatsiya qilingan).
"""

import asyncio
import html
import re
from datetime import datetime, timedelta
from typing import List, Optional, Tuple

from loguru import logger
from telethon.tl.custom import Message
from telethon import types
from telethon.tl.functions.channels import GetFullChannelRequest
from telethon.tl.types import ChatBannedRights

from core.app_context import AppContext
from bot.decorators import userbot_cmd
from bot.lib.auth import admin_only
from bot.lib.telegram import get_user, check_rights_and_reply, get_display_name
from bot.lib.ui import bold, format_error, format_success

# --- YORDAMCHI FUNKSIYALAR ---

def _parse_time_and_targets(args_str: str) -> Tuple[List[str], Optional[datetime]]:
    """Buyruq satridan nishonlar ro'yxatini va cheklov muddatini ajratib oladi."""
    until_date: Optional[datetime] = None
    time_match = re.search(r"(\d+[smhdw])$", args_str.lower())
    
    if time_match:
        time_str = time_match.group(1)
        args_str = args_str[:time_match.start()].strip()
        
        value = int(time_str[:-1])
        unit = time_str[-1]
        
        if unit == 's': delta = timedelta(seconds=value)
        elif unit == 'm': delta = timedelta(minutes=value)
        elif unit == 'h': delta = timedelta(hours=value)
        elif unit == 'd': delta = timedelta(days=value)
        elif unit == 'w': delta = timedelta(weeks=value)
        else: delta = timedelta(0)
        
        until_date = datetime.now() + delta

    targets = args_str.split() if args_str else []
    return targets, until_date

async def _apply_action_to_user(event: Message, context: AppContext, action: str, target_user: types.User, until_date: Optional[datetime]) -> str:
    """Belgilangan foydalanuvchiga cheklov amalini qo'llaydi."""
    client = event.client
    if not client or not event.chat_id:
        return format_error("Amalni bajarish uchun klient yoki chat mavjud emas.")

    try:
        if action == 'kick':
            await client.kick_participant(event.chat_id, target_user)
            return format_success(f"<a href='tg://user?id={target_user.id}'>{get_display_name(target_user)}</a> guruhdan chiqarildi.")
        
        rights_map = {
            'ban': ChatBannedRights(until_date=until_date, view_messages=True),
            'unban': ChatBannedRights(until_date=None),
            'mute': ChatBannedRights(until_date=until_date, send_messages=True),
            'unmute': ChatBannedRights(until_date=None, send_messages=False),
        }
        
        if action in rights_map:
            await client.edit_permissions(event.chat_id, target_user, rights=rights_map[action])
            return format_success(f"<a href='tg://user?id={target_user.id}'>{get_display_name(target_user)}</a> uchun cheklovlar o'rnatildi.")
            
        return format_error(f"Noma'lum amal: {action}")
        
    except Exception as e:
        logger.error(f"'{action}' amalini '{target_user.id}' ga qo'llashda xato: {e}")
        return format_error(f"<code>{target_user.id}</code> - {type(e).__name__}")

# --- GURUHNI BOSHQARISH BUYRUQLARI ---

@userbot_cmd(command=["ban", "kick", "unban", "mute", "unmute"], description="Foydalanuvchini guruhda boshqaradi.")
@admin_only
async def user_management_cmd(event: Message, context: AppContext):
    if not event.is_group or not event.text or not event.client:
        return await event.edit(format_error("Bu buyruq faqat guruhlarda ishlaydi."), parse_mode='html')

    required_right = 'ban_users'
    if not await check_rights_and_reply(event, [required_right]):
        return

    parts = event.text.split(maxsplit=1)
    action = parts[0].lstrip('.').lower()
    args_str = parts[1] if len(parts) > 1 else ""
    
    targets_str, until_date = _parse_time_and_targets(args_str)

    targets, error_msg = [], ""
    if not targets_str:
        user, error = await get_user(context, event, "")
        if user: targets.append(user)
        else: error_msg = error or "Nishon topilmadi."
    else:
        for t_str in targets_str:
            user, err = await get_user(context, event, t_str)
            if user: targets.append(user)
            else: error_msg += f"{err}\n"

    if not targets:
        return await event.edit(format_error(error_msg), parse_mode='html')
    
    await event.edit(f"<i>🔄 {action.capitalize()} amaliyoti bajarilmoqda...</i>", parse_mode='html')

    tasks = [_apply_action_to_user(event, context, action, user, until_date) for user in targets]
    results = await asyncio.gather(*tasks)
    
    response = "\n".join(results)
    await event.edit(response or "<b>Hech qanday amal bajarilmadi.</b>", parse_mode='html')


@userbot_cmd(command="pin", description="Xabarni qadaydi.")
@admin_only
async def pin_cmd(event: Message, context: AppContext):
    if not event.client or not event.reply_to_msg_id or not event.chat_id:
        return await event.edit(format_error("Xabarga javob bering."), parse_mode='html')
    if not await check_rights_and_reply(event, ['pin_messages']):
        return
        
    await event.client.pin_message(event.chat_id, event.reply_to_msg_id)
    await event.edit(format_success("Xabar qadaldi."), parse_mode='html')


@userbot_cmd(command="unpin", description="Qadalgan xabarni olib tashlaydi.")
@admin_only
async def unpin_cmd(event: Message, context: AppContext):
    if not event.client or not event.chat_id:
        return await event.edit(format_error("Buyruq guruhda ishlatilishi kerak."), parse_mode='html')
    if not await check_rights_and_reply(event, ['pin_messages']):
        return

    await event.client.unpin_message(event.chat_id)
    await event.edit(format_success("Xabar qadalgandan olindi."), parse_mode='html')


@userbot_cmd(command="purge", description="Belgilangan xabarlarni o'chiradi.")
@admin_only
async def purge_cmd(event: Message, context: AppContext):
    if not event.chat_id or not event.client:
        return
    if not await check_rights_and_reply(event, ['delete_messages']):
        return

    reply_msg = await event.get_reply_message()
    if not reply_msg:
        return await event.edit(format_error("Xabarlarni tozalash uchun biror xabarga javob bering."), parse_mode='html')
    
    message_ids = [msg.id async for msg in event.client.iter_messages(
        event.chat_id, min_id=reply_msg.id - 1, max_id=event.id + 1
    )]

    if not message_ids:
        return await event.edit(format_error("O'chirish uchun xabarlar topilmadi."), parse_mode='html')
    
    await event.edit(f"<i>🗑 {len(message_ids)} ta xabar o'chirilmoqda...</i>", parse_mode='html')
    
    for i in range(0, len(message_ids), 100):
        await event.client.delete_messages(event.chat_id, message_ids[i:i+100])
    
    res = await event.respond(format_success(f"{len(message_ids)} ta xabar o'chirildi."), parse_mode='html')
    await asyncio.sleep(5)
    if res:
        await res.delete()


@userbot_cmd(command="tagall", description="Guruh a'zolarini belgilaydi (tag qiladi).")
@admin_only
async def tagall_cmd(event: Message, context: AppContext):
    if not event.text or not event.chat_id or not event.client: return

    args = event.text.split(maxsplit=1)[1] if ' ' in event.text else ""
    message = args.replace("--admins", "").strip() or ""
    
    await event.delete()
    
    p_filter = types.ChannelParticipantsAdmins() if "--admins" in args else None
    text_parts, base_text = [], f"<b>{message}</b>\n\n"
    
    async for member in event.client.iter_participants(event.chat_id, filter=p_filter):
        if not member.bot:
            text_parts.append(f"• <a href='tg://user?id={member.id}'>{get_display_name(member)}</a>")
    
    for i in range(0, len(text_parts), 100):
        chunk = text_parts[i:i+100]
        await event.client.send_message(event.chat_id, base_text + "\n".join(chunk), parse_mode='html')
        await asyncio.sleep(2)


@userbot_cmd(command="ginfo", description="Guruh haqida to'liq ma'lumot beradi.")
@admin_only
async def ginfo_cmd(event: Message, context: AppContext):
    if not event.is_group or not event.chat_id or not event.client:
        return await event.edit(format_error("Bu faqat guruhlarda ishlaydi."), parse_mode='html')
    
    await event.edit("<i>🔄 Guruh ma'lumotlari olinmoqda...</i>", parse_mode='html')

    try:
        input_chat = await event.get_input_chat()
        if not input_chat:
            return await event.edit(format_error("Guruh ma'lumotlarini olib bo'lmadi."), parse_mode='html')

        full_chat_obj = await event.client(GetFullChannelRequest(channel=input_chat))
        chat_info = full_chat_obj.full_chat

        chat_id = getattr(event.chat, "id", "N/A")
        response = f"<b>Guruh: {bold(get_display_name(event.chat))}</b>\n\n"
        response += f"<b>ID:</b> <code>{chat_id}</code>\n"
        response += f"<b>A'zolar:</b> <code>{getattr(chat_info, 'participants_count', 'N/A')}</code>\n"
        response += f"<b>Onlayn:</b> <code>{getattr(chat_info, 'online_count', 'N/A')}</code>\n"
        response += f"<b>Adminlar:</b> <code>{getattr(chat_info, 'admins_count', 'N/A')}</code>\n"
        response += f"<b>Cheklanganlar:</b> <code>{getattr(chat_info, 'kicked_count', 'N/A')}</code>"
        
        await event.edit(response, parse_mode='html')
    except Exception as e:
        await event.edit(format_error(f"Ma'lumot olishda xato: {e}"), parse_mode='html')
