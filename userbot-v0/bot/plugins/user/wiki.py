# bot/plugins/user/wiki.py
"""
Vikipediya, Vikilug'at va boshqa bilim manbalari bilan ishlash uchun plagin.
AI yordamida xulosalash imkoniyatiga ega (To'liq modernizatsiya qilingan).
"""

import asyncio
import html
import re
import shlex
from typing import Optional, List, Tuple

try:
    import wikipedia
    from wiktionaryparser import WiktionaryParser
    import aiohttp
    from bs4 import BeautifulSoup, Tag
    LIBS_AVAILABLE = True
except ImportError:
    wikipedia = WiktionaryParser = aiohttp = BeautifulSoup = Tag = None
    LIBS_AVAILABLE = False

from loguru import logger
from telethon.tl.custom import Message

from core.app_context import AppContext
from bot.decorators import userbot_cmd
from bot.lib.telegram import get_account_id
from bot.lib.ui import format_error, send_as_file_if_long, PaginationHelper, format_success
from bot.lib.utils import RaiseArgumentParser

# --- Yordamchi Funksiyalar ---

async def _log_wiki_usage(context: AppContext, account_id: int, command: str, query: Optional[str] = None):
    """Buyruqdan foydalanish statistikasini bazaga yozadi."""
    try:
        await context.db.execute(
            "INSERT OR IGNORE INTO wiki_stats (account_id, command, query) VALUES (?, ?, ?)",
            (account_id, command, query),
        )
    except Exception as e:
        logger.warning(f"Wiki statistikasini yozishda xato: {e}")

def _clean_text(text: str) -> str:
    """Maqola matnini keraksiz qismlardan tozalaydi."""
    text = html.unescape(text).strip()
    text = re.sub(r'\[\d+\]', '', text)
    text = re.sub(r'==\s*(Manbalar|Adabiyotlar|Yana qarang|Havolalar|References|See also)\s*==.*', '', text, flags=re.DOTALL | re.IGNORECASE)
    return text.strip()

# ===== Asosiy Buyruqlar =====

@userbot_cmd(command="wiki", description="Vikipediyadan maqola qidiradi.")
async def wiki_search(event: Message, context: AppContext):
    """
    .wiki Toshkent
    .wiki O'zbekiston --lang en
    .wiki Albert Einstein -s
    """
    if not wikipedia:
        return await event.edit(format_error("`wikipedia` kutubxonasi o'rnatilmagan."), parse_mode='html')
    if not (event.client and event.text): return
    
    account_id = await get_account_id(context, event.client)
    if not account_id: return await event.edit(format_error("Akkauntni aniqlab bo'lmadi."), parse_mode='html')

    args_str = event.text.split(maxsplit=1)[1] if len(event.text.split()) > 1 else ""
    parser = RaiseArgumentParser(prog=".wiki", description="Vikipediya qidiruvi")
    parser.add_argument('-s', '--summarize', action='store_true', help="Natijani AI bilan xulosalash")
    parser.add_argument('--lang', type=str, help="Qidiruv tili (masalan, en, ru)")
    parser.add_argument('query', nargs='*', help="Qidiruv so'rovi")

    try:
        args = parser.parse_args(shlex.split(args_str))
        args.query = " ".join(args.query).strip()
        if not args.query:
            return await event.edit(format_error("Qidirish uchun so'z kiriting."), parse_mode='html')
    except (ValueError, SystemExit) as e:
        return await event.edit(format_error(f"Argument xatosi: {e}"), parse_mode='html')

    lang_code = args.lang or (context.state.get(f"wiki_default_lang_{account_id}") or 'uz')
    await event.edit(f"<i>🔄 '{html.escape(args.query)}' qidirilmoqda ({lang_code.upper()})...</i>", parse_mode='html')

    try:
        await asyncio.to_thread(wikipedia.set_lang, lang_code)
        page = await asyncio.to_thread(wikipedia.page, args.query, auto_suggest=True, redirect=True)
        await _log_wiki_usage(context, account_id, "wiki", args.query)

        if args.summarize:
            if not context.ai_service.is_configured:
                return await event.edit(format_error("AI xizmati sozlanmagan."), parse_mode='html')
            await event.edit(f"<i>🤖 AI xulosasi tayyorlanmoqda...</i>", parse_mode='html')
            prompt = f"Quyidagi Vikipediya maqolasini muhim faktlarni ajratib, o'zbek tilida qisqa va tushunarli xulosala:\n\n---\n{page.summary}\n---"
            ai_result = await context.ai_service.generate_text(prompt)
            response = f"<b>🤖 AI Xulosasi ({html.escape(page.title)}):</b>\n\n{html.escape(ai_result.get('text', ''))}\n\n<b>Asl manba:</b> {page.url}"
        else:
            response = f"<b>📖 {html.escape(page.title)}</b>\n\n{html.escape(_clean_text(page.summary))}\n\n<b>Batafsil:</b> {page.url}"

        await send_as_file_if_long(event, response, filename=f"wiki_{page.title}.txt", parse_mode='html')

    except wikipedia.exceptions.PageError:
        suggestions = await asyncio.to_thread(wikipedia.search, args.query, results=5)
        if suggestions:
            s_text = "\n".join([f"▫️ <code>.wiki {s}</code>" for s in suggestions])
            await event.edit(f"<b>🤔 Aniq maqola topilmadi.</b>\nQuyidagilarni sinab ko'ring:\n{s_text}", parse_mode='html')
        else:
            await event.edit(format_error(f"'{args.query}' bo'yicha hech narsa topilmadi."), parse_mode='html')
    except wikipedia.exceptions.DisambiguationError as e:
        opts = "\n".join([f"▫️ <code>.wiki {o}</code>" for o in e.options[:5]])
        await event.edit(f"<b>❓ So'rov bir nechta maqolaga ishora qilmoqda:</b>\n{opts}", parse_mode='html')
    except Exception as e:
        logger.exception(f"Wiki qidiruvida xato: {e}")
        await event.edit(format_error(f"Kutilmagan xatolik: {e}"), parse_mode='html')

