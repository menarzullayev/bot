# userbot-v0/bot/plugins/user/ai_commenter.py
"""
Kanallarga AI yordamida avtomatik izoh yozish uchun plagin.
(To'liq modernizatsiya qilingan).
"""

import asyncio
import html
import random
from datetime import datetime, timedelta
from typing import Dict

from loguru import logger
from telethon import events, types
from telethon.tl.custom import Message

from core.app_context import AppContext
from bot.decorators import userbot_cmd
from bot.lib.telegram import get_account_id, resolve_entity, get_display_name
from bot.lib.ui import PaginationHelper, format_error, format_success, bold, code
from bot.lib.auth import admin_only

# --- Global O'zgaruvchilar ---
_last_comment_time: Dict[int, datetime] = {}

# --- YADRO FUNKSIYALARI ---

async def _check_and_generate_comment(event: Message, context: AppContext, account_id: int):
    """Kanal posti uchun shartlarni tekshiradi va mos bo'lsa, AI yordamida izoh generatsiya qiladi."""
    channel_id = event.chat_id
    if not channel_id: return

    channel_config = await context.db.fetchone(
        "SELECT * FROM ai_commenter_channels WHERE userbot_account_id = ? AND channel_id = ? AND is_active = 1",
        (account_id, channel_id)
    )
    if not channel_config: return

    personality = await context.db.fetchone(
        "SELECT * FROM ai_personalities WHERE userbot_account_id = ? AND name = ?",
        (account_id, channel_config['personality_name'])
    )
    if not personality:
        return logger.warning(f"Kanal {channel_id} uchun '{channel_config['personality_name']}' shaxsiyati topilmadi.")

    cooldown = timedelta(seconds=int(personality.get('cooldown_seconds', 600)))
    if last_time := _last_comment_time.get(channel_id):
        if (datetime.now() - last_time) < cooldown:
            return logger.trace(f"Cooldown faol: {channel_id}")

    text_lower = (event.text or "").lower()
    if include := channel_config.get('include_keywords'):
        if not any(k.strip() in text_lower for k in include.split(',')): return
    if exclude := channel_config.get('exclude_keywords'):
        if any(k.strip() in text_lower for k in exclude.split(',')): return
    
    full_prompt = f"{personality['prompt']}\n\nPost matni: \"{event.text}\"\n\nUshbu postga izohingiz:"
    try:
        response = await context.ai_service.generate_text(full_prompt)
        answer = response.get("text", "").strip()
        
        if not answer or "NO_COMMENT" in answer.upper(): return

        delay = random.randint(int(channel_config.get('delay_min_seconds', 10)), int(channel_config.get('delay_max_seconds', 30)))
        await asyncio.sleep(delay)
        
        await event.reply(answer)
        
        _last_comment_time[channel_id] = datetime.now()
        await context.db.execute(
            "INSERT INTO ai_usage_stats (userbot_account_id, stat_date, call_count) VALUES (?, ?, 1) "
            "ON CONFLICT(userbot_account_id, stat_date) DO UPDATE SET call_count = call_count + 1",
            (account_id, datetime.now().strftime("%Y-%m-%d"))
        )
        logger.success(f"'{getattr(event.chat, 'title', channel_id)}' kanaliga izoh yozildi.")
    except Exception as e:
        logger.exception(f"AI izohini generatsiya qilishda xatolik: {e}")

# --- HODISA TINGLOVCHISI (LISTENER) ---
@userbot_cmd(listen=events.NewMessage(incoming=True, func=lambda e: e.is_channel and not e.is_group))
async def ai_commenter_listener(event: Message, context: AppContext):
    if not event.text or not event.client: return
    
    if not (account_id := await get_account_id(context, event.client)): return
    
    if not context.ai_service.is_configured:
        return logger.warning("AI Commenter: AI Servis sozlanmagan, ish to'xtatildi.")

    await _check_and_generate_comment(event, context, account_id)

# --- BOSHqaruv BUYRUQLARI ---

