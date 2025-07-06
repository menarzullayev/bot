# bot/plugins/admin/tasks_cmds.py
"""
Userbotning fon vazifalari (tasks) va rejalashtiruvchisini (scheduler)
boshqarish uchun mo'ljallangan admin plaginlari.
"""

import html
import json
import shlex
from datetime import datetime
from typing import Any, Dict, Optional

# dateutil kutubxonasi standart emas, shuning uchun uni alohida tekshiramiz
try:
    from dateutil.parser import parse as parse_date
except ImportError:
    parse_date = None

from loguru import logger
from telethon.tl.custom import Message

from core.app_context import AppContext
from bot.decorators import userbot_cmd
from bot.lib.auth import admin_only, owner_only
from bot.lib.ui import PaginationHelper, format_error, format_success
from bot.lib.utils import RaiseArgumentParser


@userbot_cmd(command="tasks list", description="Barcha vazifalar holatini ko'rsatadi.")
@admin_only
async def tasks_list_handler(event: Message, context: AppContext):
    """
    .tasks list
    .tasks list --scheduled
    .tasks list --unscheduled
    """
    if not event.text:
        return

    args_str = event.text.split(maxsplit=2)[2] if len(event.text.split()) > 2 else ""
    parser = RaiseArgumentParser(prog=".tasks list")
    parser.add_argument('--scheduled', action='store_true', help="Faqat rejalashtirilgan vazifalarni ko'rsatish")
    parser.add_argument('--unscheduled', action='store_true', help="Faqat rejalashtirilmagan vazifalarni ko'rsatish")

    try:
        args = parser.parse_args(shlex.split(args_str))
    except ValueError as e:
        return await event.edit(format_error(f"Argument xatosi: {e}"), parse_mode='html')

    await event.edit("<code>🔄 Vazifalar ro'yxati olinmoqda...</code>", parse_mode='html')

    registered_tasks = context.tasks.list_tasks()
    running_tasks = context.tasks.get_running_tasks()
    scheduled_jobs = {job.id: job for job in context.scheduler.get_jobs()}

    lines = []
    for task in sorted(registered_tasks, key=lambda t: t.key):
        job = scheduled_jobs.get(task.key)

        if (args.scheduled and not job) or (args.unscheduled and job):
            continue

        status_icon, run_str = "⚪️", "Rejalanmagan"
        if task.key in running_tasks:
            status_icon, run_str = "⏳", "Bajarilmoqda"
        elif job:
            status_icon, run_str = ("⏸️", "Pauzada") if not job.next_run_time else ("🟢", job.next_run_time.astimezone().strftime('%H:%M:%S (%d-%b)'))

        lines.append(f"{status_icon} <b>{html.escape(task.key)}</b>")
        lines.append(f"   <i>└ {html.escape(task.description)}</i>")
        lines.append(f"   └ <b>Holati:</b> <code>{run_str}</code>")

    if not lines:
        return await event.edit("ℹ️ Ko'rsatish uchun vazifalar topilmadi.", parse_mode='html')

    pagination = PaginationHelper(context=context, items=lines, title="⚙️ Userbot Vazifalari Holati", origin_event=event, page_size=10)
    await pagination.start()


@userbot_cmd(command="jobs", description="APScheduler'dagi barcha aktiv ishlarni ko'rsatadi.")
@admin_only
async def jobs_list_handler(event: Message, context: AppContext):
    await event.edit("<code>🔄 Aktiv ishlar ro'yxati olinmoqda...</code>", parse_mode='html')
    jobs = context.scheduler.get_jobs()
    if not jobs:
        return await event.edit("ℹ️ Rejalashtirilgan ish (job) topilmadi.", parse_mode='html')

    lines = []
    for job in sorted(jobs, key=lambda j: j.id):
        next_run_str = job.next_run_time.astimezone().strftime('%Y-%m-%d %H:%M:%S') if job.next_run_time else "To'xtatilgan"
        lines.append(f"• <b>ID:</b> <code>{job.id}</code>")
        lines.append(f"  <b>Trigger:</b> <code>{job.trigger}</code>")
        lines.append(f"  <b>Keyingi:</b> <code>{next_run_str}</code>")

    pagination = PaginationHelper(context=context, items=lines, title="🕒 Rejalashtirilgan Ishlar (Jobs)", origin_event=event)
    await pagination.start()

