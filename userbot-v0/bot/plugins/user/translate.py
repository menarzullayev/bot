# bot/plugins/user/translate.py
"""
Matnlarni Google Translate yoki AI yordamida tarjima qilish,
tarix va statistikani ko'rish uchun mo'ljallangan plagin.
(To'liq modernizatsiya qilingan).
"""

import asyncio
import html
import shlex
from functools import partial
from typing import Any, Dict, List, Optional, Tuple

try:
    from googletrans import LANGUAGES as GOOGLE_LANGUAGES, Translator
    from googletrans.models import Translated
    GOOGLETRANS_AVAILABLE = True
except ImportError:
    GOOGLE_LANGUAGES, Translator, Translated = {}, None, None
    GOOGLETRANS_AVAILABLE = False

from loguru import logger
from telethon.tl.custom import Message

from core.app_context import AppContext
from bot.decorators import userbot_cmd
from bot.lib.telegram import get_account_id
from bot.lib.ui import PaginationHelper, format_error, format_success
from bot.lib.utils import RaiseArgumentParser

FLAG_EMOJIS = {"EN": "🇬🇧", "DE": "🇩🇪", "FR": "🇫🇷", "RU": "🇷🇺", "UZ": "🇺🇿", "ES": "🇪🇸", "IT": "🇮🇹", "TR": "🇹🇷", "JA": "🇯🇵", "KO": "🇰🇷", "ZH-CN": "🇨🇳"}
TEXT_CHUNK_SIZE = 4000

# --- YORDAMCHI FUNKSIYALAR ---

async def _log_translate_usage(context: AppContext, account_id: int, provider: str, source_lang: str, target_lang: str):
    """Tarjima statistikasi uchun yozuv qo'shadi."""
    try:
        await context.db.execute(
            "INSERT INTO translation_stats (account_id, provider, source_lang, target_lang) VALUES (?, ?, ?, ?)",
            (account_id, provider, source_lang, target_lang),
        )
    except Exception as e:
        logger.error(f"Tarjima statistikasini yozishda xato: {e}")

def _parse_tr_args(args: List[str]) -> Tuple[Optional[List[str]], str]:
    """Argumentlardan til kodlari va matnni ajratadi."""
    if not args:
        return None, ""
    
    # Birinchi argument til kodi(lar)mi yoki yo'qligini tekshirish
    first_arg = args[0]
    # Agar vergul bo'lsa, bu aniq til kodlari
    if ',' in first_arg:
        potential_langs = [lang.strip().lower() for lang in first_arg.split(',')]
    # Agar 5 belgidan kam, faqat harflardan iborat va raqam bo'lmasa, bu til kodi bo'lishi mumkin
    elif len(first_arg) <= 5 and first_arg.isalpha():
        potential_langs = [first_arg.lower()]
    else:
        return None, " ".join(args)

    if GOOGLE_LANGUAGES and all(lang in GOOGLE_LANGUAGES for lang in potential_langs):
        return potential_langs, " ".join(args[1:])
        
    return None, " ".join(args)

async def _translate(context: AppContext, text: str, target_langs: List[str], use_ai: bool) -> List[Dict[str, str]]:
    """Matnni tanlangan provayder orqali tarjima qiladi."""
    if use_ai:
        if not context.ai_service.is_configured:
            raise ValueError("AI xizmati sozlanmagan.")
        
        results = []
        for lang in target_langs:
            lang_name = GOOGLE_LANGUAGES.get(lang, lang) if GOOGLE_LANGUAGES else lang
            prompt = (f"Translate the following text to {lang_name}. "
                      f"Provide only the translated text, without any additional comments.\n\n"
                      f"Text:\n---\n{text}\n---")
            ai_result = await context.ai_service.generate_text(prompt)
            translated_text = ai_result.get("text", "").strip('"` ')
            results.append({"text": translated_text, "source_lang": "AI", "target_lang": lang.upper()})
        return results

    else: # Google Translate
        if not Translator:
            raise ModuleNotFoundError("`googletrans` kutubxonasi o'rnatilmagan.")
        
        translator = Translator()
        text_chunks = [text[i : i + TEXT_CHUNK_SIZE] for i in range(0, len(text), TEXT_CHUNK_SIZE)]
        results = []
        loop = asyncio.get_running_loop()

        for lang in target_langs:
            try:
                tasks = [loop.run_in_executor(None, partial(translator.translate, chunk, dest=lang)) for chunk in text_chunks]
                chunk_results: List[Any] = await asyncio.gather(*tasks)
                
                if not chunk_results:
                    raise ValueError("Tarjima natijasi bo'sh.")

                full_text = "".join(r.text for r in chunk_results)
                source_lang = chunk_results[0].src.upper() if chunk_results and hasattr(chunk_results[0], 'src') and chunk_results[0].src else "auto"
                results.append({"text": full_text, "source_lang": source_lang, "target_lang": lang.upper()})
            except Exception as e:
                if "invalid destination language" in str(e).lower():
                    raise ValueError(f"'{lang}' nomli til kodi topilmadi.") from e
                raise IOError(f"Google Translate xatosi: {e}") from e
        return results

