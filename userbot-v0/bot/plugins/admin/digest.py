# bot/plugins/admin/digest.py
"""
Foydalanuvchi faoliyati haqida kunlik hisobotlarni (dayjestlarni)
rejalashtirish va boshqarish uchun mo'ljallangan to'liq funksional plagin.
Endi haqiqiy statistika ma'lumotlar bazasidan olinadi.
"""

import html
import re
import time
from datetime import datetime, timedelta
from typing import Optional

from loguru import logger
from telethon import TelegramClient
from telethon.tl.custom import Message
from telethon.tl.types import Channel, User

from core.app_context import AppContext
from bot.decorators import userbot_cmd
from bot.lib.auth import admin_only
from bot.lib.telegram import get_account_id, get_me, get_display_name, resolve_entity
from bot.lib.ui import format_error, format_success

# --- Rejalashtirilgan Vazifa ---

async def generate_digest_report(context: AppContext, client: TelegramClient, **kwargs):
    """
    Bu fon vazifasi. U rejalashtiruvchi (`scheduler`) tomonidan avtomatik
    chaqiriladi va kunlik hisobotni generatsiya qilib, yuboradi.
    Endi 'account_id' ni kwargs'dan oladi.
    """
    account_id = kwargs.get("account_id")
    if not account_id:
        logger.critical(f"generate_digest_report vazifasi 'account_id'siz chaqirildi! kwargs: {kwargs}")
        return
        
    logger.info(f"Kunlik hisobot vazifasi ishga tushdi. AccID: {account_id}")

    me = await get_me(context, client)
    if not me:
        return logger.error(f"Digest hisoboti uchun 'me' olinmadi. AccID: {account_id}")

    display_name = get_display_name(me)
    
    three_days_ago_dt = datetime.now() - timedelta(days=1)
    
    try:
        total_media_res = await context.db.fetchone(
            "SELECT COUNT(id) as c FROM logged_media WHERE account_id=? AND timestamp >= ?",
            (account_id, three_days_ago_dt)
        )
        total_media_count = total_media_res['c'] if total_media_res else 0

        most_active_chat_res = await context.db.fetchone(
            "SELECT source_chat_id, COUNT(id) as media_count FROM logged_media "
            "WHERE account_id=? AND timestamp >= ? "
            "GROUP BY source_chat_id ORDER BY media_count DESC LIMIT 1",
            (account_id, three_days_ago_dt)
        )
        
        most_active_chat = "<i>(aniqlanmadi)</i>"
        if most_active_chat_res and most_active_chat_res['source_chat_id']:
            try:
                entity = await resolve_entity(context, client, int(most_active_chat_res['source_chat_id']))
                most_active_chat = get_display_name(entity) if entity else "Noma'lum chat"
            except Exception as e:
                logger.warning(f"Eng faol chat nomini olib bo'lmadi: {e}")
                most_active_chat = f"ID: {most_active_chat_res['source_chat_id']}"

    except Exception as e:
        logger.exception(f"Hisobot uchun statistikani DB'dan olishda xato: {e}")
        total_media_count, most_active_chat = ("Xato", "Xato")

    report_text = (
        f"📊 <b>Kunlik Hisobot</b>\n\n"
        f"Assalomu alaykum, {html.escape(display_name)}! O'tgan 24 soatdagi media-logger faoliyati:\n\n"
        f"🗄️ <b>Jami saqlangan medialar:</b> <code>{total_media_count}</code> ta\n"
        f"🏆 <b>Eng faol chat:</b> <i>{html.escape(most_active_chat)}</i>\n\n"
        f"<i>Hisobot {datetime.now().strftime('%Y-%m-%d %H:%M')} holatiga ko'ra tayyorlandi.</i>"
    )

    try:
        settings = await context.db.fetchone(
            "SELECT confirmation_message_id, chat_id FROM digest_settings WHERE account_id=?",
            (account_id,)
        )
        chat_id = int(settings['chat_id']) if settings and settings.get('chat_id') else me.id
        reply_to_id = settings['confirmation_message_id'] if settings else None

        if reply_to_id:
            await client.send_message(chat_id, report_text, reply_to=reply_to_id, parse_mode='html')
        else:
            await client.send_message(chat_id, report_text, parse_mode='html')
            
        logger.info(f"Hisobot {chat_id} chatiga yuborildi.")
    except Exception as e:
        logger.exception(f"Hisobotni yuborishda xato: {e}")
        try:
            await client.send_message(me.id, f"<b>Hisobotni belgilangan chatga yuborib bo'lmadi.</b>\n\n{report_text}", parse_mode='html')
        except Exception as final_e:
            logger.error(f"Hisobotni lichkaga ham yuborib bo'lmadi: {final_e}")
               
            
