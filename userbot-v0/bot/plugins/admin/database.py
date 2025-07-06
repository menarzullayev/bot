"""
Userbot ma'lumotlar bazasini (SQLite) boshqarish, so'rovlar yuborish,
zaxira nusxalarini olish va holatini kuzatish uchun mo'ljallangan
admin plaginlari.
"""

import asyncio
import csv
import html
import io
import json
from pathlib import Path

from loguru import logger
from telethon.tl.custom import Message

from core.app_context import AppContext
from bot.decorators import userbot_cmd
from bot.lib.auth import admin_only, owner_only
from bot.lib.utils import humanbytes

from bot.lib.ui import (
    PaginationHelper,
    format_error,
    format_success,
    request_confirmation,
    send_as_file_if_long,
    format_as_table,
)


@userbot_cmd(command="db query", description="Xavfsiz rejimda SQL so'rovini bajaradi.")
@owner_only
async def db_query_handler(event: Message, context: AppContext):
    if not event.text: return

    query = event.text.split(maxsplit=2)[2] if len(event.text.split()) > 2 else ""
    if not query:
        return await event.edit(format_error("Bajarish uchun SQL so'rovini kiriting."), parse_mode='html')

    is_dangerous = any(k in query.upper() for k in ["UPDATE", "DELETE", "DROP", "INSERT", "ALTER", "TRUNCATE"])
    if is_dangerous:
        confirmed = await request_confirmation(event, context, action_text=f"xavfli SQL so'rovini bajarish:\n<pre>{html.escape(query)}</pre>", command="db query")
        if not confirmed: return

    await event.edit("<code>🔄 So'rov bajarilmoqda...</code>", parse_mode='html')
    try:
        if query.upper().strip().startswith("SELECT"):
            rows = await context.db.fetchall(query)
            if not rows:
                return await event.edit("<b>✅ So'rov bajarildi, lekin natija qaytarmadi.</b>", parse_mode='html')
            
            headers = list(rows[0].keys())
            # Barcha qiymatlarni stringga o'tkazamiz
            table_data = [[str(item) for item in row.values()] for row in rows]
            response_text = format_as_table(headers, table_data)
            title = f"<b>🔍 So'rov Natijasi ({len(rows)} qator):</b>\n"
        else:
            rows_affected = await context.db.execute(query)
            response_text = f"<b>Ta'sir qilgan qatorlar soni:</b> <code>{rows_affected}</code>"
            title = "<b>⚙️ So'rov Bajarildi</b>\n\n"

        await send_as_file_if_long(event, title + response_text, filename="query_result.txt", parse_mode='html')
    except Exception as e:
        logger.error(f"Error executing SQL query: {e}. Query: {query}")
        await event.edit(format_error(f"SQL so'rovida xatolik:\n<code>{html.escape(str(e))}</code>"), parse_mode='html')
        
        

@userbot_cmd(command="db export", description="Jadvalni JSON yoki CSV formatida eksport qiladi.")
@admin_only
async def db_export_handler(event: Message, context: AppContext):
    if not event.text: return

    parts = event.text.split()
    if len(parts) < 3:
        return await event.edit(format_error("<b>Format:</b> <code>.db export &lt;jadval_nomi&gt; [--format csv/json]</code>"), parse_mode='html')

    table_name = parts[2]
    file_format = "json"
    if "--format" in parts and len(parts) > parts.index("--format") + 1:
        file_format = parts[parts.index("--format") + 1].lower()

    if file_format not in ["json", "csv"]:
        return await event.edit(format_error("Noto'g'ri eksport formati. 'json' yoki 'csv' ni tanlang."), parse_mode='html')

    await event.edit(f"<code>🔄 '{html.escape(table_name)}' jadvalidan ma'lumotlar eksport qilinmoqda...</code>", parse_mode='html')
    try:
        if not table_name.isidentifier():
            return await event.edit(format_error("Noto'g'ri jadval nomi."), parse_mode='html')

        rows = await context.db.fetchall(f'SELECT * FROM "{table_name}"')
        if not rows:
            return await event.edit(format_error(f"'{html.escape(table_name)}' jadvali bo'sh yoki mavjud emas."), parse_mode='html')

        data_to_export = [dict(row) for row in rows]
        buffer = io.StringIO()

        if file_format == "json":
            json.dump(data_to_export, buffer, indent=2, ensure_ascii=False)
        elif file_format == "csv":
            writer = csv.DictWriter(buffer, fieldnames=data_to_export[0].keys())
            writer.writeheader()
            writer.writerows(data_to_export)

        buffer.seek(0)
        file_stream = io.BytesIO(buffer.read().encode('utf-8'))
        file_stream.name = f"{table_name}_export.{file_format}"

        if not event.client: return

        await event.client.send_file(
            event.chat_id, file_stream,
            caption=f"📄 <b>{html.escape(table_name)}</b> jadvali. Format: {file_format.upper()}",
            reply_to=event.id, parse_mode='html' # <-- QO'SHILDI
        )
        await event.delete()
    except Exception as e:
        logger.error(f"DB Export error: {e}. Table: {table_name}, Format: {file_format}")
        await event.edit(format_error(f"Eksport qilishda xatolik:\n<code>{html.escape(str(e))}</code>"), parse_mode='html')
        
        
