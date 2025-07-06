# bot/plugins/user/telegraph.py
"""
Matn, media yoki butun albomlardan Telegra.ph sahifalari yaratish
va Telegra.ph akkauntlarini boshqarish uchun plagin (To'liq modernizatsiya qilingan).
"""

import asyncio
import html
import os
from pathlib import Path
from typing import Dict, List, Optional, Any

try:
    from telegraph import Telegraph, TelegraphException, upload_file
    TELEGRAPH_AVAILABLE = True
except ImportError:
    Telegraph = TelegraphException = upload_file = None
    TELEGRAPH_AVAILABLE = False

from loguru import logger
from telethon.tl.custom import Message
from telethon.tl.types import MessageEntityTextUrl

from core.app_context import AppContext
from bot.decorators import userbot_cmd
from bot.lib.telegram import get_account_id
from bot.lib.ui import format_error, format_success

# --- Konfiguratsiya va Global o'zgaruvchilar ---
TEMP_DOWNLOAD_DIR = Path("cache/telegraph_temp/")
TEMP_DOWNLOAD_DIR.mkdir(parents=True, exist_ok=True)

TELEGRAPH_CLIENTS: Dict[int, Any] = {}


# --- YORDAMCHI FUNKSIYALAR ---
async def get_telegraph_client(context: AppContext, account_id: int) -> Optional[Any]:
    """Berilgan akkaunt uchun aktiv Telegra.ph klientini keshdan oladi yoki yaratadi."""
    if not Telegraph: return None

    if account_id in TELEGRAPH_CLIENTS:
        return TELEGRAPH_CLIENTS[account_id]

    active_acc = await context.db.fetchone(
        "SELECT access_token, short_name FROM telegraph_accounts WHERE userbot_account_id = ? AND is_active = 1",
        (account_id,)
    )
    if not (active_acc and active_acc.get('access_token')):
        return None

    client = Telegraph(access_token=active_acc['access_token'])
    TELEGRAPH_CLIENTS[account_id] = client
    logger.info(f"[{account_id}] Telegra.ph klienti yuklandi: '{active_acc['short_name']}'")
    return client



def _format_message_entities_to_html(text: str, entities: Optional[List[MessageEntityTextUrl]]) -> str:
    """Telethon Message entitilarini Telegra.ph uchun HTML formatiga o'giradi."""
    if not entities:
        return html.escape(text).replace("\n", "<br>")
    return html.escape(text).replace("\n", "<br>") # Hozircha oddiyroq versiya

async def _upload_media_to_telegraph(message: Message) -> str:
    """Xabardagi mediani yuklab, Telegra.ph'ga joylaydi va HTML tegini qaytaradi."""
    if not (message.media and upload_file): return ""
    
    download_path_str: Optional[str] = None
    try:
        download_path_str = await message.download_media(file=TEMP_DOWNLOAD_DIR)
        if not download_path_str: return ""
        
        urls = await asyncio.to_thread(upload_file, str(download_path_str))
        if not urls: return ""

        url = f"https://telegra.ph{urls[0]}"
        tag = "img" if message.photo else "video" if message.video else None
        
        return f"<figure><{tag} src='{url}'/></figure>" if tag else f"<p><a href='{url}'>Yuklab olish</a></p>"
    except Exception as e:
        logger.error(f"Media yuklashda xatolik: {e}")
        return ""
    finally:
        if download_path_str and os.path.exists(download_path_str):
            await asyncio.to_thread(os.remove, download_path_str)

# --- Asosiy Buyruqlar ---