# --- BUYRUQLAR HANDLERLARI ---

@userbot_cmd(command=["tr", "translate", "trai"], description="Matnni Google yoki AI yordamida tarjima qiladi.")
async def translate_command_handler(event: Message, context: AppContext):
    if not event.text or not event.client:
        return

    account_id = await get_account_id(context, event.client)
    if not account_id:
        return await event.edit(format_error("Akkauntni aniqlab bo'lmadi."), parse_mode='html')

    args_str = event.text.split(maxsplit=1)[1] if len(event.text.split()) > 1 else ""
    target_langs, text_from_args = _parse_tr_args(shlex.split(args_str))
    
    text_to_translate = text_from_args
    if not text_to_translate:
        if replied := await event.get_reply_message():
            text_to_translate = replied.text
    if not text_to_translate:
        return await event.edit(format_error("Tarjima uchun matn kiriting yoki matnli xabarga javob bering."), parse_mode='html')

    if not target_langs:
        # YECHIM: `await` olib tashlandi, chunki `get` sinxron
        default_lang_setting = context.state.get(f"translate_default_{account_id}")
        target_langs = [default_lang_setting or 'uz']

    command = event.text.split()[0].strip('.')
    use_ai = command == 'trai'
    provider_name = "Gemini AI" if use_ai else "Google"
    
    await event.edit(f"<i>🔄 '{provider_name}' orqali tarjima qilinmoqda...</i>", parse_mode='html')

    try:
        translations = await _translate(context, text_to_translate, target_langs, use_ai)
        if not translations:
            raise ValueError("Tarjima natijasi bo'sh.")

        response_parts = []
        source_lang_detected = translations[0].get("source_lang", "auto")
        flag_from = FLAG_EMOJIS.get(source_lang_detected, "🏳️")
        target_langs_str = ', '.join(t['target_lang'] for t in translations)
        response_parts.append(f"<b>{flag_from} {source_lang_detected} → {target_langs_str}</b>\n")

        for res in translations:
            flag_to = FLAG_EMOJIS.get(res['target_lang'], "🏳️")
            response_parts.append(f"\n{flag_to} <b>{res['target_lang']}:</b><blockquote>{html.escape(res['text'])}</blockquote>")
            await _log_translate_usage(context, account_id, provider_name, source_lang_detected, res['target_lang'])

        await event.edit("".join(response_parts), link_preview=False, parse_mode='html')
    except Exception as e:
        logger.exception(f"Tarjima bajarishda xatolik: {e}")
        await event.edit(format_error(f"Tarjima xatosi ({provider_name}):\n<code>{html.escape(str(e))}</code>"), parse_mode='html')

@userbot_cmd(command="trset", description="Standart tarjima tilini o'rnatadi.")
async def set_default_lang_handler(event: Message, context: AppContext):
    if not event.text or not event.client: return
    account_id = await get_account_id(context, event.client)
    if not account_id: return await event.edit(format_error("Akkauntni aniqlab bo'lmadi."), parse_mode='html')

    lang_code = event.text.split(maxsplit=1)[1].strip().lower() if len(event.text.split()) > 1 else ""
    if not lang_code:
        return await event.edit(format_error("Til kodini kiriting. Masalan: <code>.trset en</code>"), parse_mode='html')

    if GOOGLE_LANGUAGES and lang_code not in GOOGLE_LANGUAGES:
        return await event.edit(format_error(f"Noto'g'ri til kodi: `{lang_code}`"), parse_mode='html')

    await context.state.set(f"translate_default_{account_id}", lang_code, persistent=True)
    await event.edit(format_success(f"Standart tarjima tili <b>{lang_code.upper()}</b>'ga o'zgartirildi."), parse_mode='html')

@userbot_cmd(command="trstats", description="Tarjimalar statistikasini ko'rsatadi.")
async def translate_stats_handler(event: Message, context: AppContext):
    if not event.client: return
    account_id = await get_account_id(context, event.client)
    if not account_id: return await event.edit(format_error("Akkauntni aniqlab bo'lmadi."), parse_mode='html')

    total = await context.db.fetch_val("SELECT COUNT(id) FROM translation_stats WHERE account_id = ?", (account_id,)) or 0
    if not total:
        return await event.edit("<b>📊 Statistika bo'sh.</b>", parse_mode='html')

    lines = [f"📊 <b>Tarjimon Statistikasi (Jami: {total})</b>"]
    
    top_langs = await context.db.fetchall(
        "SELECT target_lang, COUNT(id) as c FROM translation_stats WHERE account_id = ? GROUP BY target_lang ORDER BY c DESC LIMIT 5",
        (account_id,)
    )
    if top_langs:
        lines.append("\n<b>🔝 Top 5 Tillar:</b>")
        lines.extend(f"  • {row['target_lang']}: {row['c']} marta" for row in top_langs)

    await event.edit("\n".join(lines), parse_mode='html')
