# bot/plugins/admin/settings_cmds.py
"""
Userbotning dinamik va statik sozlamalarini (.env fayli va ma'lumotlar bazasi)
boshqarish uchun mo'ljallangan admin plaginlari.
"""

import html
from typing import Any

from loguru import logger
from telethon.tl.custom import Message

from core.app_context import AppContext
from bot.decorators import userbot_cmd
from bot.lib.auth import admin_only, owner_only
from bot.lib.ui import PaginationHelper, format_error, format_success
from bot.lib.utils import parse_string_to_value

PROTECTED_KEYS = {
    "API_ID", "API_HASH", "OWNER_ID", "DB_PATH", "LOG_FILE_PATH", "GEMINI_API_KEY",
}
MSG_ENTER_KEY = "Sozlama nomini kiriting."
MSG_FORMAT_ERROR = "<b>Format:</b> <code>.setvar KEY VALUE</code>"


@userbot_cmd(command="vars", description="Dinamik sozlamalar ro'yxatini ko'rsatadi.")
@admin_only
async def list_vars_handler(event: Message, context: AppContext):
    """
    .vars              # Barcha sozlamalar
    .vars afk          # Nomida "afk" so'zi bor sozlamalar
    """
    if not event.text:
        return
    q = event.text.split(maxsplit=1)[1] if len(event.text.split()) > 1 else ""

    await event.edit("<code>🔄 Sozlamalar olinmoqda...</code>", parse_mode='html')

    sql = "SELECT key, value, type, description FROM dynamic_settings"
    params = ()
    if q:
        sql += " WHERE key LIKE ?"
        params = (f"%{q}%",)
    sql += " ORDER BY key"

    all_settings = await context.db.fetchall(sql, params)

    if not all_settings:
        return await event.edit(format_error("Sizning qidiruvingizga mos sozlamalar topilmadi."), parse_mode='html')

    lines = []
    for s in all_settings:
        value_str = str(s['value'])
        display_value = (value_str[:50] + '...') if len(value_str) > 50 else value_str
        lines.append(
            f"• <code>{html.escape(s['key'])}</code> "
            f"[<i>{s['type']}</i>] = "
            f"<code>{html.escape(display_value)}</code>"
        )

    title = f"⚙️ Dinamik Sozlamalar ({len(all_settings)} ta)"
    if q:
        title += f" (filter: '{html.escape(q)}')"
        
    # TUZATISH: PaginationHelper nomli argumentlar bilan chaqirilmoqda
    pagination = PaginationHelper(context=context, items=lines, title=title, origin_event=event)
    await pagination.start()


@userbot_cmd(command="getvar", description="Sozlamaning qiymati va ma'lumotlarini oladi.")
@admin_only
async def get_var_handler(event: Message, context: AppContext):
    """ .getvar AFK_MESSAGE """
    if not event.text:
        return
    key = event.text.split(maxsplit=1)[1] if len(event.text.split()) > 1 else ""
    if not key:
        return await event.edit(format_error(MSG_ENTER_KEY), parse_mode='html')

    value = context.config.get(key)

    if value is None:
        return await event.edit(format_error(f"<code>{html.escape(key)}</code> nomli sozlama topilmadi."), parse_mode='html')

    db_setting = await context.db.fetchone("SELECT * FROM dynamic_settings WHERE key = ?", (key,))

    if db_setting:
        res = (
            f"<b>⚙️ Dinamik Sozlama:</b> <code>{html.escape(key)}</code>\n\n"
            f"<b>Qiymat:</b> <pre>{html.escape(str(value))}</pre>\n"
            f"<b>Turi:</b> <code>{db_setting['type']}</code>\n"
            f"<b>Tavsifi:</b> <i>{html.escape(db_setting['description'] or 'Yo\'q')}</i>\n"
            f"<b>O'zgartirildi:</b> <code>{db_setting['last_modified']}</code>"
        )
    else:
        res = (
            f"<b>⚙️ Statik Sozlama:</b> <code>{html.escape(key)}</code>\n\n"
            f"<b>Qiymat:</b> <pre>{html.escape(str(value))}</pre>\n"
            f"<b>Manba:</b> <code>.env</code> fayli (o'zgartirib bo'lmaydi)"
        )
    await event.edit(res, parse_mode='html')


