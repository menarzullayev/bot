# bot/plugins/user/fun.py
"""
Ko'ngilochar buyruqlar uchun mo'ljallangan plagin (To'liq modernizatsiya qilingan va tuzatilgan).
"""

import asyncio
import hashlib
import html
import io
import os
import random
import textwrap
from math import floor
from typing import Optional

from loguru import logger
from PIL import Image, ImageDraw, ImageFont
from telethon.tl.custom import Message
from telethon.errors.rpcerrorlist import ReactionInvalidError
from telethon.tl.functions.messages import SendReactionRequest
from telethon.tl.types import ReactionEmoji

try:
    # YECHIM: Kutubxonani to'g'ri import qilish
    import cowsay
    COWSAY_AVAILABLE = True
except ImportError:
    cowsay = None
    COWSAY_AVAILABLE = False
    logger.warning("`cowsay` kutubxonasi topilmadi. .cowsay buyrug'i ishlamaydi.")

from core.app_context import AppContext
from bot.decorators import userbot_cmd
from bot.lib.telegram import get_user, get_display_name
from bot.lib.ui import format_error, format_success, bold

# --- Resurslar ---
MEME_FONT = "resources/impact.ttf"
COWSAY_FONT = "resources/DejaVuSansMono.ttf"
SLAP_TEMPLATES = [
    "<b>{name}</b>ning yuziga ulkan gulbaliq bilan urdi!",
    "<b>{name}</b>ni ho'l lagan bilan savaladi...",
    "<b>{name}</b>ga achchiq haqiqatni aytdi.",
]

# --- YORDAMCHI FUNKSIYALAR ---

def _create_cowsay_image(text: str) -> io.BytesIO:
    try:
        font = ImageFont.truetype(COWSAY_FONT, 30)
    except IOError:
        font = ImageFont.load_default()
    
    lines = text.split('\n')
    bbox = font.getbbox("A")
    line_height = bbox[3] - bbox[1]
    text_width = max(font.getbbox(line)[2] for line in lines)
    text_height = len(lines) * (line_height + 5)

    img = Image.new("RGB", (floor(text_width + 40), floor(text_height + 40)), color="white")
    draw = ImageDraw.Draw(img)
    draw.text((20, 20), text, fill="black", font=font)
    
    buffer = io.BytesIO()
    buffer.name = "cowsay.png"
    img.save(buffer, 'PNG')
    buffer.seek(0)
    return buffer

def _create_meme(image_path: str, top_text: str, bottom_text: str) -> io.BytesIO:
    img = Image.open(image_path).convert("RGB")
    draw = ImageDraw.Draw(img)
    
    try:
        font_size = int(img.height / 10)
        font = ImageFont.truetype(MEME_FONT, size=font_size)
    except IOError:
        font = ImageFont.load_default()

    def draw_text_with_outline(text_to_draw: str, is_top: bool):
        bbox = font.getbbox('A')
        char_width = bbox[2] - bbox[0]
        lines = textwrap.wrap(text_to_draw, width=int(img.width / (char_width * 0.9)) if char_width > 0 else 15)
        total_text_height = sum(font.getbbox(line)[3] + 5 for line in lines)
        y = 10 if is_top else img.height - total_text_height - 10

        for line in lines:
            line_bbox = font.getbbox(line)
            line_width = line_bbox[2]
            x = (img.width - line_width) / 2
            for pos in [(-2,-2), (2,-2), (-2,2), (2,2)]:
                draw.text((x + pos[0], y + pos[1]), line, font=font, fill="black")
            draw.text((x, y), line, font=font, fill="white")
            y += font.getbbox(line)[3] + 5

    if top_text: draw_text_with_outline(top_text.upper(), True)
    if bottom_text: draw_text_with_outline(bottom_text.upper(), False)

    buffer = io.BytesIO()
    buffer.name = "meme.png"
    img.save(buffer, 'PNG')
    buffer.seek(0)
    return buffer

def _get_persistent_random(seed_str: str, max_val: int) -> int:
    return int(hashlib.md5(seed_str.encode()).hexdigest(), 16) % max_val

# --- BUYRUQLAR ---

@userbot_cmd(command=["cowsay", "cowthink"], description="Matnni ASCII-art sigir ko'rinishida chiqaradi. Foydalanish: .cowsay [personaj] <matn>")
async def cowsay_cmd(event: Message, context: AppContext):
    if not COWSAY_AVAILABLE or not cowsay:
        return await event.edit(format_error("`cowsay` kutubxonasi o'rnatilmagan."), parse_mode='html')
    if not event.text or not event.client: return

    parts = event.text.split(maxsplit=2)
    if len(parts) < 2: return await event.edit(format_error("Matn kiriting."), parse_mode='html')

    command_name = "cowthink" if parts[0].endswith("think") else "cowsay"
    char_name, text = "default", parts[1]
    
    if len(parts) > 2 and parts[1] in getattr(cowsay, 'char_names', []):
        char_name, text = parts[1], parts[2]
        
    await event.edit("<i>🐮 Moo...</i>", parse_mode='html')
    try:
        # YECHIM: `getattr` orqali xavfsiz chaqiruv
        func_to_run = getattr(cowsay, command_name)
        output_text = await asyncio.to_thread(func_to_run, message=text, cow=char_name)

        mode = context.config.get("cowsay_mode", "text")
        if mode == "image":
            image_buffer = await asyncio.to_thread(_create_cowsay_image, output_text)
            await event.client.send_file(event.chat_id, image_buffer, reply_to=event.reply_to_msg_id)
            await event.delete()
        else:
            await event.edit(f"<code>{html.escape(output_text)}</code>", parse_mode='html')
    except Exception as e:
        await event.edit(format_error(f"Cowsay xatoligi: {e}"), parse_mode='html')


