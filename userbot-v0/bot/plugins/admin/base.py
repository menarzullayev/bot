import asyncio
import html
import platform
import time
from datetime import timedelta


try:
    import psutil
except ImportError:
    psutil = None

from loguru import logger
from telethon import __version__ as telethon_version
from telethon.tl.custom import Message

from core.app_context import AppContext
from bot.decorators import userbot_cmd


from bot.lib.auth import admin_only, owner_only, get_user_permission_level
from bot.lib.telegram import edit_message, retry_telegram_api_call
from bot.lib.ui import PaginationHelper, format_error, format_success
from bot.lib.utils import humanbytes


BOT_VERSION = "3.0.0"
BOT_AUTHOR = "@menarzullayev"
ERROR_PSUTIL_NOT_INSTALLED = "<b>⚠️ Xatolik:</b> `psutil` kutubxonasi o'rnatilmagan."


@userbot_cmd(command="ping", description="Botning javob berish tezligini tekshiradi.")
async def ping_handler(event: Message, context: AppContext):
    """.ping"""
    if not event.client:
        return

    start_time = time.monotonic()

    await edit_message(event, "<code>Pinging...</code>", parse_mode='html')

    dc_ping_start = time.monotonic()
    await retry_telegram_api_call(event.client.get_me)
    dc_ping = (time.monotonic() - dc_ping_start) * 1000

    total_ping = (time.monotonic() - start_time) * 1000

    response = f"🏓 <b>Pong!</b>\n\n" f"<b>Bot javobi:</b> <code>{total_ping:.2f} ms</code>\n" f"<b>Telegram DC:</b> <code>{dc_ping:.2f} ms</code>"

    await edit_message(event, response, parse_mode='html')


@userbot_cmd(command="status", description="Bot, tizim va servislar haqida to'liq ma'lumot.")
@admin_only
async def status_handler(event: Message, context: AppContext):
    if not psutil:
        return await edit_message(event, ERROR_PSUTIL_NOT_INSTALLED)

    await edit_message(event, "<code>🔄 Ma'lumotlar yig'ilmoqda...</code>")

    start_time_val = context.state.get('system.start_time', time.time())
    uptime_seconds = int(time.time() - start_time_val)
    uptime = str(timedelta(seconds=uptime_seconds))

    dbis_connected = context.db.is_connected()
    db_status = "✅" if dbis_connected else "❌"

    scheduler_status = "✅" if context.scheduler.scheduler.running else "❌"

    plugin_count = len(context.plugin_manager._loaded_plugins)
    handler_count = sum(len(p.get("handlers", [])) for p in context.plugin_manager._loaded_plugins.values())

    cpu = psutil.cpu_percent()
    ram = psutil.virtual_memory()

    response = (
        f"<b>🤖 Userbot Dashboard</b>\n\n"
        f"<b>Ish vaqti:</b> <code>{uptime}</code>\n"
        f"<b>Versiya:</b> <code>{BOT_VERSION}</code>\n\n"
        f"📊 <b>Komponentlar:</b>\n"
        f" • <b>Baza:</b> {db_status} | <b>Rejalashtiruvchi:</b> {scheduler_status}\n"
        f" • <b>Plaginlar:</b> <code>{plugin_count}</code> ta | <b>Buyruqlar:</b> <code>{handler_count}</code> ta\n\n"
        f"<b>🖥️ Tizim resurslari:</b>\n"
        f" • <b>CPU:</b> <code>{cpu}%</code>\n"
        f" • <b>RAM:</b> <code>{ram.percent}% ({humanbytes(ram.used)}/{humanbytes(ram.total)})</code>"
    )
    await edit_message(event, response)


@userbot_cmd(command="about", description="Userbot va tizim haqida ma'lumot.")
async def about_handler(event: Message, context: AppContext):
    uname = platform.uname()
    response = (
        f"<h3>ℹ️ Userbot Haqida</h3>"
        f"<b>Versiya:</b> <code>{BOT_VERSION}</code>\n"
        f"<b>Muallif:</b> {BOT_AUTHOR}\n"
        f"<b>Python:</b> <code>{platform.python_version()}</code>\n"
        f"<b>Telethon:</b> <code>{telethon_version}</code>\n\n"
        f"<h3>💻 Tizim Ma'lumotlari</h3>"
        f"<b>OS:</b> <code>{uname.system} {uname.release}</code>\n"
        f"<b>Arxitektura:</b> <code>{uname.machine}</code>"
    )
    await edit_message(event, response)


@userbot_cmd(command="me", description="O'zingiz haqingizda ma'lumot (ID, daraja).")
async def me_handler(event: Message, context: AppContext):
    if not event.sender_id:
        return

    level = await get_user_permission_level(context, event.sender_id)
    level_str = {100: "OWNER", 95: "CONFIG_ADMIN", 90: "SUPER_ADMIN", 50: "ADMIN"}.get(level, f"USER (LVL_{level})")

    response = f"👤 <b>Siz haqingizda ma'lumot:</b>\n\n" f"<b>ID:</b> <code>{event.sender_id}</code>\n" f"<b>Ruxsat darajasi:</b> <code>{level} ({level_str})</code>"
    await edit_message(event, response)


