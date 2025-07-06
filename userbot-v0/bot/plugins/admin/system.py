# bot/plugins/admin/system.py
"""
Userbot ishlayotgan server tizimini boshqarish va holatini
kuzatish uchun mo'ljallangan admin plaginlari (to'liq modernizatsiya qilingan).
"""

import asyncio
import html
import os
import shlex
import sys
import time
from pathlib import Path
from typing import Optional

try:
    import psutil
except ImportError:
    psutil = None

from loguru import logger
from telethon.tl.custom import Message

from core.app_context import AppContext
from bot.decorators import userbot_cmd
from bot.lib.auth import admin_only, owner_only
from bot.lib.decorators import rate_limit
from bot.lib.system import run_shell_command
from bot.lib.ui import (
    PaginationHelper,
    send_as_file_if_long,
    request_confirmation,
    format_error,
)
from bot.lib.utils import humanbytes

ERROR_PSUTIL_NOT_INSTALLED = "<b>⚠️ Xatolik:</b> `psutil` kutubxonasi o'rnatilmagan."

# ===== TIZIM BUYRUQLARI =====


@userbot_cmd(command="sh", description="Serverda xavfsiz shell buyrug'ini ishga tushiradi.")
@admin_only
async def shell_handler(event: Message, context: AppContext):
    """
    Linux: .sh ls -l /
    Windows: .sh dir C:\\
    """
    if not event.text:
        return

    command = event.text.split(maxsplit=1)[1] if len(event.text.split()) > 1 else ""
    if not command:
        return await event.edit("<b>Qaysi shell buyrug'ini ishga tushirish kerak?</b>", parse_mode='html')

    await event.edit(f"<code>🔄 Bajarilmoqda: {html.escape(command)}</code>", parse_mode='html')
    stdout, stderr, returncode, duration = await run_shell_command(command)

    result_text = ""
    if stdout:
        result_text += f"<b>📤 STDOUT:</b>\n<pre>{html.escape(stdout)}</pre>\n"
    if stderr:
        result_text += f"<b>📥 STDERR:</b>\n<pre>{html.escape(stderr)}</pre>\n"

    result_text += f"<b>✅ Yakunlandi (kod: {returncode})</b> " f"<code>{duration:.2f}</code> soniyada."

    await send_as_file_if_long(event, result_text, filename="shell_output.txt", parse_mode='html')


@userbot_cmd(command="ping", description="Userbot pingini yoki tashqi hostga pingni tekshiradi.")
@admin_only
async def ping_handler(event: Message, context: AppContext):
    """
    .ping            # Userbotning javob berish tezligini tekshirish
    .ping google.com # Tashqi hostga ping yuborish
    """
    if not event.text:
        return

    host = event.text.split(maxsplit=1)[1] if len(event.text.split()) > 1 else ""

    if not host:
        start = time.monotonic()
        await event.edit("`Pinging...`", parse_mode='markdown')
        return await event.edit(f"🏓 **Pong!**\n`{(time.monotonic() - start) * 1000:.2f} ms`", parse_mode='html')

    await event.edit(f"<code>Pinging {html.escape(host)}...</code>", parse_mode='html')

    command = f"ping -n 4 {shlex.quote(host)}" if sys.platform == "win32" else f"ping -c 4 {shlex.quote(host)}"

    try:
        stdout, stderr, _, _ = await run_shell_command(command)
        output = (stdout or stderr).strip()
        response = f"<b>PING natijalari:</b> <code>{html.escape(host)}</code>\n\n" f"<pre>{html.escape(output)}</pre>"
        await event.edit(response, parse_mode='html')
    except Exception as e:
        await event.edit(format_error(f"Ping yuborishda xato: {e}"), parse_mode='html')


