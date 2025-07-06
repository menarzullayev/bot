# bot/plugins/admin/login_code.py
"""
Telegramning servis akkauntidan (777000) kelgan yangi sessiya uchun
kirish kodlarini avtomatik ushlaydigan va kerakli joylarga yuboradigan plagin.
"""

import html
import re

from loguru import logger
from telethon import events

from core.app_context import AppContext
from bot.decorators import userbot_cmd
from bot.lib.telegram import get_me, get_display_name

# --- Konstanta va Regex ---
TELEGRAM_SERVICE_ID = 777000
CODE_REGEX = re.compile(
    r"(?i)\b(?:login code|kirish kodi|kod|code|код|коду)[\s:]*(\d{4,7})\b"
)

# ===== HODISA ISHLOVCHISI =====

@userbot_cmd(
    listen=events.NewMessage(from_users=TELEGRAM_SERVICE_ID, incoming=True),
    description="Telegramdan kelgan login kodini ushlaydi."
)
async def login_code_handler(event: events.NewMessage.Event, context: AppContext):
    """
    Telegramning servis akkauntidan kelgan xabarlarni tekshiradi,
    login kodini topadi, terminalga chiqaradi, "Saqlangan xabarlar"ga
    va log kanaliga yuboradi.
    """
    message_text = event.raw_text
    client = event.client
    if not (message_text and client):
        return

    match = CODE_REGEX.search(message_text)
    if not match:
        return

    code = match.group(1)
    # Kiritilgan o'zgarish: kodni nuqtalar bilan ajratamiz
    formatted_code = ".".join(code)
    
    logger.info(f"Telegram servisidan xabar keldi. Matn: \"{message_text.replace('\n', ' ')}\"")
    
    # 1. Terminalga kodni chiqarish
    print("\n" + "="*50)
    logger.critical(f"!!! TELEGRAMGA KIRISH KODI: {formatted_code} !!!")
    print("="*50 + "\n")

    # 2. Kodni "Saqlangan xabarlar"ga yuborish
    try:
        logger.info("Kod 'Saqlangan xabarlar'ga yuborilmoqda...")
        await client.send_message('me', f"<b>Kirish kodi:</b> <code>{formatted_code}</code>", parse_mode='html')
        logger.success("Kod 'Saqlangan xabarlar'ga muvaffaqiyatli yuborildi.")
    except Exception as e:
        logger.exception(f"Login kodini 'Saqlangan xabarlar'ga yuborishda xatolik: {e}")

    # 3. Kodni log kanaliga yuborish
    log_channel_id_str = context.config.get("TEXT_LOG_CHANNEL")
    if not (log_channel_id_str and str(log_channel_id_str).lstrip('-').isdigit()):
        logger.trace("TEXT_LOG_CHANNEL sozlanmagan, log kanaliga yuborish o'tkazib yuborildi.")
        return

    try:
        log_channel_id = int(log_channel_id_str)
        me = await get_me(context, client)
        user_info = f"<a href='tg://user?id={me.id}'>{get_display_name(me)}</a>" if me else "Noma'lum akkaunt"
        
        log_message = (
            "🚨 <b>Login Kodi Qabul Qilindi</b>\n\n"
            f"👤 <b>Akkaunt:</b> {user_info}\n"
            f"🔐 <b>Kod:</b> <code>{formatted_code}</code>\n\n"
            "ℹ️ <i>Ushbu kod yangi qurilmadan tizimga kirish uchun ishlatilmoqda.</i>"
        )

        logger.info(f"Login kodi log kanaliga ({log_channel_id}) yuborilmoqda...")
        await client.send_message(log_channel_id, log_message, parse_mode='html')
        logger.success(f"Login kodi log kanaliga ({log_channel_id}) muvaffaqiyatli yuborildi.")
    except Exception as e:
        logger.exception(f"Login kodini log kanaliga yuborishda xatolik: {e}")
