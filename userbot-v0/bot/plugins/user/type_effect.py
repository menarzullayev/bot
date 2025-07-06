# bot/plugins/user/type_effect.py
"""
Matnni turli animatsion effektlar bilan yozib beradigan plagin.
(To'liq modernizatsiya qilingan).
"""

import argparse
import asyncio
import html
import random
import re
import shlex
from typing import Optional, Sequence, Tuple

from loguru import logger
from telethon.tl.custom import Message
from telethon.errors import RPCError


from core.app_context import AppContext
from bot.decorators import userbot_cmd
from bot.lib.ui import format_error

# ===== YORDAMCHI FUNKSIYALAR =====

def _prepare_highlighted_text(text: str, lang: Optional[str]) -> Sequence[Tuple[str, Optional[str]]]:
    """Matnni sintaksis belgilari bilan tayyorlaydi (oddiy simulyatsiya)."""
    if lang != 'py':
        return [(char, None) for char in text]

    keywords = {'def', 'class', 'import', 'from', 'return', 'if', 'else', 'for', 'while', 'in', 'async', 'await'}
    output: list[tuple[str, str | None]] = []
    pattern = re.compile(r"(\b" + r"\b|\b".join(keywords) + r"\b)|(\".*?\"|'.*?')|(#.*)")
    last_idx = 0

    for match in pattern.finditer(text):
        start, end = match.span()
        output.extend([(char, None) for char in text[last_idx:start]])
        keyword, string, comment = match.groups()
        
        tag = 'b' if keyword else 'i' if string else 'code' if comment else None
        if tag:
            output.extend([(char, f"<{tag}>") for char in match.group(0)])
        last_idx = end
        
    output.extend([(char, None) for char in text[last_idx:]])
    return output

# ===== ASOSIY BUYRUQ =====

@userbot_cmd(command="type", description="Matnni turli animatsion effektlar bilan yozib beradi.")
async def typewriter_effect(event: Message, context: AppContext):
    """
    .type Salom Dunyo!
    .type -H                     (javob berilgan xabarga)
    .type -m --speed 0.01        (javob berilgan xabarga)
    .type -l py                  (javob berilgan faylga)
    """
    if not event.text: return

    args_str = event.text.split(maxsplit=1)[1] if len(event.text.split()) > 1 else ""
    
    # Argumentlarni va matnni ajratish
    parser = argparse.ArgumentParser(prog=".type", add_help=False)
    parser.add_argument('-s', '--speed', type=float, default=0.04)
    parser.add_argument('-c', '--cursor', type=str, default='█')
    parser.add_argument('-H', '--hacker', action='store_true')
    parser.add_argument('-m', '--mistake', action='store_true')
    parser.add_argument('-l', '--lang', type=str)
    
    try:
        parsed_args, remaining_text_list = parser.parse_known_args(shlex.split(args_str))
        text_to_type = " ".join(remaining_text_list)
    except (ValueError, SystemExit) as e:
        return await event.edit(format_error(f"Argument xatosi: {e}"), parse_mode='html')

    # Agar matn argumentlarda bo'lmasa, javobdan olishga harakat qilamiz
    if not text_to_type:
        reply_msg = await event.get_reply_message()
        if reply_msg and reply_msg.text:
            text_to_type = reply_msg.text
        else:
            return await event.edit(format_error("Yozish uchun matn kiriting yoki matnli xabarga javob bering."), parse_mode='html')

    if not text_to_type:
        return await event.edit(format_error("Yozish uchun matn topilmadi."), parse_mode='html')

    await event.edit("...", parse_mode='html') # Boshlang'ich xabar
    
    prepared_text = _prepare_highlighted_text(text_to_type, parsed_args.lang)
    typing_text = ""
    current_tag: Optional[str] = None
    
    for char, new_tag in prepared_text:
        try:
            if current_tag and new_tag != current_tag:
                typing_text += f"</{current_tag.strip('<>')}>"
                current_tag = None
            if new_tag and new_tag != current_tag:
                typing_text += new_tag
                current_tag = new_tag

            if parsed_args.hacker and random.random() < 0.2:
                for _ in range(random.randint(1, 3)):
                    fake_char = random.choice("!@#$%^&*()_+=-`~[]{}|;:,.<>/?")
                    await event.edit(f"{typing_text}{fake_char}{parsed_args.cursor}", parse_mode='html')
                    await asyncio.sleep(0.02)
            
            if parsed_args.mistake and random.random() < 0.05:
                mistake = random.choice("abcdefghijklmnopqrstuvwxyz")
                await event.edit(f"{typing_text}{mistake}{parsed_args.cursor}", parse_mode='html')
                await asyncio.sleep(0.1)

            typing_text += char
            await event.edit(f"{typing_text}{parsed_args.cursor}", parse_mode='html')

            pause = 0.3 if char in '.?!' else 0.15 if char == ',' else parsed_args.speed
            await asyncio.sleep(pause)
        
        except RPCError as e:
            logger.warning(f"Type animatsiyasi to'xtatildi: {e}")
            return # Xatolik bo'lsa, to'xtatamiz
        except Exception:
             # Boshqa kutilmagan xatoliklar uchun ham to'xtatamiz
            return

    if current_tag:
        typing_text += f"</{current_tag.strip('<>')}>"

    await event.edit(typing_text, parse_mode='html')
