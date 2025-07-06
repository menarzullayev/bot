# bot/plugins/user/welcome.py
"""
Guruhlarga yangi a'zolar qo'shilganda ularni kutib olish, xayrlashish
va CAPTCHA orqali botlardan himoya qilish uchun plagin (To'liq modernizatsiya qilingan).
"""

import asyncio
import html
import random
import re
from datetime import timedelta
from typing import Optional, Tuple, Union

from loguru import logger
from telethon import events
from telethon.tl.custom import Message
from telethon.tl.types import User, Chat, Channel

from core.app_context import AppContext
from bot.decorators import userbot_cmd
from bot.lib.telegram import get_account_id
from bot.lib.ui import format_error, format_success
from bot.lib.auth import admin_only

# --- Yordamchi Funksiyalar ---

def _generate_math_captcha() -> Tuple[str, int]:
    """Oddiy matematik misol (CAPTCHA) yaratadi."""
    a, b = random.randint(2, 9), random.randint(2, 9)
    return (f"{a} + {b}", a + b) if random.choice([True, False]) else (f"{max(a, b)} - {min(a, b)}", max(a, b) - min(a, b))

def _format_message(text: str, user: User, chat: Union[Chat, Channel]) -> str:
    """Xabar matnidagi o'zgaruvchilarni almashtiradi."""
    return text.format(
        first_name=html.escape(user.first_name or "Foydalanuvchi"),
        last_name=html.escape(user.last_name or ""),
        username=f"@{user.username}" if user.username else f"ID: {user.id}",
        mention=f"<a href='tg://user?id={user.id}'>{html.escape(user.first_name or 'Foydalanuvchi')}</a>",
        chat_title=html.escape(getattr(chat, 'title', "Guruh")),
    )

async def _apply_penalty(client, chat_id: int, user_id: int, penalty: str):
    """CAPTCHA'dan o'ta olmagan foydalanuvchiga jazo qo'llaydi."""
    logger.info(f"CAPTCHA jazosi: '{penalty}' user:{user_id} chat:{chat_id}")
    try:
        if penalty == "kick":
            await client.kick_participant(chat_id, user_id)
        else:  # 'mute'
            await client.edit_permissions(chat_id, user_id, send_messages=False)
    except Exception as e:
        logger.error(f"Jazo qo'llashda xato: {e}")

def _parse_time(time_str: str) -> Optional[timedelta]:
    """Vaqt matnini (10s, 5m, 1h) timedelta obyektiga o'tkazadi."""
    if match := re.match(r"^(\d+)([smhd])$", time_str.strip().lower()):
        value, unit = int(match.group(1)), match.group(2)
        return {"s": timedelta(seconds=value), "m": timedelta(minutes=value), "h": timedelta(hours=value), "d": timedelta(days=value)}.get(unit)
    return None

# --- Asosiy Hodisa Ishlovchilari ---

@userbot_cmd(listen=events.ChatAction)
async def welcome_event_handler(event: events.ChatAction.Event, context: AppContext):
    """Guruhdagi harakatlar (qo'shilish, chiqish) uchun asosiy handler."""
    client = event.client
    if not (client and event.chat_id): return
    
    if event.client is None:
        return
    account_id = await get_account_id(context, event.client)
    if not account_id: return
    
    settings = await context.db.fetchone(
        "SELECT * FROM group_settings WHERE userbot_account_id = ? AND chat_id = ?",
        (account_id, event.chat_id)
    )
    if not settings: return

    if settings.get('clean_service_messages') and (event.user_joined or event.user_left or event.user_kicked):
        await event.delete()

    user = await event.get_user()
    if not isinstance(user, User) or user.bot:
        return
    
    chat = await event.get_chat()
    if not isinstance(chat, (Chat, Channel)): return
    
    if event.user_joined or event.user_added:
        if settings.get('captcha_enabled'):
            timeout = settings.get("captcha_timeout", 120)
            question, answer = _generate_math_captcha()
            mention = f"<a href='tg://user?id={user.id}'>{html.escape(user.first_name or '')}</a>"
            captcha_text = (f"Salom, {mention}! Guruhga xush kelibsiz.\n"
                            f"Iltimos, <b>{timeout} soniya</b> ichida quyidagi misolning javobini yozing:\n\n"
                            f"<b>Misol: {question} = ?</b>")
            try:
                captcha_msg = await event.reply(captcha_text, parse_mode='html')
                await context.db.execute(
                    "REPLACE INTO captcha_challenges (chat_id, user_id, correct_answer, captcha_message_id) VALUES (?, ?, ?, ?)",
                    (chat.id, user.id, str(answer), captcha_msg.id)
                )
                await asyncio.sleep(timeout)
                if challenge := await context.db.fetchone("SELECT * FROM captcha_challenges WHERE chat_id = ? AND user_id = ?", (chat.id, user.id)):
                    await _apply_penalty(client, chat.id, user.id, settings.get('captcha_penalty', 'mute'))
                    await client.delete_messages(chat.id, [challenge['captcha_message_id']])
                    await context.db.execute("DELETE FROM captcha_challenges WHERE chat_id = ? AND user_id = ?", (chat.id, user.id))
            except Exception as e:
                logger.error(f"CAPTCHA jarayonida xato: {e}")

        elif settings.get('welcome_enabled') and (welcome_msg_text := settings.get("welcome_message")):
            formatted_msg = _format_message(welcome_msg_text, user, chat)
            sent_msg = await event.reply(formatted_msg, parse_mode='html')
            if sent_msg and (timeout := settings.get("welcome_timeout", 0)) > 0:
                await asyncio.sleep(timeout)
                await sent_msg.delete()

    elif (event.user_left or event.user_kicked) and settings.get('goodbye_enabled'):
        if goodbye_msg_text := settings.get('goodbye_message'):
            formatted_msg = _format_message(goodbye_msg_text, user, chat)
            await client.send_message(event.chat_id, formatted_msg, parse_mode='html')

