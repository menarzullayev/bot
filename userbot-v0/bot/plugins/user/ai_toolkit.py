# userbot-v0/bot/plugins/user/ai_toolkit.py
"""
AI (sun'iy intellekt) bilan ishlash uchun plaginlar to'plami.
(To'liq modernizatsiya qilingan).
"""

import asyncio
import html
import io
import shlex
from typing import AsyncGenerator, Optional, Tuple, Union

from loguru import logger
from telethon import events, types
from telethon.tl.custom import Message

from core.app_context import AppContext
from bot.decorators import userbot_cmd
from bot.lib.telegram import get_account_id
from bot.lib.ui import (code, format_error, format_success,
                        send_as_file_if_long)
from bot.lib.utils import RaiseArgumentParser
from bot.lib.auth import admin_only

# --- YORDAMCHI FUNKSIYALAR ---

async def _get_prompt(event: Message, args: str) -> Optional[str]:
    """Buyruq argumentlaridan yoki javob berilgan xabardan so'rov (prompt) matnini oladi."""
    prompt = args.strip()
    if not prompt:
        if replied := await event.get_reply_message():
            prompt = replied.text
    return prompt.strip() if prompt else None

async def _get_media_from_reply(reply_msg: Message) -> Tuple[Optional[Union[types.Photo, types.Document]], Optional[str]]:
    """Javob berilgan xabardan Photo yoki Document obyektini ajratib oladi."""
    if not (media := reply_msg.media):
        return None, "❗️ Iltimos, rasm yoki hujjatga javob bering."
    
    if isinstance(media, types.MessageMediaPhoto) and isinstance(media.photo, types.Photo):
        return media.photo, None
    if isinstance(media, types.MessageMediaDocument) and isinstance(media.document, types.Document):
        return media.document, None
    if isinstance(media, types.MessageMediaWebPage) and isinstance(media.webpage, types.WebPage) and isinstance(media.webpage.photo, types.Photo):
        return media.webpage.photo, None
        
    return None, "❌ Javob berilgan xabarda mos media topilmadi."

# --- ASOSIY BUYRUQLAR ---

@userbot_cmd(command="ask", description="AI'ga matnli savol beradi. Internetdan qidirishi ham mumkin.")
async def ask_cmd(event: Message, context: AppContext):
    if not event.text: return
    
    args_str = event.text.split(maxsplit=1)[1] if len(event.text.split()) > 1 else ""
    parser = RaiseArgumentParser(prog=".ask", add_help=False)
    parser.add_argument('-net', action='store_true')
    parser.add_argument('prompt_parts', nargs='*')
    
    try:
        args = parser.parse_args(shlex.split(args_str))
    except (ValueError, SystemExit) as e:
        return await event.edit(format_error(f"Argument xatosi: {e}"), parse_mode='html')

    prompt = " ".join(args.prompt_parts)
    if not (prompt := await _get_prompt(event, prompt)):
        return await event.edit(format_error("Savolingizni kiriting yoki matnli xabarga javob bering."), parse_mode='html')

    initial_text = "🧠 AI o'ylanmoqda..."
    if args.net:
        initial_text = "🌐 Internetdan qidirilmoqda..."
    
    await event.edit(f"<i>{initial_text}</i>", parse_mode='html')

    try:
        handler = context.ai_service.generate_with_rag if args.net else context.ai_service.generate_text
        response_data = await handler(prompt)
        final_response = response_data.get("text", "Javob topilmadi.")
        formatted_response = f"<b>❓ Savol:</b>\n<code>{html.escape(prompt)}</code>\n\n<b>🤖 Javob:</b>\n{html.escape(final_response)}"
        await send_as_file_if_long(event, formatted_response, filename="ai_response.txt", parse_mode='html')
    except Exception as e:
        logger.exception("AI xizmatida xatolik")
        await event.edit(format_error(f"<b>AI Xatoligi:</b>\n<code>{html.escape(str(e))}</code>"), parse_mode='html')


