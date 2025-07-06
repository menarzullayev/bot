# userbot-v0/bot/plugins/user/help.py
"""
Userbotning barcha buyruqlari haqida ma'lumot beruvchi interaktiv yordam menyusi.
(To'liq modernizatsiya qilingan).
"""

import asyncio
import html
import re
from typing import Any, Dict

from loguru import logger
from telethon import events
from telethon.tl.custom import Message

from core.app_context import AppContext
from bot.decorators import userbot_cmd
from bot.lib.ui import code, bold

# --- Menyu Generatsiya Qiluvchi Funksiyalar ---

def _generate_main_menu(context: AppContext) -> str:
    """Barcha mavjud kategoriyalardan asosiy menyuni dinamik yaratadi."""
    bot_name = context.config.get('BOT_NAME', 'Userbot')
    menu = f"<b>🤖 {html.escape(bot_name)} Yordam Menyusi</b>\n\n"
    menu += "Quyidagi bo'limlardan birini tanlash uchun uning raqamini javob (reply) qilib yuboring:\n\n"
    
    categories = context.plugin_manager.get_all_categories()
    for i, category_name in enumerate(categories, 1):
        menu += f"<code>{i}.</code> {category_name.capitalize()}\n"
        
    menu += "\n<i>Menyudan chiqish uchun xabarni o'chiring yoki 2 daqiqa kuting.</i>"
    return menu

def _generate_category_menu(context: AppContext, category_name: str) -> str:
    """Tanlangan kategoriya bo'yicha buyruqlar menyusini dinamik yaratadi."""
    commands = context.plugin_manager.get_commands_by_category(category_name)
    
    menu = f"<b>{category_name.capitalize()}</b>\n\n"
    menu += "Aniq buyruq haqida ma'lumot olish uchun uning nomini javob qilib yozing (nuqtasiz):\n\n"
    
    sorted_commands = sorted(commands, key=lambda cmd: cmd['commands'][0])
    
    for command_data in sorted_commands:
        main_command = command_data['commands'][0]
        menu += f"• <code>{main_command}</code>\n"
        
    menu += "\n<i>Asosiy menyuga qaytish uchun <code>0</code> yoki <code>back</code> deb javob bering.</i>"
    return menu

def _generate_command_details(command_data: Dict[str, Any], prefix: str) -> str:
    """Buyruq haqida batafsil ma'lumotni formatlaydi."""
    cmd_str = ' | '.join([f"{prefix}{c}" for c in command_data['commands']])
    
    response_text = f"<b>ℹ️ Buyruq:</b> {code(cmd_str)}\n\n"
    if description := command_data.get('description'):
        # Foydalanish qo'llanmasini tavsifdan ajratib olamiz
        usage_match = re.search(r"Foydalanish: (.+)", description)
        usage_example = usage_match.group(1) if usage_match else None
        
        # Asosiy tavsif
        main_description = re.sub(r"\s*Foydalanish:.*", "", description).strip()
        response_text += f"<b>Tavsif:</b> {main_description}"
        
        if usage_example:
            response_text += f"\n\n<b>Namuna:</b> <code>{prefix}{html.escape(usage_example)}</code>"
            
    response_text += "\n\n<i>Bo'lim menyusiga qaytish uchun <code>0</code> yoki <code>back</code> deb javob bering.</i>"
    return response_text

# --- BUYRUQ VA NAVIGATSIYA HANDLERLARI ---

@userbot_cmd(command="help", description="Userbot yordam menyusini ko'rsatadi.")
async def start_help_cmd(event: Message, context: AppContext):
    """`.help` buyrug'i uchun asosiy boshlovchi, interaktiv menyuni ishga tushiradi."""
    if not event.chat_id or not event.client: return
    
    chat_id = event.chat_id
    menu_text = _generate_main_menu(context)
    
    help_message = await event.edit(menu_text, parse_mode='html', link_preview=False)
    if not help_message: return
        
    # YECHIM: Holatni `context.state` orqali saqlaymiz, bu barqaror
    state_key = f"help_menu:{chat_id}"
    await context.state.set(state_key, {
        "message_id": help_message.id,
        "state": "main",
    }, ttl_seconds=120) # 2 daqiqadan so'ng avtomatik o'chadi

@userbot_cmd(listen=events.NewMessage(incoming=True, func=lambda e: e.is_reply))
async def help_navigator_listener(event: Message, context: AppContext):
    """Yordam menyusidagi javoblarni (navigatsiyani) boshqaradi."""
    if not (event.text and event.chat_id and event.client):
        return

    chat_id = event.chat_id
    state_key = f"help_menu:{chat_id}"
    state_data = context.state.get(state_key)

    if not state_data or event.reply_to_msg_id != state_data.get("message_id"):
        return

    user_input_raw = event.text.strip()
    prefix = context.config.get("BOT_PREFIX", ".")
    if user_input_raw.startswith(prefix):
        return

    await event.delete()
    user_input = user_input_raw.lower()

    try:
        message_to_edit = await event.client.get_messages(chat_id, ids=state_data["message_id"])
        if not message_to_edit:
            await context.state.delete(state_key)
            return
    except Exception as e:
        logger.warning(f"Help menyusini tahrirlash uchun xabarni olib bo'lmadi: {e}")
        await context.state.delete(state_key)
        return

    current_state = state_data['state']

    if user_input in ["0", "back"]:
        if current_state != "main":
            menu_text = _generate_main_menu(context)
            await message_to_edit.edit(menu_text, parse_mode='html')
            state_data['state'] = "main"
            await context.state.set(state_key, state_data, ttl_seconds=120)
        return

    if current_state == "main":
        if user_input.isdigit():
            categories = context.plugin_manager.get_all_categories()
            cat_index = int(user_input) - 1
            if 0 <= cat_index < len(categories):
                category_name = categories[cat_index]
                menu_text = _generate_category_menu(context, category_name)
                await message_to_edit.edit(menu_text, parse_mode='html')
                state_data['state'] = category_name
                await context.state.set(state_key, state_data, ttl_seconds=120)
            return

    command_data = context.plugin_manager.get_command(user_input)
    if command_data and command_data['category'] == current_state:
        details_text = _generate_command_details(command_data, prefix)
        await message_to_edit.edit(details_text, parse_mode='html')
        await context.state.set(state_key, state_data, ttl_seconds=120) # Sessiyani yangilash
        return