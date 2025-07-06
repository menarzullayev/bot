# bot/plugins/admin/state_cmds.py
"""
Userbotning ishlash davomidagi holatini (state) boshqarish va kuzatish
uchun mo'ljallangan admin plaginlari.
"""

import html
import json
import sys
from typing import Any
import uuid

from loguru import logger
from telethon.tl.custom import Message

from core.app_context import AppContext
from bot.decorators import userbot_cmd
from bot.lib.auth import admin_only, owner_only
from bot.lib.ui import (
    PaginationHelper,
    format_error,
    format_success,
    request_confirmation,
    send_as_file_if_long,
)
from bot.lib.utils import parse_string_to_value

PROTECTED_KEYS = {"system.start_time", "system.restart_pending"}


def _get_value_details(value: Any) -> str:
    """Qiymatning tipi va hajmi haqida ma'lumot beradi."""
    try:
        size = sys.getsizeof(value)
        return f"Turi: {type(value).__name__}, Hajmi: {size} bayt"
    except Exception:
        return f"Turi: {type(value).__name__}, Hajmi: N/A"


def _json_default_serializer(o: Any) -> str:
    """JSON'ga o'girib bo'lmaydigan obyektlar uchun matnli ko'rinish."""
    return f"<Not Serializable: {type(o).__name__}>"


@userbot_cmd(command="state get", description="Holatdan (state) biror kalit qiymatini oladi.")
@admin_only
async def state_get_handler(event: Message, context: AppContext):
    """
    .state get system.start_time
    .state get commands.disabled
    """
    if not event.text:
        return
    key = event.text.split(maxsplit=2)[2] if len(event.text.split()) > 2 else ""
    if not key:
        return await event.edit(format_error("Qaysi kalit qiymatini olish kerak?"), parse_mode='html')

    data = context.state.get(key)
    if data is None:
        return await event.edit(format_error(f"<code>{html.escape(key)}</code> kaliti bo'yicha holat topilmadi."), parse_mode='html')

    details = _get_value_details(data)
    try:
        pretty_data = json.dumps(data, indent=2, ensure_ascii=False, default=_json_default_serializer)
        response_text = (f"<b>📦 Kalit:</b> <code>{html.escape(key)}</code>\n"
                         f"<b>ℹ️ Ma'lumot:</b> <i>{details}</i>\n\n"
                         f"<pre><code class=\"language-json\">{html.escape(pretty_data)}</code></pre>")
    except TypeError:
        response_text = (f"<b>📦 Kalit:</b> <code>{html.escape(key)}</code>\n"
                         f"<b>ℹ️ Ma'lumot:</b> <i>{details}</i>\n\n"
                         f"<pre>{html.escape(str(data))}</pre>")
    
    await send_as_file_if_long(event, response_text, filename=f"state_{key.replace('.', '_')}.txt")


@userbot_cmd(command="state dump", description="Joriy dastur holatini (state) to'liq JSON ko'rinishida ko'rsatadi.")
@admin_only
async def state_dump_handler(event: Message, context: AppContext):
    await event.edit("<code>🔄 To'liq holat ma'lumotlari tayyorlanmoqda...</code>", parse_mode='html')
    data_to_dump = context.state.dump()
    
    try:
        pretty_json = json.dumps(data_to_dump, indent=2, ensure_ascii=False, default=_json_default_serializer)
        await send_as_file_if_long(event, pretty_json, filename="state_dump.json", caption="📦 To'liq Dastur Holati")
    except Exception as e:
        await event.edit(format_error(f"Holatni JSON formatiga o'girishda xato:\n<code>{e}</code>"), parse_mode='html')