@userbot_cmd(command="chat", description="AI bilan suhbat (shaxsiyat bilan). Suhbatni tozalash uchun '-p' dan foydalaning.")
async def chat_cmd(event: Message, context: AppContext):
    if not event.text: return
    
    args_str = event.text.split(maxsplit=1)[1] if len(event.text.split()) > 1 else ""
    parser = RaiseArgumentParser(prog=".chat", add_help=False)
    parser.add_argument('-p', '--persona', type=str, help="Yangi shaxsiyat o'rnatib, suhbatni boshlaydi.")
    parser.add_argument('prompt_parts', nargs='*')
    
    try:
        args = parser.parse_args(shlex.split(args_str))
    except (ValueError, SystemExit) as e:
        return await event.edit(format_error(f"Argument xatosi: {e}"), parse_mode='html')

    prompt = " ".join(args.prompt_parts)
    if not prompt:
        return await event.edit(format_error("Suhbat uchun xabar yozing."), parse_mode='html')

    await event.edit("<i>🤖 AI suhbatdosh o'ylanmoqda...</i>", parse_mode='html')
    
    try:
        chat_id = f"tg_chat_{event.chat_id}"
        if args.persona:
            await context.ai_service.start_chat(chat_id, persona=args.persona)
        
        response_data = await context.ai_service.generate_chat_response(chat_id=chat_id, prompt=prompt)
        final_response = response_data.get("text", "Javob topilmadi.")
        formatted_response = f"<b>👤 Siz:</b>\n<code>{html.escape(prompt)}</code>\n\n<b>🤖 AI:</b>\n{html.escape(final_response)}"
        await send_as_file_if_long(event, formatted_response, filename="ai_chat.txt", parse_mode='html')
    except Exception as e:
        logger.exception("AI chatda xatolik")
        await event.edit(format_error(f"<b>AI Xatoligi:</b>\n<code>{html.escape(str(e))}</code>"), parse_mode='html')

@userbot_cmd(command=["askimg", "askdoc", "transcribe"], description="Rasm, hujjat yoki audio bilan AI'ga murojaat.")
async def media_cmd(event: Message, context: AppContext):
    if not event.text or not event.client: return
    
    parts = event.text.split(maxsplit=1)
    command = parts[0].lstrip('.').lower()
    prompt = parts[1].strip() if len(parts) > 1 else ""

    if not prompt and command != 'transcribe':
        return await event.edit(format_error("Rasm yoki hujjat uchun savolingizni yozing."), parse_mode='html')
    if not (reply_msg := await event.get_reply_message()):
        return await event.edit(format_error("Rasm, hujjat yoki audio faylga javob bering."), parse_mode='html')
    
    media_obj, error = await _get_media_from_reply(reply_msg)
    if error: return await event.edit(format_error(error), parse_mode='html')
    if not media_obj: return

    await event.edit("<i>⏳ Fayl yuklanmoqda va qayta ishlanmoqda...</i>", parse_mode='html')
    
    try:
        with io.BytesIO() as media_buffer:
            await event.client.download_media(media_obj, media_buffer)
            media_bytes = media_buffer.getvalue()

        handler, initial_text, response_template = None, "", ""
        if command == "askimg":
            handler = lambda: context.ai_service.generate_from_image(prompt, media_bytes)
            initial_text, response_template = "AI rasmni tahlil qilmoqda...", "<b>🖼️ Savol:</b>\n<code>{prompt}</code>\n\n<b>🤖 Javob:</b>\n{response}"
        elif command == "askdoc":
            doc_text = media_bytes.decode('utf-8', errors='ignore')
            handler = lambda: context.ai_service.generate_from_document(prompt, doc_text)
            initial_text, response_template = "AI hujjatni o'qimoqda...", "<b>📄 Savol:</b>\n<code>{prompt}</code>\n\n<b>🤖 Javob:</b>\n{response}"
        elif command == "transcribe":
            handler = lambda: context.ai_service.transcribe_audio(media_bytes)
            initial_text, response_template = "AI audioni eshitmoqda...", "<b>🎤 Natija:</b>\n{response}"
        
        if handler:
            await event.edit(f"<i>{initial_text}</i>", parse_mode='html')
            response_data = await handler()
            final_response = response_data.get("text", "Javob topilmadi.")
            formatted_response = response_template.format(prompt=html.escape(prompt), response=html.escape(final_response))
            await send_as_file_if_long(event, formatted_response, filename="ai_media_response.txt", parse_mode='html')
            
    except Exception as e:
        logger.exception(f"AI media so'rovida xatolik: {command}")
        await event.edit(format_error(f"<b>AI Xatoligi:</b>\n<code>{html.escape(str(e))}</code>"), parse_mode='html')