@userbot_cmd(command="logs", description="Botning jurnal (log) faylini ko'rsatadi.")
@admin_only
async def logs_handler(event: Message, context: AppContext):
    """
    .logs         # Oxirgi 25 qatorni ko'rsatish
    .logs 100     # Oxirgi 100 qatorni ko'rsatish
    .logs full    # Log faylini to'liq yuborish
    """
    if not event.text:
        return

    args = event.text.split(maxsplit=1)[1] if len(event.text.split()) > 1 else ""
    log_file_path_str = context.config.get("LOG_FILE_PATH")
    if not log_file_path_str:
        return await event.edit("<b>❌ Log yo'li konfiguratsiyada ko'rsatilmagan.</b>", parse_mode='html')

    log_path = Path(log_file_path_str)
    if not log_path.is_file():
        return await event.edit(f"<b>❌ Log fayli topilmadi:</b> <code>{log_path}</code>", parse_mode='html')

    if args.lower() == "full":
        if not event.client:
            return
        await event.edit("<code>Fayl yuborilmoqda...</code>", parse_mode='html')
        await event.client.send_file(event.chat_id, log_path, caption="<b>Userbot log fayli.</b>", reply_to=event.id, parse_mode='html')
        return await event.delete()

    num_lines = int(args) if args.isdigit() and int(args) > 0 else 25
    await event.edit(f"<code>🔄 Logning oxirgi {num_lines} qatori o'qilmoqda...</code>", parse_mode='html')

    try:
        with open(log_path, 'r', encoding='utf-8', errors='ignore') as f:
            # Faylning oxirgi N qatorini samarali o'qish
            lines = f.readlines()
            last_lines = lines[-num_lines:]
            content = "".join(last_lines)

        response_text = f"<b>📜 Log ({len(last_lines)} qator):</b>\n\n<pre>{html.escape(content or 'Log boʻsh.')}</pre>"
        await send_as_file_if_long(event, response_text, parse_mode='html')
    except Exception as e:
        await event.edit(format_error(f"Log faylni o'qishda xato: {e}"), parse_mode='html')


@userbot_cmd(command="top", description="CPU va RAMni eng ko'p ishlatayotgan jarayonlarni ko'rsatadi.")
@rate_limit(seconds=60)
@admin_only
async def top_processes_handler(event: Message, context: AppContext):
    if not psutil:
        return await event.edit(ERROR_PSUTIL_NOT_INSTALLED, parse_mode='html')

    await event.edit("<code>🔄 Jarayonlar tahlil qilinmoqda...</code>", parse_mode='html')

    def get_processes_info():
        if not psutil:
            return []
        procs = []
        for p in psutil.process_iter(['pid', 'name', 'username', 'cpu_percent', 'memory_info']):
            try:
                p.info['memory_percent'] = (p.info['memory_info'].rss / psutil.virtual_memory().total) * 100
                procs.append(p.info)
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                continue
        return procs

    processes = await asyncio.to_thread(get_processes_info)
    if not processes:
        return await event.edit(format_error("Jarayonlar haqida ma'lumot olib bo'lmadi."), parse_mode='html')

    top_cpu = sorted(processes, key=lambda p: p['cpu_percent'], reverse=True)[:5]
    top_mem = sorted(processes, key=lambda p: p['memory_percent'], reverse=True)[:5]
    cpu_text = "\n".join([f"   • <code>{p['cpu_percent']:.1f}% - {html.escape(p['name'])} ({p['pid']})</code>" for p in top_cpu])
    mem_text = "\n".join([f"   • <code>{humanbytes(p['memory_info'].rss)} - {html.escape(p['name'])} ({p['pid']})</code>" for p in top_mem])
    response = f"<b>📊 Tizim Resurslari</b>\n\n<b>🧠 CPU (Top 5):</b>\n{cpu_text}\n\n<b>💾 Xotira (Top 5):</b>\n{mem_text}"
    await event.edit(response, parse_mode='html')


