# bot/plugins/admin/files_cmds.py
"""
Userbot ishlayotgan serverdagi fayl tizimi bilan ishlash uchun
mo'ljallangan admin plaginlari.
"""
import asyncio
import html
import os
import uuid
import shlex
import shutil
from datetime import datetime
from pathlib import Path
from typing import List, Optional

from loguru import logger
from telethon.tl.custom import Message

from core.app_context import AppContext
from bot.decorators import userbot_cmd
from bot.lib.auth import admin_only, owner_only
from bot.lib.system import resolve_secure_path
from bot.lib.telegram import edit_message
from bot.lib.ui import (
    PaginationHelper,
    format_error,
    format_success,
    request_confirmation,
    send_as_file_if_long,
)
from bot.lib.utils import RaiseArgumentParser, humanbytes



# ===== YORDAMCHI FUNKSIYALAR =====

def _get_directory_listing(secure_path: Path, long_format: bool, recursive: bool) -> List[str]:
    """Papkadagi fayllar ro'yxatini formatlangan matn ko'rinishida tayyorlaydi."""

    def _format_item(item_path: Path) -> str:
        """Bitta fayl yoki papka uchun formatlangan qatorni yaratadi."""
        try:
            stat = item_path.stat()
            is_dir = item_path.is_dir()
            name = item_path.name
            
            if long_format:
                return "<code>{size:<10} {time} {name}{suffix}</code>".format(
                    size=humanbytes(stat.st_size) if not is_dir else "DIR",
                    time=datetime.fromtimestamp(stat.st_mtime).strftime('%y-%m-%d %H:%M'),
                    name=html.escape(name),
                    suffix='/' if is_dir else ''
                )
            return "• <code>{name}{suffix}</code>".format(name=html.escape(name), suffix='/' if is_dir else '')
        except OSError as e:
            logger.warning(f"Fayl statistikasini o'qib bo'lmadi: {item_path}, xato: {e}")
            return f"• <code>{html.escape(item_path.name)}</code> (xatolik)"

    if recursive:
        lines: List[str] = []
        for root, dirs, files in os.walk(secure_path):
            # Ichma-ich papkalar uchun chiroyli ko'rinish
            rel_path = os.path.relpath(root, secure_path)
            if rel_path != '.':
                lines.append(f"\n<b>./{html.escape(rel_path)}/:</b>")
            
            for name in sorted(dirs + files, key=str.lower):
                lines.append("  " + _format_item(Path(root) / name))
        return lines
    else:
        items = sorted(secure_path.iterdir(), key=lambda p: (not p.is_dir(), p.name.lower()))
        return [_format_item(item) for item in items]

# ===== ASOSIY BUYRUQLAR =====

@userbot_cmd(command="ls", description="Serverdagi fayllar ro'yxatini ko'rsatadi.")
@admin_only
async def ls_handler(event: Message, context: AppContext):
    """
    .ls .
    .ls -l bot/plugins/
    .ls -R data/
    """
    if not event.text: return
    args_str = event.text.split(maxsplit=1)[1] if len(event.text.split()) > 1 else "."
    
    parser = RaiseArgumentParser(prog=".ls")
    parser.add_argument('path', nargs='?', default='.')
    parser.add_argument('-l', '--long', action='store_true')
    parser.add_argument('-R', '--recursive', action='store_true')

    try:
        args = parser.parse_args(shlex.split(args_str))
    except ValueError as e:
        return await event.edit(format_error(f"Argument xatosi: {e}"))

    secure_path = resolve_secure_path(args.path)
    if not (secure_path and secure_path.exists() and secure_path.is_dir()):
        return await event.edit(format_error(f"Papkasi topilmadi yoki yo'l xavfsiz emas: <code>{args.path}</code>"))

    await event.edit(f"<code>🔄 '{html.escape(str(secure_path))}' papkasi o'qilmoqda...</code>")
    try:
        file_lines = await asyncio.to_thread(_get_directory_listing, secure_path, args.long, args.recursive)
        
        if not file_lines:
            return await event.edit(f"<b>📂 '{html.escape(args.path)}' papkasi bo'sh.</b>")

        # TUZATISH: PaginationHelper nomli argumentlar bilan chaqirilmoqda
        pagination = PaginationHelper(
            context=context,
            items=file_lines,
            title=f"📁 <code>{html.escape(str(secure_path))}</code>",
            origin_event=event
        )
        await pagination.start()
    except Exception as e:
        await event.edit(format_error(f"Fayllarni o'qishda xatolik:\n<code>{html.escape(str(e))}</code>"))