@userbot_cmd(command="db stats", description="Ma'lumotlar bazasi haqida statistika.")
@admin_only
async def db_stats_handler(event: Message, context: AppContext):
    await event.edit("<code>🔄 Ma'lumotlar bazasi statistikasi hisoblanmoqda...</code>")

    stats = await context.db.db_stats()
    if "error" in stats:
        return await event.edit(format_error(stats['error']))

    response_lines = [
        "<b>🗂️ Ma'lumotlar Bazasi Statistikasi</b>",
        f"<b>Hajmi:</b> <code>{humanbytes(stats['file_size_bytes'])}</code>",
        f"<b>Jadvallar soni:</b> <code>{stats['table_count']}</code>\n",
        "<b>⚙️ PRAGMA sozlamalari:</b>",
        *[f" • {k}: <code>{v}</code>" for k, v in stats['pragmas'].items()],
        "",
    ]

    table_lines = [f"<b>Jadvallar ({len(stats['tables'])}):</b>"]
    for table in stats['tables']:
        table_lines.append(f"• <code>{table['name']}</code> - {table['row_count']} ta yozuv")
        if table['indexes']:
            table_lines.append(f"  └ Indekslar: {', '.join(f'<code>{idx}</code>' for idx in table['indexes'])}")

    # TUZATILGAN QATOR:
    pagination = PaginationHelper(
        context=context, 
        items=table_lines, 
        title="\n".join(response_lines), 
        page_size=15, 
        origin_event=event
    )
    await pagination.start()


@userbot_cmd(command="db backup", description="Ma'lumotlar bazasining zaxira nusxasini yaratadi.")
@owner_only
async def db_backup_handler(event: Message, context: AppContext):
    await event.edit("<code>💽 Zaxira nusxa yaratilmoqda...</code>", parse_mode='html')
    try:
        backup_path = await context.db.create_backup()
        if not backup_path:
            return await event.edit(format_error("Zaxira nusxa yaratib bo'lmadi."), parse_mode='html')

        if not event.client: return

        await event.client.send_file(
            event.chat_id, str(backup_path),
            caption=f"✅ Baza zaxira nusxasi: <code>{html.escape(backup_path.name)}</code>",
            reply_to=event.id, parse_mode='html' # <-- QO'SHILDI
        )
        await event.delete()
    except Exception as e:
        logger.error(f"DB Backup error: {e}")
        await event.edit(format_error(f"Zaxira nusxa yaratishda xatolik:\n<code>{html.escape(str(e))}</code>"), parse_mode='html')

@userbot_cmd(command="db schema", description="Jadvalning tuzilish sxemasini ko'rsatadi.")
@admin_only
async def db_schema_handler(event: Message, context: AppContext):
    if not event.text: return

    table_name = event.text.split(maxsplit=2)[2] if len(event.text.split()) > 2 else ""
    if not table_name:
        return await event.edit(format_error("Jadval nomi berilmagan."), parse_mode='html')
    if not table_name.isidentifier():
        return await event.edit(format_error("Noto'g'ri jadval nomi."), parse_mode='html')

    await event.edit(f"<code>🔄 '{html.escape(table_name)}' sxemasi olinmoqda...</code>", parse_mode='html')
    schema_info = await context.db.fetchone("SELECT sql FROM sqlite_master WHERE type='table' AND name=?", (table_name,))

    if not schema_info or not schema_info.get('sql'):
        return await event.edit(f"<b>❌ '{html.escape(table_name)}' nomli jadval topilmadi.</b>", parse_mode='html')

    response = f"<b>📄 '{html.escape(table_name)}' sxemasi:</b>\n\n<pre><code class=\"language-sql\">{html.escape(schema_info['sql'])}</code></pre>"
    await send_as_file_if_long(event, response, filename=f"{table_name}_schema.txt", parse_mode='html')
    

@userbot_cmd(command="db vacuum", description="Ma'lumotlar bazasini tozalaydi (VACUUM).")
@owner_only
async def db_vacuum_handler(event: Message, context: AppContext):
    await event.edit("<b>⏳ Ma'lumotlar bazasini tozalash (VACUUM) boshlandi...</b>", parse_mode='html')
    try:
        await context.db.vacuum()
        await event.edit("<b>✅ Ma'lumotlar bazasi muvaffaqiyatli tozalandi.</b>", parse_mode='html')
    except Exception as e:
        logger.error(f"DB Vacuum error: {e}")
        await event.edit(format_error(f"VACUUM operatsiyasida xatolik:\n<code>{html.escape(str(e))}</code>"), parse_mode='html')


@userbot_cmd(command="db migrations", description="Ma'lumotlar bazasi migratsiyalari holatini ko'rsatadi.")
@admin_only
async def db_migrations_status_handler(event: Message, context: AppContext):
    await event.edit("<code>🔄 Migratsiyalar holati tekshirilmoqda...</code>")
    try:

        project_root = Path(__file__).parent.parent.parent.parent
        migrations_path = project_root / "data" / "migrations"

        if not migrations_path.is_dir():
            return await event.edit(f"<b>❌ Migratsiyalar papkasi topilmadi:</b> <code>{migrations_path}</code>")

        applied_files = {row['filename'] for row in await context.db.fetchall("SELECT filename FROM applied_migrations")}
        disk_files = sorted([f.name for f in migrations_path.glob("*.sql")])

        if not disk_files:
            return await event.edit("<b>ℹ️ Migratsiya fayllari topilmadi.</b>")

        response = "<b>✳️ DB Migratsiyalari Holati:</b>\n\n"
        response += "\n".join([(f"<b>[ ✅ Bajarilgan ]</b> - <code>{f}</code>" if f in applied_files else f"<b>[ ⏳ Bajarilmagan ]</b> - <code>{f}</code>") for f in disk_files])
        await send_as_file_if_long(event, response, filename="migration_status.txt")
    except Exception as e:
        logger.error(f"DB Status error: {e}", exc_info=True)
        await event.edit(format_error(f"Migratsiya holatini olishda xatolik:\n<code>{html.escape(str(e))}</code>"))