@userbot_cmd(command="state set", description="Holatga yangi qiymat o'rnatadi.")
@owner_only
async def state_set_handler(event: Message, context: AppContext):
    """
    .state set my_plugin.enabled true
    .state set user.status "AFK"
    """
    if not event.text or not event.sender_id:
        return
        
    parts = event.text.split(maxsplit=3)
    if len(parts) < 3:
        return await event.edit(format_error("<b>Format:</b> <code>.state set &lt;kalit&gt; &lt;qiymat&gt;</code> yoki <code>.state set &lt;kod&gt;</code>"), parse_mode='html')

    # 1. Bu tasdiqlash chaqiruvi ekanligini tekshiramiz
    code = parts[2]
    confirm_key = f"confirm_set:{event.sender_id}:{code}"
    data_to_set = context.state.get(confirm_key)

    if data_to_set and isinstance(data_to_set, dict):
        key = data_to_set['key']
        value = data_to_set['value']
        
        await context.state.set(key, value, persistent=True)
        await context.state.delete(confirm_key)
        return await event.edit(format_success(f"Holat o'rnatildi:\n<code>{html.escape(key)} = {html.escape(str(value))}</code>"), parse_mode='html')

    # 2. Bu birinchi chaqiruv. Tasdiqlash so'raymiz.
    if len(parts) < 4:
        return await event.edit(format_error("<b>Format:</b> <code>.state set &lt;kalit&gt; &lt;qiymat&gt;</code>"), parse_mode='html')
    
    key, value_str = parts[2], parts[3]
    if key in PROTECTED_KEYS:
        return await event.edit(format_error(f"`{key}` - himoyalangan kalit."), parse_mode='html')

    try:
        value = parse_string_to_value(value_str)
        confirm_code = str(uuid.uuid4().hex[:6])
        new_confirm_key = f"confirm_set:{event.sender_id}:{confirm_code}"
        
        await context.state.set(new_confirm_key, {'key': key, 'value': value}, ttl_seconds=30, persistent=False)
        
        prompt_text = (
            f"⚠️ <b>DIQQAT!</b> Siz holatga o'zgartirish kirityapsiz:\n"
            f"<pre>{html.escape(key)} = {html.escape(str(value))}</pre>\n"
            f"✅ Davom etish uchun <b>30 soniya ichida</b> quyidagi buyruqni yuboring:\n"
            f"<code>.state set {confirm_code}</code>"
        )
        await event.edit(prompt_text, parse_mode='html')
    except ValueError as e:
        await event.edit(format_error(f"Qiymatni o'girishda xatolik: {e}"), parse_mode='html')



@userbot_cmd(command="state del", description="Holatdan kalitni o'chiradi.")
@owner_only
async def state_del_handler(event: Message, context: AppContext):
    """ .state del my_plugin.some_temp_data """
    if not event.text or not event.sender_id:
        return
    
    key_or_code = event.text.split(maxsplit=2)[2] if len(event.text.split()) > 2 else ""
    if not key_or_code:
        return await event.edit(format_error("Qaysi kalitni o'chirish yoki tasdiqlash kodini kiritish kerak?"), parse_mode='html')

    # 1. Tasdiqlashni tekshirish
    confirm_key = f"confirm_del:{event.sender_id}:{key_or_code}"
    data_to_delete = context.state.get(confirm_key)
    if data_to_delete and isinstance(data_to_delete, dict) and 'key' in data_to_delete:
        key_to_delete = data_to_delete['key']
        await context.state.delete(key_to_delete)
        await context.state.delete(confirm_key)
        return await event.edit(format_success(f"<code>{html.escape(key_to_delete)}</code> kaliti holatdan o'chirildi."), parse_mode='html')

    # 2. Birinchi chaqiruv
    key = key_or_code
    if key in PROTECTED_KEYS:
        return await event.edit(format_error(f"`{key}` - himoyalangan kalit."), parse_mode='html')
    if context.state.get(key) is None:
        return await event.edit(format_error(f"`{key}` kaliti holatda topilmadi."), parse_mode='html')

    confirm_code = str(uuid.uuid4().hex[:6])
    new_confirm_key = f"confirm_del:{event.sender_id}:{confirm_code}"
    
    await context.state.set(new_confirm_key, {'key': key}, ttl_seconds=30, persistent=False)
    
    prompt_text = (
        f"⚠️ <b>DIQQAT!</b> Siz holatdan <code>{html.escape(key)}</code> kalitini o'chiryapsiz.\n"
        f"✅ Davom etish uchun <b>30 soniya ichida</b> quyidagi buyruqni yuboring:\n"
        f"<code>.state del {confirm_code}</code>"
    )
    await event.edit(prompt_text, parse_mode='html')




