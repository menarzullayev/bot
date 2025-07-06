# bot/plugins/admin/users_cmds.py
"""
Userbot ma'muriyatini (adminlarni) boshqarish uchun mo'ljallangan plagin.
"""

import asyncio
import html
import shlex
from datetime import datetime

from loguru import logger
from telethon.tl.custom import Message
from telethon.tl.types import User

from core.app_context import AppContext
from bot.decorators import userbot_cmd
from bot.lib.auth import admin_only, owner_only, invalidate_admin_cache
from bot.lib.telegram import get_user, get_display_name
from bot.lib.ui import PaginationHelper, format_error, format_success

# Admin darajalari va ularning nomlari
LEVEL_NAMES = {
    100: "OWNER",
    95: "CONFIG_ADMIN",
    90: "SUPER_ADMIN",
    50: "ADMIN",
}


@userbot_cmd(command=["promote", "addadmin"], description="Foydalanuvchini bot admini qiladi.")
@owner_only  # Faqat bot egasi yangi admin qo'sha oladi
async def promote_handler(event: Message, context: AppContext):
    """
    .promote @username
    .promote 123456789 90
    """
    if not event.text or not event.sender_id:
        return

    try:
        args = shlex.split(event.text.split(maxsplit=1)[1])
    except (ValueError, IndexError):
        return await event.edit(format_error("Foydalanuvchini ko'rsating."), parse_mode='html')

    if not args:
        return await event.edit(format_error("Foydalanuvchi/daraja kiriting (misol: <code>.promote @username 90</code>)"), parse_mode='html')

    user_ref = args[0]
    level = 50  # Standart daraja
    if len(args) > 1 and args[1].isdigit():
        level = int(args[1])
        if level >= 95:
            return await event.edit(format_error("95 va undan yuqori daraja faqat <code>.env</code> fayli orqali beriladi."), parse_mode='html')

    user, error = await get_user(context, event, user_ref)
    if not user:
        return await event.edit(error or format_error("Foydalanuvchi topilmadi."), parse_mode='html')

    user_display_name = get_display_name(user)

    if user.id == context.config.get("OWNER_ID") or user.id in context.config.get("ADMIN_IDS", []):
        return await event.edit(f"ℹ️ <b>{user_display_name}</b> allaqachon asosiy admin hisoblanadi.", parse_mode='html')

    if await context.db.fetchone("SELECT 1 FROM admins WHERE user_id = ?", (user.id,)):
        return await event.edit(f"ℹ️ <b>{user_display_name}</b> allaqachon ma'lumotlar bazasida admin sifatida mavjud.", parse_mode='html')

    await context.db.execute(
        "INSERT INTO admins (user_id, permission_level, added_by, added_date) VALUES (?, ?, ?, ?)",
        (user.id, level, event.sender_id, datetime.now())
    )
    await invalidate_admin_cache(context)

    level_name = LEVEL_NAMES.get(level, f"LVL_{level}")
    await event.edit(format_success(f"<b>{user_display_name}</b> (<code>{user.id}</code>) <b>{level_name}</b> darajasida admin etib tayinlandi."), parse_mode='html')


@userbot_cmd(command=["demote", "deladmin"], description="Foydalanuvchini adminlikdan oladi.")
@owner_only # Faqat bot egasi adminni o'chira oladi
async def demote_handler(event: Message, context: AppContext):
    """ .demote @username """
    if not event.text:
        return
    
    user_ref = event.text.split(maxsplit=1)[1] if len(event.text.split()) > 1 else ""
    if not user_ref:
        return await event.edit(format_error("Adminlikdan olinadigan foydalanuvchini ko'rsating."), parse_mode='html')

    user, error = await get_user(context, event, user_ref)
    if not user:
        return await event.edit(error or format_error("Foydalanuvchi topilmadi."), parse_mode='html')

    if user.id == context.config.get("OWNER_ID") or user.id in context.config.get("ADMIN_IDS", []):
        return await event.edit(format_error("Bu foydalanuvchini adminlikdan olish uchun <code>.env</code> faylini o'zgartiring."), parse_mode='html')

    if not await context.db.fetchone("SELECT 1 FROM admins WHERE user_id = ?", (user.id,)):
        return await event.edit(format_error("Bu foydalanuvchi ma'lumotlar bazasida admin emas."), parse_mode='html')

    await context.db.execute("DELETE FROM admins WHERE user_id = ?", (user.id,))
    await invalidate_admin_cache(context)

    user_display_name = get_display_name(user)
    await event.edit(format_success(f"<b>{user_display_name}</b> (<code>{user.id}</code>) adminlar ro'yxatidan o'chirildi."), parse_mode='html')


@userbot_cmd(command="admins", description="Barcha bot adminlari ro'yxatini ko'rsatadi.")
@admin_only
async def list_admins_handler(event: Message, context: AppContext):
    if not event.client:
        return

    await event.edit("<code>🔄 Adminlar ro'yxati olinmoqda...</code>", parse_mode='html')

    db_admins = {row['user_id']: row['permission_level'] for row in await context.db.fetchall("SELECT user_id, permission_level FROM admins")}
    config_admins = dict.fromkeys(context.config.get("ADMIN_IDS", []), 95)
    if owner_id := context.config.get("OWNER_ID"):
        config_admins[owner_id] = 100

    all_admins = {**db_admins, **config_admins}
    if not all_admins:
        return await event.edit("<b>ℹ️ Botda hozircha adminlar yo'q.</b>", parse_mode='html')

    sorted_admin_ids = sorted(all_admins.keys())
    tasks = [get_user(context, event, admin_id) for admin_id in sorted_admin_ids]
    results = await asyncio.gather(*tasks)
    
    admin_list_lines = []
    for admin_id, (user_entity, _) in zip(sorted_admin_ids, results):
        level = all_admins[admin_id]
        level_name = LEVEL_NAMES.get(level, f"LVL_{level}")
        
        if user_entity:
            user_display_name = get_display_name(user_entity)
            admin_list_lines.append(f"• <a href='tg://user?id={admin_id}'>{user_display_name}</a> - [<b>{level_name}</b>]")
        else:
            admin_list_lines.append(f"• <code>{admin_id}</code> - [ID topilmadi] - [<b>{level_name}</b>]")
    
    pagination = PaginationHelper(
        context=context, 
        items=admin_list_lines, 
        title="👑 Bot Adminlari", 
        origin_event=event
    )
    await pagination.start()