@userbot_cmd(command="kill", description="Jarayonni PID orqali to'xtatadi.")
@admin_only
async def kill_process_handler(event: Message, context: AppContext):
    if not psutil:
        return await event.edit(ERROR_PSUTIL_NOT_INSTALLED, parse_mode='html')

    if not event.text:
        return
    pid_str = event.text.split(maxsplit=1)[1] if len(event.text.split()) > 1 else ""
    if not pid_str.isdigit():
        return await event.edit("<b>❌ Noto'g'ri format.</b> PID raqam bo'lishi kerak.", parse_mode='html')
    pid = int(pid_str)

    try:
        process = psutil.Process(pid)
        proc_name = process.name()
        confirmed = await request_confirmation(event, context, action_text=f"'{proc_name}' (PID: {pid}) jarayonini to'xtatish", command="kill")
        if not confirmed:
            return

        await asyncio.to_thread(process.kill)
        await event.edit(f"✅ <b>Jarayon (PID: {pid}, Nomi: {html.escape(proc_name)}) to'xtatildi.</b>", parse_mode='html')
    except psutil.NoSuchProcess:
        await event.edit(f"<b>❌ Jarayon topilmadi (PID: {pid}).</b>", parse_mode='html')
    except psutil.AccessDenied:
        await event.edit(f"<b>❌ Bu jarayonni to'xtatishga ruxsat yo'q (PID: {pid}).</b>", parse_mode='html')
    except Exception as e:
        await event.edit(format_error(f"Noma'lum xatolik: {e}"), parse_mode='html')


@userbot_cmd(command="env", description="Serverning muhit o'zgaruvchilarini ko'rsatadi.")
@admin_only
async def env_handler(event: Message, context: AppContext):
    await event.edit("<code>🔄 Muhit o'zgaruvchilari o'qilmoqda...</code>", parse_mode='html')
    sensitive_keys = ['TOKEN', 'API', 'HASH', 'KEY', 'SECRET', 'PASS', 'PHONE', 'SUDO', 'STRING']

    def get_env_vars():
        return "\n".join(sorted([(f"{html.escape(key)} = " f"{'••••••••' if any(s in key.upper() for s in sensitive_keys) else html.escape(value)}") for key, value in os.environ.items()]))

    env_vars = await asyncio.to_thread(get_env_vars)
    response = f"<b>🌿 Muhit O'zgaruvchilari:</b>\n\n<pre>{env_vars}</pre>"
    await send_as_file_if_long(event, response, parse_mode='html')


@userbot_cmd(command="df", description="Diskdagi bo'sh joy haqida ma'lumot.")
@admin_only
async def df_handler(event: Message, context: AppContext):
    if not psutil:
        return await event.edit(ERROR_PSUTIL_NOT_INSTALLED, parse_mode='html')

    await event.edit("<code>🔄 Disk ma'lumotlari yig'ilmoqda...</code>", parse_mode='html')

    def get_disk_usage():
        if not psutil:
            return "N/A"
        response_lines = ["💾 <b>Diskdagi Joy</b>\n"]
        response_lines.append("<code>{:<8} {:>10} {:>10} {:>10} {:>5}</code>".format("Bo'lim", "Hajmi", "Ishlatilgan", "Bo'sh", "Foiz"))
        for part in psutil.disk_partitions(all=False):
            try:
                usage = psutil.disk_usage(part.mountpoint)
                response_lines.append("<code>{:<8} {:>10} {:>10} {:>10} {:>4}%</code>".format(part.device.split('\\')[0] or part.device, humanbytes(usage.total), humanbytes(usage.used), humanbytes(usage.free), int(usage.percent)))
            except (OSError, psutil.Error) as e:
                logger.warning(f"'{part.mountpoint}' bo'limini o'qib bo'lmadi: {e}")
                continue
        return "\n".join(response_lines)

    disk_info = await asyncio.to_thread(get_disk_usage)
    await event.edit(disk_info, parse_mode='html')
