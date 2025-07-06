# userbot-v0/bot/plugins/user/animator.py
"""
Profilni (ism, bio, rasm) animatsiya qilish uchun plagin.
(To'liq modernizatsiya qilingan).
"""

import asyncio
import html
import os
import random
import re
import shlex
from datetime import datetime
from io import BytesIO
from pathlib import Path
from typing import Any, Dict, Optional

from loguru import logger
from PIL import Image, ImageDraw, ImageFont
from telethon.tl.custom import Message
from telethon.tl.functions.account import UpdateProfileRequest
from telethon.tl.functions.photos import UploadProfilePhotoRequest

from core.app_context import AppContext
from bot.decorators import userbot_cmd
from bot.lib.telegram import get_account_id
from bot.lib.ui import PaginationHelper, code, format_error, format_success, bold
from userbot.bot.lib.auth import admin_only

# --- Konfiguratsiya ---
FONT_FILE = "resources/Roboto-VariableFont_wdth,wght.ttf"
PFP_SAVE_PATH = Path("cache/animator_pfps")
PFP_SAVE_PATH.mkdir(parents=True, exist_ok=True)
START_TIME = datetime.now()

# --- Yordamchi Funksiyalar ---

def _parse_interval_to_seconds(interval_str: str) -> int:
    if match := re.match(r"^(\d+)([smh])$", interval_str.strip().lower()):
        value, unit = int(match.group(1)), match.group(2)
        return value * {'s': 1, 'm': 60, 'h': 3600}[unit]
    return 60

async def _parse_placeholders(context: AppContext, template: str, account_id: int, template_type: str) -> str:
    if not template: return ""
    now = datetime.now()
    uptime = str(now - START_TIME).split('.')[0]
    
    def handle_rotate(match):
        items = [item.strip() for item in match.group(1).split('|')]
        if not items: return ""
        
        state_key = f"anim:rotations:{template_type}:{account_id}"
        rot_state = context.state.get(state_key, {'index': 0, 'items': []})
        
        if rot_state['items'] != items:
            rot_state = {'items': items, 'index': 0}
        
        current_index = rot_state.get('index', 0)
        rotated_item = items[current_index % len(items)]
        rot_state['index'] = (current_index + 1) % len(items)
        
        # Holatni saqlash asinxron bo'lgani uchun uni alohida ishga tushiramiz
        asyncio.create_task(context.state.set(state_key, rot_state, persistent=True))
        return rotated_item
        
    processed = re.sub(r'\{rotate:(.*?)\}', handle_rotate, template)
    return processed.format(time=now.strftime("%H:%M"), date=now.strftime("%d.%m.%Y"), uptime=uptime)

# --- Asosiy Animatsiya Vazifalari ---

async def update_name_bio(context: AppContext, client, **kwargs):
    account_id = kwargs.get('account_id')
    if not account_id: return logger.error("Animator (name/bio): `account_id` topilmadi.")

    try:
        name_template = context.config.get(f"anim:name_template:{account_id}", "")
        bio_template = context.config.get(f"anim:bio_template:{account_id}", "")
        
        new_name = await _parse_placeholders(context, name_template, account_id, 'name')
        new_bio = await _parse_placeholders(context, bio_template, account_id, 'bio')
        
        last_name_key, last_bio_key = f"anim:last_name:{account_id}", f"anim:last_bio:{account_id}"
        if new_name != context.state.get(last_name_key) or new_bio != context.state.get(last_bio_key):
            await client(UpdateProfileRequest(first_name=new_name, about=new_bio))
            await context.state.set(last_name_key, new_name)
            await context.state.set(last_bio_key, new_bio)
    except Exception as e:
        logger.exception(f"[{account_id}] Ism/Bio yangilashda xato: {e}")