@userbot_cmd(command="rm", description="Fayl yoki papkani xavfsiz o'chiradi.")
@owner_only
async def rm_handler(event: Message, context: AppContext):
    """ .rm path/to/useless_file.txt """
    if not event.text or not event.sender_id: return
    
    path_or_code = event.text.split(maxsplit=1)[1] if len(event.text.split()) > 1 else ""
    if not path_or_code:
        return await edit_message(event, format_error("O'chiriladigan fayl/papka yoki tasdiqlash kodini kiriting."))

    confirm_key = f"confirm_rm:{event.sender_id}:{path_or_code}"
    original_path_data = context.state.get(confirm_key)

    if original_path_data and isinstance(original_path_data, dict) and 'path' in original_path_data:
        original_path_str = original_path_data['path']
        
        # YECHIM: Tasdiqdan keyin ham yo'lni qayta tekshiramiz
        secure_path = resolve_secure_path(original_path_str)
        if not (secure_path and secure_path.exists()):
             return await edit_message(event, format_error(f"Fayl/papka topilmadi yoki yo'l o'zgargan: <code>{original_path_str}</code>"))

        await edit_message(event, f"<code>✅ Tasdiqlandi. '{html.escape(str(secure_path))}' o'chirilmoqda...</code>")
        try:
            if secure_path.is_dir():
                await asyncio.to_thread(shutil.rmtree, secure_path)
                msg = f"🗑️ <b>Papka o'chirildi:</b> <code>{html.escape(original_path_str)}</code>"
            else:
                await asyncio.to_thread(secure_path.unlink)
                msg = f"🗑️ <b>Fayl o'chirildi:</b> <code>{html.escape(original_path_str)}</code>"
            
            await edit_message(event, format_success(msg))
        except Exception as e:
            await edit_message(event, format_error(f"O'chirishda xatolik:\n<code>{html.escape(str(e))}</code>"))
        finally:
            await context.state.delete(confirm_key)
        return

    secure_path = resolve_secure_path(path_or_code)
    if not (secure_path and secure_path.exists()):
        return await edit_message(event, format_error(f"Fayl/papka topilmadi yoki yo'l xavfsiz emas: <code>{path_or_code}</code>"))

    confirm_code = str(uuid.uuid4().hex[:6])
    new_confirm_key = f"confirm_rm:{event.sender_id}:{confirm_code}"
    
    await context.state.set(new_confirm_key, {'path': path_or_code}, ttl_seconds=30, persistent=False)
    
    prompt_text = (
        f"⚠️ <b>DIQQAT!</b> Siz 'fayl/papkani o'chirish:\n"
        f"<code>{html.escape(str(secure_path))}</code>' amalini bajaryapsiz.\n\n"
        f"✅ Davom etish uchun <b>30 soniya ichida</b> quyidagi buyruqni yuboring:\n"
        f"<code>.rm {confirm_code}</code>"
    )
    await edit_message(event, prompt_text)



@userbot_cmd(command="upload", description="Serverdagi faylni chatga yuklaydi.")
@admin_only
async def upload_handler(event: Message, context: AppContext):
    """ .upload data/app_state.json """
    if not event.text: return
    path_str = event.text.split(maxsplit=1)[1] if len(event.text.split()) > 1 else ""
    if not path_str:
        return await event.edit(format_error("Yuklanadigan fayl yo'lini kiriting."))

    secure_path = resolve_secure_path(path_str)
    if not (secure_path and secure_path.exists() and secure_path.is_file()):
        return await event.edit(format_error(f"Fayl topilmadi yoki yo'l xavfsiz emas: <code>{path_str}</code>"))

    # XATOLIK TUZATILDI: `event.client` mavjudligini tekshiramiz
    if not event.client:
        return await event.edit(format_error("Faylni yuklash uchun klient topilmadi."))

    await event.edit(f"<code>🔄 '{secure_path.name}' fayli yuborilmoqda...</code>")
    try:
        await event.client.send_file(
            event.chat_id, str(secure_path),
            reply_to=event.reply_to_msg_id or event.id, force_document=True
        )
        await event.delete()
    except Exception as e:
        # Xatolik bo'lsa, tahrirlashga harakat qilamiz
        await edit_message(event, format_error(f"Faylni yuklashda xatolik:\n<code>{html.escape(str(e))}</code>"))



