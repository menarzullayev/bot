# /bot/plugins/user/qr.py
"""
QR-kodlarni generatsiya qilish (text, wifi, vcard) va o'qish uchun mo'ljallangan plagin.
(To'liq modernizatsiya qilingan).
"""
import asyncio
import io
import html
import os
import shlex
from typing import Optional, Any

from PIL import Image
import qrcode
from qrcode.image.pil import PilImage
from qrcode.constants import ERROR_CORRECT_L, ERROR_CORRECT_M, ERROR_CORRECT_Q, ERROR_CORRECT_H
from loguru import logger
from telethon.tl.custom import Message

from core.app_context import AppContext
from bot.decorators import userbot_cmd
from bot.lib.ui import format_error, code
from bot.lib.utils import RaiseArgumentParser

try:
    from pyzbar.pyzbar import decode as qr_decode_func
    PYZBAR_AVAILABLE = True
except ImportError:
    PYZBAR_AVAILABLE, qr_decode_func = False, None
    logger.warning("pyzbar kutubxonasi topilmadi. .qrr buyrug'i ishlamaydi.")


# ===== YORDAMCHI FUNKSIYALAR =====

async def _generate_qr_image(text: str, **kwargs) -> io.BytesIO:
    """Asinxron ravishda QR-kod rasmini generatsiya qiladi."""
    def _sync_generate():
        error_map = {'L': ERROR_CORRECT_L, 'M': ERROR_CORRECT_M, 'Q': ERROR_CORRECT_Q, 'H': ERROR_CORRECT_H}
        qr = qrcode.QRCode(
            error_correction=error_map.get(str(kwargs.get('e', 'L')).upper(), ERROR_CORRECT_L),
            box_size=10, border=4,
        )
        qr.add_data(text)
        qr.make(fit=True)
        img = qr.make_image(
            image_factory=PilImage,
            fill_color=str(kwargs.get('fill', 'black')),
            back_color=str(kwargs.get('back', 'white'))
        ).convert('RGB')

        buffer = io.BytesIO()
        buffer.name = 'qrcode.png'
        img.save(buffer, 'PNG')
        buffer.seek(0)
        return buffer
    return await asyncio.to_thread(_sync_generate)

async def _decode_qr_image(image_path: str) -> list[str]:
    """Asinxron ravishda rasmdan QR-kodni o'qiydi."""
    def _sync_decode():
        if not qr_decode_func: return []
        with Image.open(image_path) as img:
            return [d.data.decode('utf-8') for d in qr_decode_func(img)]
    return await asyncio.to_thread(_sync_decode)

async def _build_qr_data(args: Any) -> tuple[str, str]:
    """Argumentlardan QR ma'lumotlarini va xabar matnini quradi."""
    text, caption = "", ""
    command = getattr(args, 'command', 'text')

    if command == 'wifi':
        text = f"WIFI:S:{args.ssid};T:{args.type};P:{args.password};;"
        caption = f"<b>Wi-Fi Network:</b> {code(args.ssid)}"
    elif command == 'vcard':
        vcard_parts = [f"BEGIN:VCARD\nVERSION:3.0\nFN:{args.name}"]
        if args.tel: vcard_parts.append(f"TEL;TYPE=CELL:{args.tel}")
        if args.email: vcard_parts.append(f"EMAIL:{args.email}")
        if args.work: vcard_parts.append(f"ORG:{args.work}")
        vcard_parts.append("END:VCARD")
        text = "\n".join(vcard_parts)
        caption = f"<b>Kontakt:</b> {code(args.name)}"
    else: # command == 'text'
        text = " ".join(args.content).strip()
        if not text:
            raise ValueError("Matn kiriting yoki matnli xabarga javob bering.")
        caption = f"<b>QR-kod matni:</b>\n{code(text)}"
        
    return text, caption

# ===== BUYRUQLAR HANDLERLARI =====