@userbot_cmd(command="task", description="Vazifalarni rejalashtiradi, ishga tushiradi va boshqaradi.")
@owner_only
async def tasks_manager_handler(event: Message, context: AppContext):
    """
    .task list                         # Barcha vazifalar
    .task run system.cleanup_db        # Vazifani qo'lda ishga tushirish
    .task schedule ... --interval 1d   # Vazifani rejalashtirish
    .task unschedule ...               # Rejani bekor qilish
    .task pause ...                    # Vazifani pauza qilish
    .task resume ...                   # Vazifani davom ettirish
    """
    if not event.text or not event.sender_id:
        return
        
    parts = event.text.split()
    if len(parts) < 2:
        return await event.edit(format_error("Amalni kiriting (run, schedule, ...)."), parse_mode='html')

    action = parts[1].lower()
    
    # RUN amali
    if action == "run":
        if len(parts) < 3:
            return await event.edit(format_error("<b>Format:</b> <code>.task run &lt;vazifa_nomi&gt; [--kwargs '{\"a\":1}']</code>"), parse_mode='html')
        
        task_key = parts[2]
        kwargs_str = " ".join(parts[3:]) if len(parts) > 3 and parts[3].strip().startswith("--kwargs") else ""
        kwargs = {}
        if kwargs_str:
            try:
                kwargs_str = kwargs_str.replace("--kwargs", "", 1).strip()
                kwargs = json.loads(kwargs_str)
                if not isinstance(kwargs, dict): raise TypeError()
            except Exception:
                return await event.edit(format_error("`--kwargs` argumenti noto'g'ri JSON formatida."), parse_mode='html')

        await event.edit(f"<code>▶️ '{html.escape(task_key)}' ishga tushirilmoqda...</code>", parse_mode='html')
        
        acc_id = await context.db.fetch_val("SELECT id FROM accounts WHERE telegram_id = ?", (event.sender_id,))
        if not acc_id:
            return await event.edit(format_error("Sizning akkauntingiz ichki ma'lumotlar bazasida topilmadi."), parse_mode='html')

        success = await context.tasks.run_task_manually(task_key, account_id=acc_id, **kwargs)
        if not success:
            return await event.edit(format_error(f"<b>'{html.escape(task_key)}'</b> ishga tushirilmadi. Mavjudligini yoki holatini tekshiring."), parse_mode='html')
        
        return await event.edit(format_success(f"<b>'{html.escape(task_key)}'</b> navbatga qo'yildi.\nNatijani <code>.tasks logs</code> orqali tekshiring."), parse_mode='html')

    # Boshqa amallar
    if len(parts) < 3:
        return await event.edit(format_error("Noto'g'ri format. Misol: <code>.task &lt;amal&gt; &lt;vazifa_nomi&gt;</code>"), parse_mode='html')

    task_key = parts[2]
    args_str = " ".join(parts[3:])
    job_id = task_key
    acc_id = await context.db.fetch_val("SELECT id FROM accounts WHERE telegram_id = ?", (event.sender_id,))
    if not acc_id: return await event.edit(format_error("Akkaunt topilmadi."), parse_mode='html')

    if action == "unschedule":
        msg = "reja bekor qilindi" if await context.scheduler.remove_job(job_id) else "uchun reja topilmadi"
        return await event.edit(format_success(f"<code>{task_key}</code> {msg}."), parse_mode='html')
    if action == "pause":
        msg = "vaqtincha to'xtatildi" if await context.scheduler.pause_job(job_id) else "to'xtatilmadi (aktiv emas)"
        return await event.edit(format_success(f"<code>{task_key}</code> {msg}."), parse_mode='html')
    if action == "resume":
        msg = "davom ettirildi" if await context.scheduler.resume_job(job_id) else "davom ettirilmadi (aktiv emas)"
        return await event.edit(format_success(f"<code>{task_key}</code> {msg}."), parse_mode='html')
    
    if action == "schedule":
        if not parse_date:
            return await event.edit(format_error("`python-dateutil` kutubxonasi o'rnatilmagan."), parse_mode='html')

        parser = RaiseArgumentParser(prog=f".task schedule {task_key}")
        parser.add_argument('--date', help="Aniq sana/vaqt. Misol: '2025-12-31 23:59'")
        parser.add_argument('--interval', help="Vaqt oralig'i. Misol: '5m', '2h', '1d'")
        parser.add_argument('--cron', help="Cron qoida. Misol: 'hour=*/6,minute=30'")
        
        try:
            args = parser.parse_args(shlex.split(args_str or ""))
            trigger_args: Dict[str, Any] = {}
            trigger_type: Optional[str] = None

            if args.date:
                trigger_type, trigger_args['run_date'] = 'date', parse_date(args.date)
            elif args.interval:
                trigger_type, val = 'interval', int(args.interval[:-1])
                units = {'s': 'seconds', 'm': 'minutes', 'h': 'hours', 'd': 'days'}
                trigger_args[units[args.interval[-1].lower()]] = val
            elif args.cron:
                trigger_type = 'cron'
                trigger_args = {p.split('=')[0]: p.split('=')[1] for p in args.cron.split(',')}
            else:
                return await event.edit(format_error("Trigger turini ko'rsating: --date, --interval, yoki --cron"), parse_mode='html')
            
            await context.scheduler.add_job(task_key=task_key, account_id=acc_id, trigger_type=trigger_type, trigger_args=trigger_args, job_id=job_id)
            return await event.edit(format_success(f"<code>{task_key}</code> muvaffaqiyatli rejalashtirildi!"), parse_mode='html')
        except Exception as e:
            return await event.edit(format_error(f"Vazifani rejalashtirishda xatolik:\n<code>{html.escape(str(e))}</code>"), parse_mode='html')

    await event.edit(format_error(f"Noma'lum amal: `{action}`"), parse_mode='html')