@userbot_cmd(command="restart", description="Userbotni xavfsiz tarzda qayta ishga tushiradi.")
@owner_only
async def restart_cmd(event: Message, context: AppContext):
    if not event.text:
        return

    reason = event.text.split(maxsplit=1)[1] if len(event.text.split()) > 1 else ""

    text_for_strikethrough = "Userbot qayta ishga tushishga tayyorlanmoqda..."
    if reason:
        text_for_strikethrough += f"\nSabab: {reason}"

    message_html = f"✅ {html.escape(text_for_strikethrough)}"

    edited_message = await edit_message(event, message_html)
    if edited_message:
        await context.state.set('system.restart_notice', {'chat_id': edited_message.chat_id, 'message_id': edited_message.id, 'original_text': text_for_strikethrough}, persistent=True)
        await context.state.set('system.lifecycle_signal', 'restart', persistent=True)


@userbot_cmd(command="shutdown", description="Userbotni xavfsiz to'xtatadi.")
@owner_only
async def shutdown_cmd(event: Message, context: AppContext):
    if not event.text:
        return

    reason = event.text.split(maxsplit=1)[1] if len(event.text.split()) > 1 else ""

    text_for_strikethrough = "Userbot o'chirilmoqda..."
    if reason:
        text_for_strikethrough += f"\nSabab: {reason}"

    message_html = f"✅ {html.escape(text_for_strikethrough)}"

    edited_message = await edit_message(event, message_html)

    if edited_message:
        await context.state.set('system.shutdown_notice', {'chat_id': edited_message.chat_id, 'message_id': edited_message.id, 'original_text': text_for_strikethrough, 'reason': reason}, persistent=True)
        await context.state.set('system.lifecycle_signal', 'shutdown', persistent=True)


@userbot_cmd(command=["next", "prev", "endp", "goto", "firstp", "lastp", "psize"], description="Sahifalangan xabarlarni boshqaradi.")
async def pagination_handler(event: Message, context: AppContext):
    """.next, .prev, .endp, .goto, .firstp, .lastp, .psize buyruqlari javob berilgan xabar uchun ishlaydi."""
    if not (event.text and event.sender_id): return
    
    parts = event.text.strip('. ').split()
    cmd = parts[0]
    arg = parts[1] if len(parts) > 1 else ""
    
    logger.debug(f"[PAGINATION_CMD] Buyruq: '{cmd}', Argument: '{arg}'")

    try:
        reply_msg = await event.get_reply_message()
        if not reply_msg:
            return await event.delete()
    except Exception as e:
        logger.error(f"[PAGINATION_CMD] Javob xabarini olishda xato: {e}")
        return await event.delete()

    pagination_session = await PaginationHelper.get_from_cache(context, reply_msg)
    await event.delete()

    if not pagination_session:
        logger.warning(f"[PAGINATION_CMD] Xabar (ID: {reply_msg.id}) uchun paginatsiya sessiyasi topilmadi.")
        return

    if event.sender_id != pagination_session.origin_sender_id:
        logger.warning(f"Ruxsatsiz urinish: {event.sender_id} sahifalashni boshqarmoqchi.")
        return

    if cmd == "endp":
        return await pagination_session.end(reply_msg)

    re_render = True
    new_page = pagination_session.current_page

    if cmd == "next":
        new_page += 1
    elif cmd == "prev":
        new_page -= 1
    elif cmd == "firstp":
        new_page = 1
    elif cmd == "lastp":
        new_page = pagination_session.total_pages
    elif cmd == "goto":
        if arg.isdigit():
            new_page = int(arg)
        else:
            re_render = False
    elif cmd == "psize":
        if arg.isdigit() and 1 <= int(arg) <= 100:
            pagination_session.page_size = int(arg)
            pagination_session.total_pages = max(1, (len(pagination_session.items) + pagination_session.page_size - 1) // pagination_session.page_size)
            new_page = 1
        else:
            re_render = False
    
    if re_render and 1 <= new_page <= pagination_session.total_pages:
        new_text = pagination_session.get_page_text(new_page)
        await edit_message(reply_msg, new_text, parse_mode='html')
        # AppState `ttl_seconds` argumentini kutadi
        await pagination_session.save_to_cache(ttl_seconds=60)
    else:
        logger.debug(f"[PAGINATION_CMD] Sahifa o'zgarmadi yoki diapazondan tashqarida: {new_page}")


@userbot_cmd(command="sudo", description="Xavfli buyruqlar uchun Sudo rejimini 5 daqiqaga yoqadi.")
@owner_only
async def sudo_handler(event: Message, context: AppContext):
    if not event.sender_id:
        return
    await context.state.set(f"sudo_mode:{event.sender_id}", True, ttl_seconds=300, persistent=False)
    await edit_message(event, "✅ <b>Sudo rejimi 5 daqiqaga faollashtirildi.</b>")


@userbot_cmd(command="sudostatus", description="Sudo rejimining holatini va qolgan vaqtini tekshiradi.")
@admin_only
async def sudo_status_handler(event: Message, context: AppContext):
    if not event.sender_id:
        return

    state_key = f"sudo_mode:{event.sender_id}"
    is_active = context.state.get(state_key, False)

    if is_active:
        remaining_seconds = context.state.get_remaining_ttl(state_key)
        if remaining_seconds is not None:

            minutes, seconds = divmod(int(remaining_seconds), 60)
            time_left_str = f"{minutes} daqiqa, {seconds} soniya"
            msg = f"✅ <b>Sudo rejimi faol.</b>\nQolgan vaqt: <code>{time_left_str}</code>"
        else:
            msg = "✅ <b>Sudo rejimi faol.</b> (Vaqt cheklovisiz)"
    else:
        msg = "❌ <b>Sudo rejimi faol emas.</b>"

    await edit_message(event, msg)