@userbot_cmd(command="cat", description="Serverdagi matnli fayl tarkibini ko'rsatadi.")
@admin_only
async def cat_handler(event: Message, context: AppContext):
    """ .cat bot/lib/ui.py """
    if not event.text: return
    path_str = event.text.split(maxsplit=1)[1] if len(event.text.split()) > 1 else ""
    if not path_str:
        return await event.edit(format_error("Tarkibi ko'rsatiladigan fayl yo'lini kiriting."))

    secure_path = resolve_secure_path(path_str)
    if not (secure_path and secure_path.exists() and secure_path.is_file()):
        return await event.edit(format_error(f"Fayl topilmadi yoki yo'l xavfsiz emas: <code>{path_str}</code>"))

    await event.edit(f"<code>🔄 '{secure_path.name}' fayli o'qilmoqda...</code>")
    try:
        content = await asyncio.to_thread(secure_path.read_text, encoding='utf-8', errors='ignore')
        response_text = f"<b>📄 Fayl:</b> <code>{secure_path.name}</code>\n\n<pre>{html.escape(content)}</pre>"
        await send_as_file_if_long(event, response_text, filename=secure_path.name)
    except Exception as e:
        await event.edit(format_error(f"Faylni o'qishda xatolik:\n<code>{html.escape(str(e))}</code>"))


@userbot_cmd(command="mkdir", description="Yangi papka yaratadi.")
@admin_only
async def mkdir_handler(event: Message, context: AppContext):
    """ .mkdir data/new_folder """
    if not event.text: return
    path_str = event.text.split(maxsplit=1)[1] if len(event.text.split()) > 1 else ""
    if not path_str:
        return await event.edit(format_error("Yaratiladigan papka yo'lini kiriting."))

    secure_path = resolve_secure_path(path_str)
    if not secure_path:
        return await event.edit(format_error("Xavfsizlik cheklovi: Bu yo'lda papka yaratib bo'lmaydi."))

    try:
        await asyncio.to_thread(secure_path.mkdir, parents=True, exist_ok=True)
        await event.edit(format_success(f"<b>Papka yaratildi:</b> <code>{html.escape(str(secure_path))}</code>"))
    except Exception as e:
        await event.edit(format_error(f"Papka yaratishda xatolik:\n<code>{html.escape(str(e))}</code>"))


@userbot_cmd(command="mv", description="Fayl/papka nomini yoki joyini o'zgartiradi.")
@owner_only
async def mv_handler(event: Message, context: AppContext):
    """ .mv "eski/nom.txt" "yangi/nom.txt" """
    if not event.text: return
    args_str = event.text.split(maxsplit=1)[1] if len(event.text.split()) > 1 else ""
    try:
        parts = shlex.split(args_str)
    except ValueError:
        return await event.edit(format_error("Qo'shtirnoqlar to'g'ri yopilmagan."))
        
    if len(parts) != 2:
        return await event.edit(format_error("<b>Format:</b> <code>.mv \"eski yo'l\" \"yangi yo'l\"</code>"))

    src_str, dst_str = parts
    src_path = resolve_secure_path(src_str)
    dst_path = resolve_secure_path(dst_str)
    
    if not (src_path and src_path.exists()):
        return await event.edit(format_error(f"Manba topilmadi yoki xavfsiz emas: <code>{src_str}</code>"))
    if not dst_path:
        return await event.edit(format_error(f"Nishon yo'li xavfsiz emas: <code>{dst_str}</code>"))

    try:
        await asyncio.to_thread(shutil.move, str(src_path), str(dst_path))
        msg = (f"<b>Ko'chirildi:</b>\n"
               f" • <b>Manba:</b> <code>{html.escape(src_str)}</code>\n"
               f" • <b>Nishon:</b> <code>{html.escape(dst_str)}</code>")
        await event.edit(format_success(msg))
    except Exception as e:
        await event.edit(format_error(f"Ko'chirishda xatolik:\n<code>{html.escape(str(e))}</code>"))