@userbot_cmd(command="tasks logs", description="Vazifalar bajarilishi tarixini ko'rsatadi.")
@admin_only
async def tasks_log_handler(event: Message, context: AppContext):
    """
    .tasks logs
    .tasks logs system.cleanup_db
    .tasks logs --status FAILURE
    """
    if not event.text:
        return

    args_str = event.text.split(maxsplit=2)[2] if len(event.text.split()) > 2 else ""
    parser = RaiseArgumentParser(prog=".tasks logs")
    parser.add_argument('task_key', nargs='?', default=None, help="Filtrlash uchun vazifa nomi")
    parser.add_argument('--status', choices=['SUCCESS', 'FAILURE', 'TIMEOUT', 'SKIPPED'], help="Status bo'yicha filtrlash")

    try:
        args = parser.parse_args(shlex.split(args_str))
    except ValueError as e:
        return await event.edit(format_error(f"Argument xatosi: {e}"), parse_mode='html')

    await event.edit("<code>🔄 Vazifalar loglari olinmoqda...</code>", parse_mode='html')

    query = "SELECT id, task_key, run_at, duration_ms, status, details FROM task_logs"
    conditions, params = [], []
    if args.task_key:
        conditions.append("task_key LIKE ?")
        params.append(f"%{args.task_key}%")
    if args.status:
        conditions.append("status = ?")
        params.append(args.status.upper())

    if conditions:
        query += " WHERE " + " AND ".join(conditions)
    query += " ORDER BY run_at DESC LIMIT 100"

    logs = await context.db.fetchall(query, tuple(params))
    if not logs:
        return await event.edit("<b>📜 Hech qanday log yozuvlari topilmadi.</b>", parse_mode='html')

    lines = []
    status_icons = {"SUCCESS": "✅", "FAILURE": "❌", "TIMEOUT": "⏳", "SKIPPED": "⏩"}
    for log in logs:
        status_icon = status_icons.get(log['status'], "❓")
        run_time_dt = datetime.fromisoformat(log['run_at']).astimezone()
        run_time_str = run_time_dt.strftime('%d-%b %H:%M')
        details_text = f"- <i>{html.escape(log['details'][:50])}...</i>" if log.get('details') and log['status'] != 'SUCCESS' else ''
        lines.append(f"{status_icon} <code>{run_time_str}</code> <b>{html.escape(log['task_key'])}</b> ({log['duration_ms']:.0f}ms) {details_text}")

    pagination = PaginationHelper(context=context, items=lines, title="📜 Vazifalar Bajarilishi Jurnali", origin_event=event)
    await pagination.start()
