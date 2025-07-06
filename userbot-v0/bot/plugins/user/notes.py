# userbot-v0/bot/plugins/user/notes.py
"""
Eslatmalarni (notes) saqlash va ulardan foydalanish uchun plagin (To'liq modernizatsiya qilingan).
Endi `#note_nomi` orqali chaqirish to'liq ishlaydi.
"""

import html
from typing import Optional

from loguru import logger
from telethon import events
from telethon.tl.custom import Message

from core.app_context import AppContext
from bot.decorators import userbot_cmd
from bot.lib.telegram import get_account_id, get_display_name
from bot.lib.ui import PaginationHelper, bold, format_error, format_success, code

# --- YORDAMCHI FUNKSIYALAR ---

async def _parse_placeholders(text: Optional[str], event: Message) -> str:
    """Eslatma matnidagi o'zgaruvchilarni ({user}, {chat} va hk) haqiqiy ma'lumotlar bilan almashtiradi."""
    if not text:
        return ""
    
    sender = await event.get_sender()
    chat = await event.get_chat()
    
    sender_name = get_display_name(sender) if sender else "User"
    sender_id = getattr(sender, 'id', 0)
    chat_title = get_display_name(chat) if chat else "Chat"
    
    date_str = event.date.strftime('%d.%m.%Y') if event.date else ""
    time_str = event.date.strftime('%H:%M') if event.date else ""
    
    replacements = {
        "{user}": html.escape(sender_name),
        "{mention}": f"<a href='tg://user?id={sender_id}'>{html.escape(sender_name)}</a>",
        "{chat}": html.escape(chat_title),
        "{date}": date_str,
        "{time}": time_str
    }
    for placeholder, value in replacements.items():
        text = text.replace(placeholder, str(value))
    return text

def _get_note_type(message: Message) -> str:
    """Xabardagi media turini aniqlaydi."""
    if message.photo: return "photo"
    if message.video: return "video"
    if message.audio: return "audio"
    if message.voice: return "voice"
    if message.sticker: return "sticker"
    if getattr(message, 'gif', None): return "gif"
    if message.video_note: return "video_note"
    if message.document: return "document"
    return "media"

# --- BUYRUQLAR HANDLERLARI ---

@userbot_cmd(command="savenote", description="Xabarga javob berib, uni eslatma sifatida saqlaydi.")
async def save_note_cmd(event: Message, context: AppContext):
    if not event.client or not event.text: return
    account_id = await get_account_id(context, event.client)
    if not account_id: return await event.edit(format_error("Akkaunt ID topilmadi."), parse_mode='html')

    args = event.text.split(maxsplit=1)
    if len(args) < 2:
        return await event.edit(format_error("Eslatma uchun nom kiriting: `.savenote <nomi>`"), parse_mode='html')
    
    name = args[1].strip()
    reply_to = await event.get_reply_message()
    if not reply_to:
        return await event.edit(format_error("Eslatma yaratish uchun xabarga javob bering."), parse_mode='html')

    await event.edit("<i>🔄 Eslatma saqlanmoqda...</i>", parse_mode='html')
    
    note_data = {
        "account_id": account_id,
        "name": name.lower(),
        "content": reply_to.text or "",
        "source_chat_id": event.chat_id,
        "source_message_id": reply_to.id,
        "note_type": _get_note_type(reply_to) if reply_to.media else "text"
    }
    
    await context.db.execute(
        "REPLACE INTO notes (account_id, name, content, source_chat_id, source_message_id, note_type) VALUES (?, ?, ?, ?, ?, ?)",
        tuple(note_data.values())
    )
    await event.edit(format_success(f"Eslatma {code('#' + name.lower())} saqlandi/yangilandi."), parse_mode='html')

@userbot_cmd(command="delnote", description="Saqlangan eslatmani o'chiradi.")
async def delete_note_cmd(event: Message, context: AppContext):
    if not event.client or not event.text: return
    account_id = await get_account_id(context, event.client)
    if not account_id: return await event.edit(format_error("Akkaunt ID topilmadi."), parse_mode='html')

    args = event.text.split(maxsplit=1)
    if len(args) < 2:
        return await event.edit(format_error("O'chirish uchun eslatma nomini kiriting."), parse_mode='html')
    
    name = args[1].strip().lower()
    
    deleted_rows = await context.db.execute("DELETE FROM notes WHERE account_id = ? AND name = ?", (account_id, name))
    
    if deleted_rows > 0:
        msg = format_success(f"Eslatma {code('#' + name)} o'chirildi.")
    else:
        msg = format_error(f"Eslatma {code('#' + name)} topilmadi.")
    await event.edit(msg, parse_mode='html')