@userbot_cmd(command="setvar", description="Dinamik sozlamaning qiymatini o'rnatadi.")
@owner_only
async def set_var_handler(event: Message, context: AppContext):
    """
    .setvar PREFIX .
    .setvar DANGEROUS_COMMANDS ["purge", "eval"]
    .setvar ENABLE_SPAM_PROTECTION true
    """
    if not event.text:
        return
    parts = event.text.split(maxsplit=2)
    if len(parts) < 3:
        return await event.edit(MSG_FORMAT_ERROR, parse_mode='html')
    
    key, value_str = parts[1], parts[2]

    if key in PROTECTED_KEYS:
        return await event.edit(format_error(f"<b><code>{key}</code></b> himoyalangan, uni faqat <code>.env</code> fayli orqali o'zgartirish mumkin."), parse_mode='html')

    try:
        final_value = parse_string_to_value(value_str)
        await context.config.set(key, final_value)
        await event.edit(format_success(f"<b>Sozlama o'rnatildi:</b>\n<code>{key} = {html.escape(str(final_value))}</code>"), parse_mode='html')
    except Exception as err:
        logger.error(f"Sozlamani ('{key}') o'rnatishda xato: {err}", exc_info=True)
        await event.edit(format_error(f"Kutilmagan xato: {err}"), parse_mode='html')


@userbot_cmd(command="delvar", description="Dinamik sozlamani o'chiradi.")
@owner_only
async def del_var_handler(event: Message, context: AppContext):
    """ .delvar USELESS_SETTING """
    if not event.text:
        return
    key = event.text.split(maxsplit=1)[1] if len(event.text.split()) > 1 else ""
    if not key:
        return await event.edit(format_error(MSG_ENTER_KEY), parse_mode='html')

    if key in PROTECTED_KEYS:
        return await event.edit(format_error(f"<b><code>{key}</code></b> himoyalangan sozlamani o'chirib bo'lmaydi."), parse_mode='html')

    if await context.config.delete(key):
        await event.edit(format_success(f"Sozlama <code>{key}</code> o'chirildi."), parse_mode='html')
    else:
        await event.edit(format_error(f"<code>{key}</code> dinamik sozlamalar orasidan topilmadi."), parse_mode='html')


@userbot_cmd(command="togglevar", description="Boolean (ha/yo'q) turidagi sozlamani almashtiradi.")
@admin_only
async def toggle_var_handler(event: Message, context: AppContext):
    """ .togglevar ENABLE_AFK """
    if not event.text:
        return
    key = event.text.split(maxsplit=1)[1] if len(event.text.split()) > 1 else ""
    if not key:
        return await event.edit(format_error(MSG_ENTER_KEY), parse_mode='html')

    current_value = context.config.get(key)
    if not isinstance(current_value, bool):
        return await event.edit(format_error(f"<b><code>{key}</code></b> sozlamasi boolean (ha/yo'q) turida emas."), parse_mode='html')

    new_value = not current_value
    await context.config.set(key, new_value)
    status = "✅ Yoqildi" if new_value else "❌ O'chirildi"
    await event.edit(f"<b>Sozlama <code>{html.escape(key)}</code> o'zgardi: {status}</b>", parse_mode='html')


@userbot_cmd(command="addtovar", description="Ro'yxatli sozlamaga yangi qiymat qo'shadi.")
@admin_only
async def add_to_var_handler(event: Message, context: AppContext):
    """
    .addtovar SUDO_USERS 12345678
    .addtovar IGNORED_CHATS -100123456789
    """
    if not event.text:
        return
    parts = event.text.split(maxsplit=2)
    if len(parts) < 3:
        return await event.edit(format_error("<b>Format:</b> <code>.addtovar &lt;kalit&gt; &lt;qiymat&gt;</code>"), parse_mode='html')
    
    key, value_str = parts[1], parts[2]
    current_list = context.config.get(key, [])
    if not isinstance(current_list, list):
        return await event.edit(format_error(f"<b><code>{html.escape(key)}</code></b> sozlamasi ro'yxat turida emas."), parse_mode='html')

    try:
        new_value = parse_string_to_value(value_str)
        if new_value not in current_list:
            current_list.append(new_value)
            await context.config.set(key, current_list)
            await event.edit(format_success(f"<code>{html.escape(str(new_value))}</code> qiymati <code>{html.escape(key)}</code> ga qo'shildi."), parse_mode='html')
        else:
            await event.edit(f"ℹ️ Qiymat <code>{html.escape(key)}</code> da allaqachon mavjud.", parse_mode='html')
    except Exception as err:
        logger.exception(f"Ro'yxatga qiymat qo'shishda xato: {err}")
        await event.edit(format_error(f"Qiymat qo'shishda xato: {html.escape(str(err))}"), parse_mode='html')