@userbot_cmd(command="teach", description="AI'ga yangi bilimni (savol-javob) o'rgatadi.")
@admin_only
async def teach_cmd(event: Message, context: AppContext):
    if not event.text or not event.client: return
    account_id = await get_account_id(context, event.client)
    if not account_id: return await event.edit(format_error("Akkaunt ID topilmadi."), parse_mode='html')

    try:
        parts = shlex.split(event.text.split(' ', 1)[1])
        if len(parts) != 2: raise ValueError("Noto'g'ri format")
        trigger, response = parts
    except (IndexError, ValueError):
        return await event.edit(format_error("Format: <code>.teach \"savol\" \"javob\"</code>"), parse_mode='html')
        
    if not trigger or not response:
        return await event.edit(format_error("Savol va javob bo'sh bo'lishi mumkin emas."), parse_mode='html')
    
    await context.db.execute("REPLACE INTO ai_knowledge_base (account_id, trigger_phrase, response_text) VALUES (?, ?, ?)", (account_id, trigger.lower(), response))
    await event.edit(format_success(f"<b>O'rgatildi!</b> Endi {code(trigger)} so'roviga tayyor javob bor."), parse_mode='html')

@userbot_cmd(command="autoreply", description="Shaxsiy xabarlarga avtomatik javob berishni yoqadi/o'chiradi.")
@admin_only
async def autoreply_toggle_cmd(event: Message, context: AppContext):
    if not event.text or not event.client: return
    account_id = await get_account_id(context, event.client)
    if not account_id: return await event.edit(format_error("Akkaunt ID topilmadi."), parse_mode='html')
    
    state = event.text.split()[1].lower() if len(event.text.split()) > 1 else None
    if state not in ('on', 'off'):
        return await event.edit(format_error("Format: <code>.autoreply <on|off></code>"), parse_mode='html')
        
    is_enabled = state == 'on'
    await context.state.set(f"ai_autoreply_enabled_{account_id}", is_enabled, persistent=True)
    await event.edit(format_success(f"🤖 <b>Avtomatik javob berish rejimi</b> {'yoqildi' if is_enabled else 'o‘chirildi'}."), parse_mode='html')

@userbot_cmd(listen=events.NewMessage(incoming=True, func=lambda e: e.is_private))
async def autoreply_listener(event: Message, context: AppContext):
    if event.out or not event.client: return
    
    sender = await event.get_sender()
    if not isinstance(sender, types.User) or sender.bot or sender.is_self: return
    
    account_id = await get_account_id(context, event.client)
    if not account_id: return

    if not context.state.get(f"ai_autoreply_enabled_{account_id}", False):
        return

    logger.info(f"Avto-javob uchun {sender.id} dan xabar keldi.")
    await asyncio.sleep(10)
    
    history = await event.client.get_messages(sender, limit=5)
    if not history or any(msg.out for msg in history[:2]):
        return logger.info(f"{sender.id} bilan suhbatga yaqinda javob berilgan. Avto-javob to'xtatildi.")

    history_text = "\n".join([f"{'Siz' if msg.out else 'U'}: {msg.text}" for msg in reversed(history) if msg.text])
    
    prompt = f"Quyidagi suhbat tarixiga qarab, 'Siz'ning nomingizdan mantiqiy va qisqa javob yozing. Suhbatni cho'zmang, tabiiy javob bering.\n\nSuhbat:\n---\n{history_text}\n---\n\nJavobingiz:"
    response_data = await context.ai_service.generate_text(prompt, system_prompt="Siz foydalanuvchining shaxsiy yordamchisisiz. Uning nomidan javob yozasiz.")
    
    if response_data and (text := response_data.get("text")):
        await event.reply(text)