@userbot_cmd(command="cowsay-set", description="Cowsay uchun chiqarish rejimini o'zgartiradi. Foydalanish: .cowsay-set <text|image>")
async def set_cowsay_mode_cmd(event: Message, context: AppContext):
    if not event.text: return
    parts = event.text.split()
    if len(parts) < 2 or parts[1] not in ("text", "image"):
        return await event.edit(format_error("Format: <code>.cowsay-set <text|image></code>"), parse_mode='html')
    
    mode = parts[1]
    await context.config.set('cowsay_mode', mode)
    await event.edit(format_success(f"Cowsay rejimi '{bold(mode)}' holatiga o'rnatildi."), parse_mode='html')


@userbot_cmd(command="slap", description="Javob berilgan foydalanuvchiga 'zarba' beradi.")
async def slap_cmd(event: Message, context: AppContext):
    target_user, error = await get_user(context, event, "")
    if error or not target_user:
        return await event.edit(error or format_error("Kimga zarba berish kerak? Xabarga javob bering."), parse_mode='html')
    
    name = get_display_name(target_user)
    slap_text = random.choice(SLAP_TEMPLATES).format(name=bold(name))
    await event.edit(slap_text, parse_mode='html')


@userbot_cmd(command="react", description="Javob berilgan xabarga reaksiya yuboradi. Foydalanish: .react <emoji>")
async def react_cmd(event: Message, context: AppContext):
    if not (event.text and event.client and event.reply_to_msg_id):
        return await event.edit(format_error("Reaksiya yuborish uchun xabarga javob bering va emoji kiriting."), parse_mode='html')
    
    emojis = event.text.split()[1:]
    if not emojis:
        return await event.edit(format_error("Emoji kiriting. Namuna: `.react 👍🔥`"), parse_mode='html')

    try:
        if not (peer := await event.get_input_chat()):
            return await event.edit(format_error("Reaksiya uchun chatni aniqlab bo'lmadi."), parse_mode='html')

        await event.client(SendReactionRequest(
            peer=peer, msg_id=event.reply_to_msg_id, reaction=[ReactionEmoji(emoticon=e) for e in emojis]
        ))
        await event.delete()
    except ReactionInvalidError:
        await event.edit(format_error("Yaroqsiz reaksiya."), parse_mode='html')
    except Exception as e:
        await event.edit(format_error(f"Xatolik: {e}"), parse_mode='html')


@userbot_cmd(command="meme", description="Rasmga javob berib, klassik meme yaratadi. Foydalanish: .meme <yuqori matn> | [pastki matn]")
async def meme_cmd(event: Message, context: AppContext):
    if not event.text or not event.client: return
    
    reply_msg = await event.get_reply_message()
    if not (reply_msg and reply_msg.photo):
        return await event.edit(format_error("Meme yaratish uchun rasmga javob bering."), parse_mode='html')
    
    text = event.text.split(maxsplit=1)[1] if len(event.text.split()) > 1 else ""
    parts = text.split('|', 1)
    top_text = parts[0].strip()
    bottom_text = parts[1].strip() if len(parts) > 1 else ""

    await event.edit("<i>🎨 Meme yaratilmoqda...</i>", parse_mode='html')
    image_path: Optional[str] = await reply_msg.download_media()
    if not image_path:
        return await event.edit(format_error("Rasmni yuklab bo'lmadi."), parse_mode='html')
    
    try:
        meme_buffer = await asyncio.to_thread(_create_meme, image_path, top_text, bottom_text)
        await event.client.send_file(event.chat_id, meme_buffer, reply_to=reply_msg.id)
        await event.delete()
    except Exception as e:
        logger.exception("Meme yaratishda xato")
        await event.edit(format_error(f"Meme yaratishda xato: {e}"), parse_mode='html')
    finally:
        if image_path and os.path.exists(image_path):
            os.remove(image_path)


@userbot_cmd(command=["coin", "dice"], description="Tanga yoki shoshqol tashlaydi.")
async def random_cmd(event: Message, context: AppContext):
    if not event.text or not event.client: return
    command = event.text.split()[0].lstrip('.')
    
    if command == "coin":
        result = random.choice(["Oryol 🪙", "Reshka 🪙"])
        await event.edit(f"<b>Tanga tashlandi... Natija:</b> {result}", parse_mode='html')
    elif command == "dice":
        await event.delete()
        await event.client.send_message(event.chat_id, "🎲", reply_to=event.reply_to_msg_id)


@userbot_cmd(command="how", description="Foydalanuvchining biror 'sifatini' foizda o'lchaydi. Foydalanish: .how <sifat> [foydalanuvchi]")
async def how_cmd(event: Message, context: AppContext):
    if not event.text: return
    parts = event.text.split(maxsplit=2)
    if len(parts) < 2:
        return await event.edit(format_error("Format: `.how <sifat> [foydalanuvchi]`"), parse_mode='html')

    quality = parts[1]
    target_arg = parts[2] if len(parts) > 2 else ""

    user, error = await get_user(context, event, target_arg)
    if error or not user:
        return await event.edit(error or format_error("Kimni tekshirish kerak?"), parse_mode='html')

    name = get_display_name(user)
    seed = f"{quality}-{user.id}"
    percentage = _get_persistent_random(seed, 101)
    await event.edit(f"<b>📊 Tekshiruv natijasi:</b>\n<a href='tg://user?id={user.id}'>{name}</a> {bold(f'{percentage}%')} {quality}.", parse_mode='html')