@userbot_cmd(command="qr", description="Matn, Wi-Fi yoki vCard uchun QR-kod yaratadi.")
async def qr_generate_handler(event: Message, context: AppContext):
    if not event.client: return
    
    args_str = (event.text or "").split(maxsplit=1)[1] if len((event.text or "").split()) > 1 else ""
    
    # Agar argument bo'lmasa yoki matnli xabarga javob bo'lsa, 'text' rejimini ishlatamiz
    if not args_str:
        replied = await event.get_reply_message()
        if replied and replied.text:
            args_str = f"text {replied.text}"
        else:
             return await event.edit(format_error("QR-kod yaratish uchun matn kiriting yoki matnli xabarga javob bering."), parse_mode='html')

    parser = RaiseArgumentParser(prog=".qr")
    subparsers = parser.add_subparsers(dest="command")
    
    # Argparse sozlamalari
    text_parser = subparsers.add_parser('text', help="Oddiy matn uchun")
    text_parser.add_argument('content', nargs='*', help="QR-kodga joylanadigan matn")
    
    wifi_parser = subparsers.add_parser('wifi', help="Wi-Fi tarmog'i uchun")
    wifi_parser.add_argument('-s', '--ssid', required=True, help="Wi-Fi nomi")
    wifi_parser.add_argument('-p', '--password', default="", help="Wi-Fi paroli")
    wifi_parser.add_argument('-t', '--type', default="WPA", choices=['WPA', 'WEP'], help="Shifrlash turi")
    
    vcard_parser = subparsers.add_parser('vcard', help="vCard kontakti uchun")
    vcard_parser.add_argument('-n', '--name', required=True, help="To'liq ism")
    vcard_parser.add_argument('--tel', help="Telefon raqami")
    vcard_parser.add_argument('--email', help="Elektron pochta")
    vcard_parser.add_argument('--work', help="Ish joyi")
    
    try:
        args_list = shlex.split(args_str)
        if not args_list or args_list[0] not in subparsers.choices:
            args_list.insert(0, 'text')
        args = parser.parse_args(args_list)
    except (ValueError, SystemExit) as e:
        return await event.edit(format_error(f"Argument xatosi: {e}"), parse_mode='html')

    await event.edit("<i>🔄 QR-kod generatsiya qilinmoqda...</i>", parse_mode='html')
    try:
        text, caption = await _build_qr_data(args)
        image_buffer = await _generate_qr_image(text)
        
        await event.client.send_file(event.chat_id, image_buffer, caption=caption, reply_to=event.id, parse_mode='html')
        await event.delete()
    except ValueError as e:
        await event.edit(format_error(str(e)), parse_mode='html')
    except Exception as e:
        logger.exception("QR generatsiya qilishda xato")
        await event.edit(format_error(f"<b>Noma'lum xatolik:</b>\n<code>{html.escape(str(e))}</code>"), parse_mode='html')


@userbot_cmd(command="qrr", description="Rasmdagi QR-kodni o'qiydi (QR-Read).")
async def qr_decode_handler(event: Message, context: AppContext):
    if not PYZBAR_AVAILABLE:
        return await event.edit(format_error("QR o'qish uchun `pyzbar` kutubxonasi o'rnatilmagan."), parse_mode='html')

    replied = await event.get_reply_message()
    if not (replied and replied.photo):
        return await event.edit(format_error("QR-kod o'qish uchun rasmga javob bering."), parse_mode='html')
        
    await event.edit("<i>🖼 Rasmdagi QR-kod o'qilmoqda...</i>", parse_mode='html')
    
    download_path: Optional[str] = None
    try:
        download_path = await replied.download_media(file="cache/")
        if not download_path:
            return await event.edit(format_error("Rasm faylini yuklab bo'lmadi."), parse_mode='html')

        decoded_data = await _decode_qr_image(download_path)
        if not decoded_data:
            return await event.edit("❌ Bu rasmda QR-kod topilmadi.", parse_mode='html')

        response = "✅ <b>O'qilgan ma'lumotlar:</b>\n\n" + "\n".join(
            f"<code>{i}. {html.escape(data)}</code>" for i, data in enumerate(decoded_data, 1)
        )
        await event.edit(response, parse_mode='html')
    except Exception as e:
        await event.edit(format_error(f"QR o'qishda xatolik:\n<code>{html.escape(str(e))}</code>"), parse_mode='html')
    finally:
        if download_path and os.path.exists(download_path):
            os.remove(download_path)