async def update_pfp_clock(context: AppContext, client, **kwargs):
    account_id = kwargs.get('account_id')
    if not account_id: return logger.error("Animator (pfp): `account_id` topilmadi.")

    try:
        pfp_text_format = context.config.get(f"anim:pfp_format:{account_id}", "{time}")
        pfp_text = await _parse_placeholders(context, pfp_text_format, account_id, 'pfp')
        
        last_pfp_key = f"anim:last_pfp:{account_id}"
        if pfp_text == context.state.get(last_pfp_key): return

        img = Image.new('RGB', (800, 800), color=context.config.get(f"anim:pfp_bg_color:{account_id}", "#161B22"))
        draw = ImageDraw.Draw(img)
        try:
            font = ImageFont.truetype(FONT_FILE, size=int(context.config.get(f"anim:pfp_font_size:{account_id}", 200)))
        except Exception: font = ImageFont.load_default()
            
        draw.text((400, 400), pfp_text, fill=context.config.get(f"anim:pfp_text_color:{account_id}", "white"), font=font, anchor="mm")
        
        with BytesIO() as buffer:
            buffer.name = "clock.png"
            img.save(buffer, "PNG")
            buffer.seek(0)
            pfp_file = await client.upload_file(buffer)
            await client(UploadProfilePhotoRequest(pfp_file))

        await context.state.set(last_pfp_key, pfp_text)
    except Exception as e:
        logger.exception(f"[{account_id}] PFP Clock yangilashda xato: {e}")

async def update_random_profile(context: AppContext, client, **kwargs):
    account_id = kwargs.get('account_id')
    if not account_id: return logger.error(f"Animator (random): `account_id` topilmadi.")

    try:
        if name_row := await context.db.fetchone("SELECT item_value FROM animator_random_items WHERE account_id = ? AND item_type = 'name' ORDER BY RANDOM() LIMIT 1", (account_id,)):
            await client(UpdateProfileRequest(first_name=name_row['item_value']))
        if bio_row := await context.db.fetchone("SELECT item_value FROM animator_random_items WHERE account_id = ? AND item_type = 'bio' ORDER BY RANDOM() LIMIT 1", (account_id,)):
            await client(UpdateProfileRequest(about=bio_row['item_value']))
        if pfp_row := await context.db.fetchone("SELECT item_value FROM animator_random_items WHERE account_id = ? AND item_type = 'pfp_path' ORDER BY RANDOM() LIMIT 1", (account_id,)):
            pfp_path = Path(pfp_row['item_value'])
            if pfp_path.exists():
                pfp_file = await client.upload_file(str(pfp_path))
                await client(UploadProfilePhotoRequest(pfp_file))
    except Exception as e:
        logger.exception(f"[{account_id}] Tasodifiy profilni yangilashda xato: {e}")

# --- Boshqaruv Buyruqlari ---

@userbot_cmd(command="anim-toggle", description="Animatsiya turini yoqadi/o'chiradi.")
@admin_only
async def animator_toggle_cmd(event: Message, context: AppContext):
    if not (event.text and event.client): return
    account_id = await get_account_id(context, event.client)
    if not account_id: return await event.edit(format_error("Akkaunt ID topilmadi."), parse_mode='html')

    parts = event.text.split()
    if len(parts) < 3:
        return await event.edit(format_error("Format: <code>.anim-toggle &lt;turi&gt; &lt;on|off&gt; [interval]</code>\nMasalan: <code>.anim-toggle pfp on 60s</code>"), parse_mode='html')
    
    anim_type, state = parts[1].lower(), parts[2].lower()
    interval_str = parts[3] if len(parts) > 3 else None

    type_map = {"pfp": "wiki.random_article", "namebio": "animator.update_name_bio", "random": "animator.update_random_profile"}
    if anim_type not in type_map:
        return await event.edit(format_error(f"Noto'g'ri tur. Mavjud: {', '.join(type_map.keys())}"), parse_mode='html')

    job_id = f"animator_{anim_type}_{account_id}"
    if state == "on":
        interval_seconds = _parse_interval_to_seconds(interval_str or '60s')
        await context.scheduler.add_job(
            task_key=type_map[anim_type],
            account_id=account_id,
            trigger_type="interval",
            trigger_args={"seconds": interval_seconds},
            job_id=job_id,
        )
    else: # off
        await context.scheduler.remove_job(job_id)

    await event.edit(format_success(f"{bold(anim_type)} animatori {'yoqildi' if state == 'on' else 'o‘chirildi'}."), parse_mode='html')