@userbot_cmd(listen=events.NewMessage(incoming=True, func=lambda e: e.is_group))
async def captcha_answer_handler(event: Message, context: AppContext):
    """CAPTCHA javoblarini tekshiruvchi handler."""
    if not (event.client and event.text and event.sender_id): return
    
    challenge = await context.db.fetchone("SELECT * FROM captcha_challenges WHERE chat_id = ? AND user_id = ?", (event.chat_id, event.sender_id))
    if not challenge: return

    if event.text.strip() == challenge['correct_answer']:
        logger.info(f"Foydalanuvchi {event.sender_id} CAPTCHA'dan o'tdi.")
        await context.db.execute("DELETE FROM captcha_challenges WHERE chat_id = ? AND user_id = ?", (event.chat_id, event.sender_id))
        await event.client.delete_messages(event.chat_id, [challenge['captcha_message_id'], event.id])
    else:
        await event.delete()

# --- Boshqaruv Buyruqlari ---

@userbot_cmd(command="setwelcome", description="Guruh uchun xush kelibsiz xabarini o'rnatadi.")
@admin_only
async def set_welcome_cmd(event: Message, context: AppContext):
    if not event.is_group: return await event.edit(format_error("Bu buyruq faqat guruhlarda ishlaydi."), parse_mode='html')
    if not (event.client and event.text): return
    account_id = await get_account_id(context, event.client)
    if not account_id: return

    text = event.text.split(maxsplit=1)[1] if len(event.text.split()) > 1 else ""
    if not text:
        return await event.edit(format_error("<b>Xush kelibsiz xabari uchun matn kiriting.</b>\nO'zgaruvchilar: {mention}, {first_name}, {chat_title}"), parse_mode='html')
    
    await context.db.execute(
        "REPLACE INTO group_settings (userbot_account_id, chat_id, welcome_message) VALUES (?, ?, ?)",
        (account_id, event.chat_id, text)
    )
    await event.edit(format_success("Xush kelibsiz xabari o'rnatildi."), parse_mode='html')

@userbot_cmd(command=["welcome", "goodbye", "cleanservice", "captcha"], description="Guruh sozlamalarini yoqadi/o'chiradi.")
@admin_only
async def toggle_settings_cmd(event: Message, context: AppContext):
    if not event.is_group: return await event.edit(format_error("Bu buyruq faqat guruhlarda ishlaydi."), parse_mode='html')
    if not (event.client and event.text): return
    account_id = await get_account_id(context, event.client)
    if not account_id: return

    parts = event.text.split()
    command = parts[0].strip('.')
    state_str = parts[1].lower() if len(parts) > 1 else ""
    if state_str not in ["on", "off"]:
        return await event.edit(format_error(f"<b>Format:</b> <code>.{command} on|off</code>"), parse_mode='html')
    
    state = state_str == 'on'
    setting_map = {
        "welcome": "welcome_enabled", "goodbye": "goodbye_enabled",
        "cleanservice": "clean_service_messages", "captcha": "captcha_enabled"
    }
    db_column = setting_map[command]

    await context.db.execute(
        f"INSERT INTO group_settings (userbot_account_id, chat_id, {db_column}) VALUES (?, ?, ?) "
        f"ON CONFLICT(userbot_account_id, chat_id) DO UPDATE SET {db_column} = excluded.{db_column}",
        (account_id, event.chat_id, state)
    )
    await event.edit(format_success(f"{db_column.replace('_', ' ').capitalize()} funksiyasi <b>{'yoqildi' if state else 'o\'chirildi'}</b>."), parse_mode='html')

@userbot_cmd(command="welcomedel", description="Welcome xabarini avtomatik o'chirish vaqtini belgilaydi.")
@admin_only
async def set_welcome_delete_timer_cmd(event: Message, context: AppContext):
    if not (event.is_group and event.client and event.text): return
    account_id = await get_account_id(context, event.client)
    if not account_id: return

    time_str = event.text.split(maxsplit=1)[1] if len(event.text.split()) > 1 else ""
    if not time_str:
        return await event.edit(format_error("Vaqt kiriting (masalan, `5m`). O'chirmaslik uchun `0` kiriting."), parse_mode='html')
        
    seconds = 0
    if time_str != '0' and (delta := _parse_time(time_str)):
        seconds = int(delta.total_seconds())
    elif time_str != '0':
        return await event.edit(format_error("Noto'g'ri vaqt formati. Namuna: 10s, 5m, 1h."), parse_mode='html')

    await context.db.execute(
        "INSERT INTO group_settings (userbot_account_id, chat_id, welcome_timeout) VALUES (?, ?, ?) "
        "ON CONFLICT(userbot_account_id, chat_id) DO UPDATE SET welcome_timeout = excluded.welcome_timeout",
        (account_id, event.chat_id, seconds)
    )
    msg = f"Xush kelibsiz xabarlari endi {time_str} dan so'ng o'chiriladi." if seconds > 0 else "Xush kelibsiz xabarlarini avtomatik o'chirish bekor qilindi."
    await event.edit(format_success(msg), parse_mode='html')