@userbot_cmd(command="state save", description="Joriy holatni diskka majburan saqlaydi.")
@owner_only
async def state_save_handler(event: Message, context: AppContext):
    await event.edit("<code>💾 Holat diskka saqlanmoqda...</code>", parse_mode='html')
    try:
        await context.state.save_to_disk()
        await event.edit(format_success("Dastur holati muvaffaqiyatli saqlandi."), parse_mode='html')
    except Exception as e:
        await event.edit(format_error(f"Holatni saqlashda xatolik: {e}"), parse_mode='html')


@userbot_cmd(command="state listeners", description="Faol holat tinglovchilari ro'yxatini ko'rsatadi.")
@admin_only
async def state_listeners_handler(event: Message, context: AppContext):
    await event.edit("<code>🔄 Faol tinglovchilar ro'yxati olinmoqda...</code>", parse_mode='html')
    
    if not hasattr(context.state, "_listeners"):
        return await event.edit(format_error("Holat tinglovchilarini olib bo'lmadi."), parse_mode='html')

    listeners = context.state._listeners
    if not listeners:
        return await event.edit("<b>ℹ️ Hech qanday faol tinglovchi topilmadi.</b>", parse_mode='html')

    lines = []
    for key, callbacks in listeners.items():
        if not callbacks: continue
        lines.append(f"<b>- Kalit:</b> <code>{key}</code>")
        for cb in callbacks:
            cb_name = getattr(cb, '__qualname__', 'N/A')
            cb_module = getattr(cb, '__module__', 'N/A')
            lines.append(f"   • <code>{html.escape(cb_name)}</code> (<i>fayl: {html.escape(cb_module)}</i>)")
        lines.append("")
        
    pagination = PaginationHelper(context=context, items=lines, title="🎧 Faol Holat Tinglovchilari", origin_event=event)
    await pagination.start()


@userbot_cmd(command="state clear", description="Holatdagi barcha yozuvlarni o'chiradi (himoyalanganlardan tashqari).")
@owner_only
async def state_clear_handler(event: Message, context: AppContext):
    if not event.text or not event.sender_id:
        return

    # Buyruqdan keyingi qismni olamiz (bu tasdiqlash kodi bo'lishi mumkin)
    arg = event.text.split(maxsplit=2)[2] if len(event.text.split()) > 2 else ""

    # 1. Bu tasdiqlash chaqiruvi ekanligini tekshiramiz
    if arg: # Agar argument bo'lsa, demak bu kod bo'lishi mumkin
        confirm_key = f"confirm_clear:{event.sender_id}:{arg}"
        if context.state.get(confirm_key):
            await event.edit("<code>🔄 Holat tozalanmoqda...</code>", parse_mode='html')
            
            # AppState.clear() metodi endi o'chirilgan yozuvlar sonini qaytaradi
            cleared_count = await context.state.clear(protected_keys=PROTECTED_KEYS)
            await context.state.delete(confirm_key)
            return await event.edit(format_success(f"{cleared_count} ta holat yozuvi o'chirildi."), parse_mode='html')

    # 2. Bu birinchi chaqiruv. Tasdiqlash so'raymiz.
    confirm_code = str(uuid.uuid4().hex[:6])
    new_confirm_key = f"confirm_clear:{event.sender_id}:{confirm_code}"
    
    # Keshga `True` qiymatini saqlaymiz, bu kodning mavjudligini bildiradi
    await context.state.set(new_confirm_key, True, ttl_seconds=30, persistent=False)
    
    prompt_text = (
        f"⚠️ <b>DIQQAT!</b> Siz holatdagi <b>BARCHA</b> (himoyalanmagan) yozuvlarni o'chiryapsiz.\n"
        f"✅ Davom etish uchun <b>30 soniya ichida</b> quyidagi buyruqni yuboring:\n"
        f"<code>.state clear {confirm_code}</code>"
    )
    await event.edit(prompt_text, parse_mode='html')

