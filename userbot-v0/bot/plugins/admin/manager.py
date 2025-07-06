# bot/plugins/admin/manager_cmds.py
"""
Userbotning plaginlarini va buyruqlarini boshqarish uchun mo'ljallangan
markaziy plagin.
"""

import html
import os
import shlex
from datetime import datetime
from pathlib import Path

from loguru import logger
from telethon.tl.custom import Message

from core.app_context import AppContext
from bot.decorators import userbot_cmd
from bot.lib.auth import admin_only
from bot.lib.ui import PaginationHelper, format_error
from bot.lib.utils import RaiseArgumentParser

PROJECT_ROOT = Path(__file__).parent.parent.parent.parent


@userbot_cmd(command="plugins", description="Plaginlarni boshqarish va ro'yxatini ko'rsatish.")
@admin_only
async def list_plugins_cmd(event: Message, context: AppContext):
    """
    .plugins           # Yuklangan plaginlar ro'yxati
    .plugins -v         # Batafsil ma'lumot (buyruqlar bilan)
    .plugins --all      # Diskdagi barcha plaginlar daraxti
    """
    if not event.text:
        return

    args_str = event.text.split(maxsplit=1)[1] if len(event.text.split()) > 1 else ""
    parser = RaiseArgumentParser(prog=".plugins")
    parser.add_argument('-v', '--verbose', action='store_true', help="Batafsil ma'lumot ko'rsatish")
    parser.add_argument('-a', '--all', action='store_true', help="Diskdagi barcha plaginlarni ko'rsatish")

    try:
        args = parser.parse_args(shlex.split(args_str))
    except ValueError as e:
        return await event.edit(format_error(f"Argument xatosi: {e}"), parse_mode='html')

    await event.edit("<code>🔄 Ma'lumotlar tayyorlanmoqda...</code>", parse_mode='html')
    plugin_manager = context.plugin_manager
    lines: list[str] = []
    title = ""

    if args.verbose:
        title = "✅ Yuklangan plaginlar (batafsil)"
        if not plugin_manager._loaded_plugins:
            return await event.edit("ℹ️ Hech qanday plagin yuklanmagan.", parse_mode='html')

        sorted_plugins = sorted(plugin_manager._loaded_plugins.items())
        for module_path, data in sorted_plugins:
            display_name = module_path.removeprefix("bot.plugins.")
            lines.append(f"🗂️ <b>{html.escape(display_name)}</b>")
            for handler in data.get("handlers", []):
                meta = handler.get("meta", {})
                cmd_id = handler.get("command_id", "N/A")
                # TUZATISH: `get` metodi sinxron bo'lgani uchun 'await' olib tashlandi
                is_disabled = context.state.get(f"commands.disabled.{cmd_id}", False)
                status = "🔴" if is_disabled else "🟢"
                cmd_usage = meta.get("usage", "N/A")
                desc = meta.get("description", "Tavsif berilmagan")
                lines.append(f"   {status} <code>.{html.escape(cmd_usage)}</code>: <i>{html.escape(desc)}</i>")
            lines.append("")

    elif args.all:
        title = "💽 Diskdagi barcha plaginlar"
        plugins_dir = PROJECT_ROOT / "bot" / "plugins"
        loaded_modules = plugin_manager._loaded_plugins.keys()
        
        all_plugin_paths = sorted([
            p.relative_to(plugins_dir) for p in plugins_dir.rglob("*.py")
            if not p.name.startswith("_")
        ])

        for path in all_plugin_paths:
            module_path = f"bot.plugins.{str(path.with_suffix('')).replace(os.path.sep, '.')}"
            status = "✅" if module_path in loaded_modules else "➖"
            lines.append(f"{status} <code>{html.escape(str(path))}</code>")
    else:
        title = "✅ Yuklangan plaginlar"
        if not plugin_manager._loaded_plugins:
            return await event.edit("ℹ️ Hech qanday plagin yuklanmagan.", parse_mode='html')
        
        for module_path, data in sorted(plugin_manager._loaded_plugins.items()):
            display_name = module_path.removeprefix("bot.plugins.")
            handler_count = len(data.get("handlers", []))
            lines.append(f"• <code>{html.escape(display_name)}</code> ({handler_count} ta buyruq)")

    if not lines:
        return await event.edit("ℹ️ Ma'lumot topilmadi.", parse_mode='html')

    pagination = PaginationHelper(context=context, items=lines, title=title, origin_event=event)
    await pagination.start()