@userbot_cmd(command="tg", description="Xabardan yoki albomdan Telegra.ph sahifasi yaratadi.")
async def telegraph_handler(event: Message, context: AppContext):
    """ .tg <sarlavha> (xabarga javob bergan holda) """
    if not TELEGRAPH_AVAILABLE:
        return await event.edit(format_error("`telegraph` kutubxonasi o'rnatilmagan."), parse_mode='html')
    if not (event.client and event.text): return
    
    account_id = await get_account_id(context, event.client)
    if not account_id:
        return await event.edit(format_error("Akkauntni aniqlab bo'lmadi."), parse_mode='html')
    
    telegraph = await get_telegraph_client(context, account_id)
    if not telegraph:
        return await event.edit(format_error("Aktiv Telegra.ph akkaunti topilmadi.\nYaratish uchun: `.tg_new_acc <nomi>`"), parse_mode='html')

    replied_message = await event.get_reply_message()
    if not replied_message:
        return await event.edit("❗️ Sahifa yaratish uchun biror xabarga javob bering.", parse_mode='html')

    await event.edit("<i>🔄 Telegra.ph sahifasi tayyorlanmoqda...</i>", parse_mode='html')

    try:
        title = event.text.split(maxsplit=1)[1].strip() if len(event.text.split()) > 1 else "Sarlavhasiz"
        
        messages_to_process = [replied_message]
        if replied_message.grouped_id:
            album_messages = await event.client.get_messages(event.chat_id, grouped_id=replied_message.grouped_id)
            if album_messages:
                messages_to_process = sorted(album_messages, key=lambda m: m.id)

        content_parts = []
        for msg in messages_to_process:
            content_parts.append(await _upload_media_to_telegraph(msg))
            if msg.text:
                content_parts.append(f"<p>{_format_message_entities_to_html(msg.text, msg.entities)}</p>")
        
        content_html = "".join(filter(None, content_parts))
        if not content_html.strip():
            return await event.edit(format_error("Sahifa uchun kontent yaratib bo'lmadi."), parse_mode='html')

        response = await asyncio.to_thread(telegraph.create_page, title, html_content=content_html)
        await event.edit(f"✅ <b>Sahifa:</b> <a href=\"{response['url']}\">{html.escape(title)}</a>", link_preview=True, parse_mode='html')
    except Exception as e:
        if TelegraphException is not None and isinstance(e, TelegraphException):
            await event.edit(format_error(f"Telegra.ph xatoligi: {e}"), parse_mode='html')
        else:
            logger.exception("Telegraph sahifasini yaratishda kutilmagan xato")
            await event.edit(format_error(f"Noma'lum xatolik: {e}"), parse_mode='html')


@userbot_cmd(command="tg_new_acc", description="Yangi Telegra.ph akkaunti yaratadi.")
async def new_account_command(event: Message, context: AppContext):
    """ .tg_new_acc Mening Blogim | Alisher """
    if not Telegraph:
        return await event.edit(format_error("`telegraph` kutubxonasi o'rnatilmagan."), parse_mode='html')
    if not (event.client and event.text): return
    account_id = await get_account_id(context, event.client)
    if not account_id: return await event.edit(format_error("Akkauntni aniqlab bo'lmadi."), parse_mode='html')

    args_str = event.text.split(maxsplit=1)[1] if len(event.text.split()) > 1 else ""
    args = [a.strip() for a in args_str.split('|', 1)]
    short_name = args[0]
    author_name = args[1] if len(args) > 1 else "UserBot"

    if not short_name:
        return await event.edit(format_error("<b>Namuna:</b> <code>.tg_new_acc MeningBlogim | Alisher</code>"), parse_mode='html')

    await event.edit(f"<i>🔄 '{short_name}' nomli yangi akkaunt yaratilmoqda...</i>", parse_mode='html')

    try:
        new_acc = await asyncio.to_thread(Telegraph().create_account, short_name=short_name, author_name=author_name)
        token = new_acc.get('access_token')
        if not token: raise ValueError("Yangi tokenni olib bo'lmadi")

        async with context.db.transaction():
            await context.db.execute("UPDATE telegraph_accounts SET is_active = 0 WHERE userbot_account_id = ?", (account_id,))
            await context.db.execute(
                "INSERT INTO telegraph_accounts (userbot_account_id, short_name, author_name, access_token, is_active) VALUES (?, ?, ?, ?, 1)",
                (account_id, new_acc['short_name'], new_acc.get('author_name'), token)
            )
        
        TELEGRAPH_CLIENTS.pop(account_id, None)
        await event.edit(format_success(f"Yangi akkaunt '{new_acc['short_name']}' yaratildi va aktivlashtirildi!"), parse_mode='html')
    except Exception as e:
        if TelegraphException is not None and isinstance(e, TelegraphException):
            await event.edit(format_error(f"Akkaunt yaratishda xatolik: {e}"), parse_mode='html')
        else:
            logger.exception("Yangi Telegraph akkaunt yaratishda kutilmagan xato")
            await event.edit(format_error(f"Noma'lum xatolik: {e}"), parse_mode='html')