@userbot_cmd(command="notes", description="Barcha saqlangan eslatmalar ro'yxatini ko'rsatadi.")
async def list_notes_cmd(event: Message, context: AppContext):
    if not event.client: return
    account_id = await get_account_id(context, event.client)
    if not account_id: return await event.edit(format_error("Akkaunt ID topilmadi."), parse_mode='html')

    all_notes = await context.db.fetchall("SELECT name, note_type FROM notes WHERE account_id = ? ORDER BY name", (account_id,))
    if not all_notes:
        return await event.edit("<b>Sizda saqlangan eslatmalar mavjud emas.</b>", parse_mode='html')

    type_icons = {"text": "📝", "photo": "🖼️", "video": "🎬", "audio": "🎵", "document": "📄", "voice": "🎤", "sticker": "✨", "gif": "🎇", "video_note": "🔘", "media": "📁"}
    notes_list = [f"{type_icons.get(note['note_type'], '📁')} {code('#' + note['name'])}" for note in all_notes]

    paginator = PaginationHelper(context=context, items=notes_list, title="Saqlangan Eslatmalar Ro'yxati", page_size=20, origin_event=event)
    await paginator.start()

@userbot_cmd(command="getnote", description="Eslatma haqida batafsil ma'lumot beradi.")
async def get_note_info_cmd(event: Message, context: AppContext):
    if not event.client or not event.text: return
    account_id = await get_account_id(context, event.client)
    if not account_id: return await event.edit(format_error("Akkaunt ID topilmadi."), parse_mode='html')

    args = event.text.split(maxsplit=1)
    if len(args) < 2:
        return await event.edit(format_error("Ma'lumot olish uchun eslatma nomini kiriting."), parse_mode='html')
    
    name = args[1].strip().lower()
    note = await context.db.fetchone("SELECT * FROM notes WHERE account_id = ? AND name = ?", (account_id, name))
    if not note:
        return await event.edit(format_error(f"Eslatma {code('#' + name)} topilmadi."), parse_mode='html')

    response = [f"{bold('Eslatma:')} {code('#' + name)}", f"{bold('Turi:')} {code(note['note_type'])}"]
    if note.get('source_message_id'):
        response.append(f"{bold('Media manbasi (ID):')} {code(f'{note.get("source_chat_id")}:{note.get("source_message_id")}')}")
    if note.get('content'):
        response.append(f"\n{bold('Matn tarkibi:')}\n<pre>{html.escape(str(note.get('content')))}</pre>")
    
    await event.edit("\n".join(response), parse_mode='html')

# YECHIM: Hashtag orqali chaqirish uchun yangi dekoratorli handler
@userbot_cmd(listen=events.NewMessage(outgoing=True, pattern=r"^#\w+"))
async def hashtag_note_handler(event: Message, context: AppContext):
    if not event.client or not event.text: return
    if not (account_id := await get_account_id(context, event.client)): return

    name = event.text.split()[0].lstrip('#').lower()
    note = await context.db.fetchone("SELECT * FROM notes WHERE account_id = ? AND name = ?", (account_id, name))
    if not note: return

    # O'zimiz yozgan eslatmani o'chirib, natijani yuboramiz
    await event.delete()
    
    content = await _parse_placeholders(note.get('content'), event)
    chat_id = note.get('source_chat_id')
    msg_id = note.get('source_message_id')
    
    try:
        source_message = None
        if chat_id and msg_id:
            source_message = await event.client.get_messages(int(chat_id), ids=int(msg_id))
        
        if source_message and isinstance(source_message, Message):
            await event.client.send_file(
                event.chat_id,
                file=source_message.media,
                caption=content,
                reply_to=event.reply_to_msg_id,
                parse_mode='html'
            )
        elif content:
            await event.respond(content, reply_to=event.reply_to_msg_id, parse_mode='html')
            
    except Exception as e:
        logger.warning(f"Eslatma yuborishda xato (note: #{name}): {e}. Matn sifatida yuborilmoqda.")
        if content:
            await event.respond(content, reply_to=event.reply_to_msg_id, parse_mode='html')