@userbot_cmd(command=["load", "unload", "reload"], description="Plaginni yuklaydi, o'chiradi yoki qayta yuklaydi.")
@admin_only
async def manage_plugin_cmd(event: Message, context: AppContext):
    """
    .load admin/manager_cmds
    .unload user/afk
    .reload user.notes
    """
    if not event.text:
        return

    parts = event.text.split(maxsplit=1)
    action = parts[0].strip('. ')
    plugin_name = parts[1].strip() if len(parts) > 1 else ""

    if not plugin_name:
        return await event.edit(format_error(f"Qaysi plaginni `{action}` qilish kerak?"), parse_mode='html')

    await event.edit(f"⏳ <code>{html.escape(plugin_name)}</code> plaginini `{action}` qilish boshlandi...", parse_mode='html')
    
    action_map = {
        "load": context.plugin_manager.load_plugin,
        "unload": context.plugin_manager.unload_plugin,
        "reload": context.plugin_manager.reload_plugin,
    }
    
    success, message = await action_map[action](plugin_name)
    await event.edit(message, parse_mode='html')


@userbot_cmd(command=["enable", "disable"], description="Buyruqni yoqadi yoki o'chiradi.")
@admin_only
async def toggle_command_cmd(event: Message, context: AppContext):
    """
    .enable ping
    .disable afk
    .disable admin/system:shell_handler   # To'liq ID bo'yicha
    """
    if not event.text:
        return

    parts = event.text.split(maxsplit=1)
    action = parts[0].strip('. ')
    cmd_name_or_id = parts[1].strip() if len(parts) > 1 else ""
    if not cmd_name_or_id:
        return await event.edit(format_error(f"Format: <code>.{action} &lt;buyruq_nomi_yoki_ID&gt;</code>"), parse_mode='html')

    found_handler = None
    if ":" in cmd_name_or_id:
        found_handler = context.plugin_manager.get_handler_by_id(cmd_name_or_id)
    else:
        for handler in context.plugin_manager.iter_handlers():
            if handler.get("meta", {}).get("usage") == cmd_name_or_id:
                found_handler = handler
                break
    
    if not found_handler:
        return await event.edit(format_error(f"<code>{html.escape(cmd_name_or_id)}</code> nomli buyruq topilmadi."), parse_mode='html')

    command_id = found_handler.get("command_id")
    if not command_id:
        return await event.edit(format_error("Buyruq uchun haqiqiy ID topilmadi."), parse_mode='html')
         
    success, message = await context.plugin_manager.toggle_command(command_id, enable=(action == "enable"))
    await event.edit(message, parse_mode='html')


@userbot_cmd(command="phealth", description="Plaginlardagi xatoliklar tarixini ko'rsatadi.")
@admin_only
async def plugin_health_cmd(event: Message, context: AppContext):
    title = "🩺 Plaginlar Salomatligi Hisoboti"
    error_registry = context.plugin_manager._error_registry
    
    if not error_registry:
        return await event.edit(f"<b>{title}</b>\n\n✅ Hech qanday xatolik qayd etilmagan.", parse_mode='html')

    lines = []
    for module, errors in error_registry.items():
        display_name = module.removeprefix("bot.plugins.")
        lines.append(f"❗️ <b>{html.escape(display_name)}</b> ({len(errors)} ta xatolik):")
        for error in errors[-5:]:
            error_msg = html.escape(error["error"])
            ts = datetime.fromisoformat(error['timestamp']).strftime('%d-%b %H:%M:%S')
            lines.append(f"   - 🕒 <code>{ts}</code>: <i>{error_msg[:150]}</i>")
        lines.append("")

    pagination = PaginationHelper(context=context, items=lines, title=title, origin_event=event)
    await pagination.start()