# --- Asosiy Boshqaruv Buyrug'i ---

@userbot_cmd(command="digest", description="Kunlik faoliyat hisobotini boshqaradi.")
@admin_only
async def digest_manager_handler(event: Message, context: AppContext):
    """
    .digest on [HH:MM]  # Har kuni belgilangan vaqtda hisobotni yoqish (standart: 08:00)
    .digest off         # Hisobotni o'chirish
    .digest now         # Hisobotni hoziroq yuborish
    .digest status      # Joriy holatni ko'rish
    """
    if not event.text or not event.client:
        return
    
    args = event.text.split()
    action = args[1].lower() if len(args) > 1 else "status"
    time_str = args[2] if len(args) > 2 and action == "on" else "08:00"
    
    account_id = await get_account_id(context, event.client)
    if not account_id:
        return await event.edit(format_error("Akkauntni aniqlab bo'lmadi."), parse_mode='html')

    job_id = f"digest_report_{account_id}"

    if action == "on":
        if not re.match(r"^\d{1,2}:\d{2}$", time_str):
            return await event.edit(format_error("Vaqt formati noto'g'ri. Namuna: <code>08:30</code>"), parse_mode='html')
        
        try:
            hour, minute = map(int, time_str.split(':'))
            if not (0 <= hour <= 23 and 0 <= minute <= 59):
                raise ValueError("Vaqt diapazoni noto'g'ri")
        except ValueError:
             return await event.edit(format_error("Vaqt qiymati noto'g'ri. Soat 0-23, daqiqa 0-59 oralig'ida bo'lishi kerak."), parse_mode='html')

        await context.scheduler.add_job(
            task_key="digest.daily_report",
            account_id=account_id,
            trigger_type='cron',
            trigger_args={'hour': hour, 'minute': minute},
            job_id=job_id
        )
        
        await context.db.execute(
            "REPLACE INTO digest_settings (account_id, delivery_time, is_enabled, confirmation_message_id, chat_id) "
            "VALUES (?, ?, 1, ?, ?)",
            (account_id, time_str, event.id, event.chat_id)
        )
        logger.info(f"Kunlik hisobot yoqildi. AccID: {account_id}, Vaqt: {time_str}")
        await event.edit(format_success(f"Kunlik hisobot yoqildi.\nHar kuni soat <b>{time_str}</b> da shu xabarga javob beriladi."), parse_mode='html')
    
    elif action == "off":
        await context.scheduler.remove_job(job_id)
        await context.db.execute("UPDATE digest_settings SET is_enabled = 0 WHERE account_id = ?", (account_id,))
        logger.info(f"Kunlik hisobot o'chirildi. AccID: {account_id}")
        await event.edit(format_success("Kunlik hisobot o'chirildi."), parse_mode='html')
        
    elif action == "now":
        await event.edit("⏳ Hisobot hozir tayyorlanib, yuboriladi...", parse_mode='html')
        await generate_digest_report(context, event.client, account_id=account_id)
        await event.delete()
        
    elif action == "status":
        settings = await context.db.fetchone("SELECT delivery_time, is_enabled FROM digest_settings WHERE account_id=?", (account_id,))
        job = context.scheduler.get_job(job_id)

        if settings and settings['is_enabled'] and job:
            next_run = job.next_run_time.strftime('%Y-%m-%d %H:%M:%S %Z') if job.next_run_time else "Noma'lum"
            response = (
                f"ℹ️ <b>Kunlik hisobot holati</b>\n\n"
                f"<b>Holat:</b> <span style='color:green;'>Yoqilgan</span>\n"
                f"<b>Yuborilish vaqti:</b> <code>{settings['delivery_time']}</code>\n"
                f"<b>Keyingi yuborish:</b> <code>{next_run}</code>"
            )
        else:
            response = "ℹ️ <b>Kunlik hisobot holati:</b> <span style='color:red;'>O'chirilgan</span>"
        
        await event.edit(response, parse_mode='html')
    else:
        await event.edit(format_error(f"Noma'lum buyruq: <code>{html.escape(action)}</code>"), parse_mode='html')



def register_plugin_tasks(context: AppContext):
    """Bu plaginga tegishli fon vazifalarini ro'yxatdan o'tkazadi."""
    context.tasks.register(
        key="digest.daily_report",
        description="Har kungi faoliyat dayjestini yaratadi.",
        retries=2
    )(generate_digest_report)