@userbot_cmd(command="aic-p", description="Shaxsiyatlarni (personality) boshqarish.")
@admin_only
async def personality_manager_cmd(event: Message, context: AppContext):
    if not event.text or not event.client: return
    account_id = await get_account_id(context, event.client)
    if not account_id: return await event.edit(format_error("Akkaunt ID topilmadi."), parse_mode='html')

    parts = event.text.split(maxsplit=2)
    if len(parts) < 2:
        return await event.edit(format_error("Format: <code>.aic-p &lt;add|rm|list&gt; [parametrlar]</code>"), parse_mode='html')
    
    command = parts[1].lower()
    args_str = parts[2] if len(parts) > 2 else ""

    if command == "add":
        name, _, prompt = args_str.partition(' ')
        if not (name and prompt): return await event.edit(format_error("Format: <code>.aic-p add &lt;nom&gt; &lt;prompt&gt;</code>"), parse_mode='html')
        await context.db.execute("REPLACE INTO ai_personalities (userbot_account_id, name, prompt) VALUES (?, ?, ?)", (account_id, name, prompt))
        await event.edit(format_success(f"'{bold(name)}' shaxsiyati saqlandi."), parse_mode='html')
        
    elif command == "rm":
        name = args_str.strip()
        if not name: return await event.edit(format_error("Format: <code>.aic-p rm &lt;nom&gt;</code>"), parse_mode='html')
        await context.db.execute("DELETE FROM ai_personalities WHERE userbot_account_id = ? AND name = ?", (account_id, name))
        await event.edit(format_success(f"'{bold(name)}' shaxsiyati o'chirildi."), parse_mode='html')
        
    elif command == "list":
        all_p = await context.db.fetchall("SELECT name, cooldown_seconds, prompt FROM ai_personalities WHERE userbot_account_id = ?", (account_id,))
        if not all_p: return await event.edit("<b>Hozircha shaxsiyatlar yaratilmagan.</b>", parse_mode='html')
        
        lines = [f"• {code(p['name'])} ({p['cooldown_seconds']}s) - `{p['prompt'][:50]}...`" for p in all_p]
        pagination = PaginationHelper(context=context, items=lines, title="🤖 Mavjud shaxsiyatlar", origin_event=event)
        await pagination.start()

@userbot_cmd(command="aic-ch", description="Kanallarni boshqarish.")
@admin_only
async def channel_manager_cmd(event: Message, context: AppContext):
    if not event.text or not event.client: return
    account_id = await get_account_id(context, event.client)
    if not account_id: return await event.edit(format_error("Akkaunt ID topilmadi."), parse_mode='html')
    
    parts = event.text.split(maxsplit=2)
    if len(parts) < 2: return await event.edit(format_error("Format: <code>.aic-ch &lt;add|rm|list|config&gt; [parametrlar]</code>"), parse_mode='html')
    
    command = parts[1].lower()
    params_str = parts[2] if len(parts) > 2 else ""

    if command == "add":
        try:
            ch_id, _, personality = params_str.partition('-p')
            entity = await resolve_entity(context, event.client, ch_id.strip())
            if not isinstance(entity, types.Channel): return await event.edit(format_error("Faqat kanallar bilan ishlash mumkin."), parse_mode='html')
            
            await context.db.execute("REPLACE INTO ai_commenter_channels (userbot_account_id, channel_id, personality_name) VALUES (?, ?, ?)", 
                                     (account_id, entity.id, personality.strip()))
            await event.edit(format_success(f"'{bold(entity.title)}' kanali '{bold(personality.strip())}' shaxsiyatiga biriktirildi."), parse_mode='html')
        except Exception as e:
            await event.edit(format_error(f"Kanal qo'shishda xato: {e}"), parse_mode='html')
            
    elif command == "rm":
        entity = await resolve_entity(context, event.client, params_str)
        if not isinstance(entity, types.Channel): return await event.edit(format_error("Kanal topilmadi."), parse_mode='html')
        await context.db.execute("DELETE FROM ai_commenter_channels WHERE userbot_account_id = ? AND channel_id = ?", (account_id, entity.id))
        await event.edit(format_success(f"'{bold(entity.title)}' kanali kuzatuvdan olindi."), parse_mode='html')

    elif command == "list":
        channels = await context.db.fetchall("SELECT * FROM ai_commenter_channels WHERE userbot_account_id = ?", (account_id,))
        if not channels: return await event.edit("<b>Kuzatilayotgan kanallar yo'q.</b>", parse_mode='html')
        
        lines = []
        for ch in channels:
            try:
                entity = await resolve_entity(context, event.client, ch['channel_id'])
                ch_name = get_display_name(entity) if entity else "Noma'lum"
            except Exception:
                ch_name = "Noma'lum"
            
            lines.append(f"• {bold(ch_name)} ({code(ch['channel_id'])}) | Shaxsiyat: `{ch['personality_name']}` | Holati: {'✅' if ch['is_active'] else '❌'}")
        
        pagination = PaginationHelper(context=context, items=lines, title="📡 Kuzatilayotgan kanallar", origin_event=event)
        await pagination.start()


@userbot_cmd(command="aic-stats", description="AI Commenter API foydalanish statistikasini ko'rsatadi.")
@admin_only
async def stats_cmd(event: Message, context: AppContext):
    if not event.client: return
    account_id = await get_account_id(context, event.client)
    if not account_id: return await event.edit(format_error("Akkaunt ID topilmadi."), parse_mode='html')

    today = datetime.now().strftime("%Y-%m-%d")
    today_stat = await context.db.fetchone("SELECT call_count FROM ai_usage_stats WHERE userbot_account_id = ? AND stat_date = ?", (account_id, today))
    total_stat = await context.db.fetchone("SELECT SUM(call_count) as total FROM ai_usage_stats WHERE userbot_account_id = ?", (account_id,))
    
    await event.edit(f"<b>📊 AI Commenter Statistikasi:</b>\n- Bugun: {code(today_stat['call_count'] if today_stat else 0)}\n- Jami: {code(total_stat['total'] if total_stat else 0)}", parse_mode='html')