@userbot_cmd(command="etymology", description="So'zning etimologiyasini (kelib chiqishini) topadi.")
async def etymology_command(event: Message, context: AppContext):
    if not WiktionaryParser:
        return await event.edit(format_error("`WiktionaryParser` kutubxonasi o'rnatilmagan."), parse_mode='html')
    if not event.text or not event.client: return
    
    query = event.text.split(maxsplit=1)[1] if len(event.text.split()) > 1 else ""
    if not query:
        return await event.edit(format_error("Etimologiyasini bilish uchun so'z kiriting."), parse_mode='html')

    await event.edit(f"<i>🔄 '{html.escape(query)}' so'zining kelib chiqishi qidirilmoqda...</i>", parse_mode='html')
    try:
        result = await asyncio.to_thread(WiktionaryParser().fetch, query)
        if not result or not result[0].get('etymology'):
            raise ValueError(f"'{html.escape(query)}' so'zi uchun etimologiya topilmadi.")

        etymology_text = result[0]['etymology']
        response = f"<b>📜 '{html.escape(query)}' so'zining etimologiyasi:</b>\n\n{html.escape(etymology_text)}"
        await event.edit(response, parse_mode='html')

        if acc_id := await get_account_id(context, event.client):
            await _log_wiki_usage(context, acc_id, "etymology", query)
    except Exception as e:
        await event.edit(format_error(f"Ma'lumot topilmadi yoki xatolik: {e}"), parse_mode='html')

# --- Sozlamalar va Statistika ---

@userbot_cmd(command="wikiset", description="Standart Vikipediya tilini o'rnatadi.")
async def wikiset_lang(event: Message, context: AppContext):
    if not wikipedia: return await event.edit(format_error("`wikipedia` kutubxonasi o'rnatilmagan."), parse_mode='html')
    if not (event.text and event.client): return
    account_id = await get_account_id(context, event.client)
    if not account_id: return

    lang_code = event.text.split(maxsplit=1)[1].lower() if len(event.text.split()) > 1 else ""
    if not lang_code:
        return await event.edit(format_error("Til kodini kiriting. Masalan: .wikiset en"), parse_mode='html')

    all_langs = await asyncio.to_thread(wikipedia.languages)
    if lang_code not in all_langs:
        return await event.edit(format_error(f"Noto'g'ri til kodi: <code>{lang_code}</code>"), parse_mode='html')

    await context.state.set(f"wiki_default_lang_{account_id}", lang_code, persistent=True)
    await event.edit(format_success(f"Standart Vikipediya tili <b>{lang_code.upper()}</b>'ga o'zgartirildi."), parse_mode='html')

@userbot_cmd(command="wikilangs", description="Mavjud Vikipediya tillari ro'yxatini ko'rsatadi.")
async def wikilangs_handler(event: Message, context: AppContext):
    if not wikipedia: return await event.edit(format_error("`wikipedia` kutubxonasi o'rnatilmagan."), parse_mode='html')
    await event.edit("<code>🔄 Tillari ro'yxati olinmoqda...</code>", parse_mode='html')
    
    langs = await asyncio.to_thread(wikipedia.languages)
    lines = [f"<code>{code}</code> - {name}" for code, name in sorted(langs.items())]
    
    pagination = PaginationHelper(context=context, items=lines, title="🌐 Vikipediya Tillari", origin_event=event, page_size=20)
    await pagination.start()