@userbot_cmd(command="anim-set", description="Animatsiya uchun shablon yoki rang/shrift o'rnatadi.")
@admin_only
async def animator_set_template_cmd(event: Message, context: AppContext):
    if not (event.text and event.client): return
    account_id = await get_account_id(context, event.client)
    if not account_id: return await event.edit(format_error("Akkaunt ID topilmadi."), parse_mode='html')

    parts = event.text.split(maxsplit=2)
    if len(parts) < 3:
        return await event.edit(format_error("Format: <code>.anim-set &lt;turi&gt; &lt;qiymat&gt;</code>"), parse_mode='html')
    
    template_type, template = parts[1].lower(), parts[2]
    allowed_types = ['name_template', 'bio_template', 'pfp_format', 'pfp_bg_color', 'pfp_text_color', 'pfp_font_size']
    if template_type not in allowed_types:
        return await event.edit(format_error(f"Noto'g'ri tur. Ruxsat etilganlar: {', '.join(allowed_types)}"), parse_mode='html')

    await context.config.set(f"anim:{template_type}:{account_id}", template)
    await event.edit(format_success(f"{bold(template_type.replace('_', ' ').capitalize())} uchun qiymat o‘rnatildi."), parse_mode='html')

@userbot_cmd(command="anim-rand", description="Tasodifiy rejim uchun ro'yxatni boshqaradi.")
@admin_only
async def animator_random_list_cmd(event: Message, context: AppContext):
    if not (event.text and event.client): return
    account_id = await get_account_id(context, event.client)
    if not account_id: return await event.edit(format_error("Akkaunt ID topilmadi."), parse_mode='html')

    parts = event.text.split(maxsplit=2)
    if len(parts) < 2:
        return await event.edit(format_error("Format: <code>.anim-rand &lt;add|list|del&gt; &lt;turi&gt; [qiymat|id]</code>"), parse_mode='html')
        
    command, item_type = parts[1].lower(), parts[2].split()[0].lower()
    value = parts[2][len(item_type):].strip() if len(parts) > 2 else ""

    if item_type not in ('name', 'bio', 'pfp'):
        return await event.edit(format_error("Noto'g'ri tur. Mavjud: `name`, `bio`, `pfp`"), parse_mode='html')

    if command == "add":
        if item_type == "pfp":
            replied = await event.get_reply_message()
            if not replied or not replied.photo:
                return await event.edit(format_error("Tasodifiy rasm qo'shish uchun rasmga javob bering."), parse_mode='html')
            file_path = await replied.download_media(file=PFP_SAVE_PATH)
            if not file_path: return await event.edit(format_error("Rasmni yuklab bo'lmadi."), parse_mode='html')
            value = str(Path(file_path).resolve())
        elif not value:
            return await event.edit(format_error(f"`{item_type}` uchun qiymat kiriting."), parse_mode='html')
        
        await context.db.execute("INSERT INTO animator_random_items (account_id, item_type, item_value) VALUES (?, ?, ?)", (account_id, item_type, value))
        await event.edit(format_success(f"Tasodifiy ro'yxatga yangi `{item_type}` qo'shildi."), parse_mode='html')

    elif command == "list":
        items = await context.db.fetchall("SELECT id, item_value FROM animator_random_items WHERE account_id = ? AND item_type = ?", (account_id, item_type))
        if not items: return await event.edit(f"ℹ️ Tasodifiy `{item_type}` ro'yxati bo'sh.", parse_mode='html')
        
        lines = [f"• ID: {code(item['id'])} | Qiymat: `{html.escape(item['item_value'])}`" for item in items]
        title = f"📜 Tasodifiy {item_type.upper()} Ro'yxati"
        paginator = PaginationHelper(context=context, items=lines, title=title, origin_event=event)
        await paginator.start()
        
    elif command == "del":
        if not value.isdigit(): return await event.edit(format_error("O'chirish uchun element ID'sini kiriting."), parse_mode='html')
        deleted = await context.db.execute("DELETE FROM animator_random_items WHERE account_id = ? AND id = ?", (account_id, int(value)))
        await event.edit(format_success("Element o'chirildi.") if deleted > 0 else format_error("Element topilmadi."), parse_mode='html')

def register_plugin_tasks(context: AppContext):
    """Bu plaginga tegishli fon vazifalarini ro'yxatdan o'tkazadi."""
    context.tasks.register(key="animator.update_name_bio", description="Profil ism va biosini animatsiya qiladi.")(update_name_bio)
    context.tasks.register(key="animator.update_pfp_clock", description="Profil rasmini soat bilan yangilaydi.")(update_pfp_clock)
    context.tasks.register(key="animator.update_random_profile", description="Profilni tasodifiy ma'lumotlar bilan yangilaydi.")(update_random_profile)

