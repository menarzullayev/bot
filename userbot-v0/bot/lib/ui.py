import asyncio
import html
import io
import re
import uuid
import json
from contextlib import asynccontextmanager, suppress
from typing import Any, Dict, List, Optional, Union

from loguru import logger
from telethon.tl.custom import Message

from core.app_context import AppContext

from bot.lib.telegram import edit_message, retry_telegram_api_call
from bot.lib.utils import run_in_background


ERROR_ADMIN_ONLY = "<b>🚫 Bu buyruqdan faqat adminlar foydalana oladi.</b>"
ERROR_OWNER_ONLY = "<b>🚫 Bu buyruqdan faqat bot egasi foydlana oladi.</b>"
ERROR_SUDO_REQUIRED = ("<b>🛡️ Bu xavfli buyruq. Davom etish uchun avval "
                       "<code>.sudo</code> buyrug'i bilan rejimni yoqing.</b>")
MESSAGE_RATE_LIMITED = "⏳ <b>Tez-tez murojaat!</b> Iltimos, <code>{remaining:.1f}</code> soniya kuting."


def bold(text: Any) -> str:
    return f"<b>{html.escape(str(text))}</b>"


def italic(text: Any) -> str:
    return f"<i>{html.escape(str(text))}</i>"


def code(text: Any) -> str:
    return f"<code>{html.escape(str(text))}</code>"


def pre(text: Any) -> str:
    return f"<pre>{html.escape(str(text))}</pre>"


def link(text: Any, url: str) -> str:
    return f'<a href="{html.escape(url)}">{html.escape(str(text))}</a>'


def format_success(text: str) -> str:
    return f"✅ <b>Muvaffaqiyatli:</b>\n{text}"


def format_error(text: str) -> str:
    return f"❌ <b>Xatolik:</b>\n{text}"


def format_as_table(headers: List[str], rows: List[List[Any]]) -> str:
    if not rows:
        return "<i>(Natija bo'sh)</i>"
    col_widths = [max(len(str(h)), *(len(str(row[i])) for row in rows)) for i, h in enumerate(headers)]
    header_line = " | ".join(str(h).ljust(w) for h, w in zip(headers, col_widths))
    separator = "-+-".join("-" * w for w in col_widths)
    body_lines = [" | ".join(str(c).ljust(w) for c, w in zip(row, col_widths)) for row in rows]
    return f"<pre>{header_line}\n{separator}\n" + "\n".join(body_lines) + "</pre>"


async def _safe_edit_message(message: Message, text: str, **kwargs: Any) -> bool:
    """Xabarni xavfsiz tahrirlaydi, mavjud bo'lmasa yoki o'zgarmasa, xatolik bermaydi."""

    if not text or not hasattr(message, "client") or not message.client:
        return False
    try:
        kwargs.setdefault("parse_mode", "html")
        kwargs.setdefault("link_preview", False)

        await retry_telegram_api_call(
            message.client.edit_message,
            entity=message.peer_id,
            message=message.id,
            text=text,
            **kwargs,
        )
        return True
    except Exception as e:

        logger.debug(f"Xabarni tahrirlashda kutilgan xato: {e}")
        return False


async def request_confirmation(
    event: Message,
    context: AppContext,
    action_text: str,
    command: str,
    data: Optional[Dict[str, Any]] = None,
    timeout: int = 20, 
) -> bool:
    """Xavfli amallarni interaktiv tasdiqlashni so'raydi (to'g'rilangan versiya)."""
    if not (event.client and event.chat_id and event.sender_id):
        logger.error("Tasdiqlash so'rovi uchun ob'ektlar yetishmayapti.")
        return False

    confirm_code = str(uuid.uuid4().hex[:6])
    cache_key = f"confirm:{event.sender_id}:{command}"

    await context.state.set(cache_key, {"code": confirm_code, "data": data or {}}, ttl_seconds=timeout, persistent=False)

    prompt_text = (f"⚠️ <b>DIQQAT!</b> Siz '<code>{html.escape(action_text)}</code>' amalini bajaryapsiz.\n"
                   f"✅ Davom etish uchun <b>{timeout} soniya ichida</b> quyidagi buyruqni yuboring:\n"
                   f"<code>.{command} {confirm_code}</code>")

    # Eskisini tahrirlash o'rniga, yangi xabar yuborib, keyin o'chiramiz
    prompt_message = None
    try:
        async with event.client.conversation(event.chat_id, timeout=timeout) as conv:
            # YECHIM: Suhbat ichidan yangi xabar yuboramiz
            prompt_message = await conv.send_message(prompt_text, parse_mode='html')

            # Endi javobni kutamiz
            response = await conv.get_response()

            if response and response.sender_id == event.sender_id and response.text and response.text.strip() == f".{command} {confirm_code}":
                await context.state.delete(cache_key)
                await retry_telegram_api_call(response.delete)
                # Eski buyruq va tasdiq so'rovini ham o'chiramiz
                await retry_telegram_api_call(event.delete)
                await retry_telegram_api_call(prompt_message.delete)
                return True
            else:
                await context.state.delete(cache_key)
                # Agar noto'g'ri javob kelgan bo'lsa, uni o'chiramiz
                if response:
                    await retry_telegram_api_call(response.delete)
                await _safe_edit_message(event, "❌ <i>Noto'g'ri tasdiqlash kodi. Amal bekor qilindi.</i>")
                return False
    except asyncio.TimeoutError:
        if context.state.get(cache_key):
            await _safe_edit_message(event, "⏳ <i>Vaqt tugadi. Amal avtomatik bekor qilindi.</i>")
        await context.state.delete(cache_key)
        return False
    except Exception as e:
        logger.error(f"Tasdiqlash so'rovida kutilmagan xato: {e}", exc_info=True)
        await context.state.delete(cache_key)
        await _safe_edit_message(event, f"<b>❌ Tasdiqlashda xato yuz berdi:</b> <code>{html.escape(str(e))}</code>")
        return False
    finally:
        # Har qanday holatda ham tasdiq so'rovini o'chirib tashlaymiz
        if prompt_message:
            with suppress(Exception):
                await retry_telegram_api_call(prompt_message.delete)


async def _animation_cycle(message: Message, base_text: str, frames: List[str], delay: float):
    try:
        while True:
            for frame in frames:
                # Xavfsizlik: Har bir kadrda xabar hali ham mavjudligini tekshiramiz
                if not await retry_telegram_api_call(message.get_chat):
                    logger.debug(f"Animatsiya to'xtatildi: Xabar yoki chat o'chirilgan ({message.id}).")
                    return

                new_text = f"<code>{html.escape(base_text)} {frame}</code>"

                # Xavfsizlik: Xabarni tahrirlab bo'lmasa, animatsiyani to'xtatamiz
                if not await _safe_edit_message(message, new_text):
                    logger.debug(f"Animatsiya to'xtatildi: Xabarni tahrirlab bo'lmadi ({message.id}).")
                    return

                await asyncio.sleep(delay)
    except asyncio.CancelledError:
        raise
    except Exception as e:
        logger.error(f"Animatsiya tsiklida kutilmagan xato (message_id: {message.id}): {e}")
        
async def animate_message(message: Message, base_text: str, frames: Optional[List[str]] = None, delay: float = 0.2) -> Optional[asyncio.Task]:
    """
    Xabarni chiroyli kadrlar bilan tahrirlab, animatsiya yaratadi.
    Tugatish uchun qaytarilgan Task obyektini .cancel() qilish kerak.
    """
    if not message:
        return None


    # Dasturchi uchun tanlov: keraklisini kommentdan chiqaring
    # effective_frames = frames or ["", ".", "..", "..."] # Nuqtali uslub
    effective_frames = frames or ["⠋", "⠙", "⠹", "⠸", "⠼", "⠴", "⠦", "⠧", "⠇", "⠏"]  # Aylanma uslub (standart)

    # Use an async feature directly to satisfy the linter
    await asyncio.sleep(0)

    return run_in_background(_animation_cycle(message, base_text, effective_frames, delay))


async def send_as_file_if_long(event: Message, text: str, *, filename: str = "output.txt", caption: str = "", max_len: int = 4096, **kwargs: Any) -> Optional[Message]:
    """
    Agar matn `max_len` dan uzun bo'lsa, uni fayl sifatida yuboradi, aks holda xabarni tahrirlaydi.
    Endi `parse_mode` kabi qo'shimcha argumentlarni ham qabul qiladi.
    """
    if not text or not event or not event.client:
        logger.warning("send_as_file_if_long: Matn yoki event/client obyekti bo'sh.")
        return None

    try:
        # Standart `parse_mode` ni 'html' qilib belgilaymiz, agar boshqasi berilmagan bo'lsa
        kwargs.setdefault("parse_mode", "html")

        if len(text) <= max_len:
            logger.debug(f"Matn uzunligi {len(text)}, xabar sifatida tahrirlanmoqda.")
            await _safe_edit_message(event, text, **kwargs)
            return event

        logger.info(f"Matn juda katta ({len(text)} belgi), fayl sifatida yuborilmoqda.")
        await _safe_edit_message(event, "<code>⏳ Natija juda katta, fayl sifatida yuborilmoqda...</code>")

        plain_text = re.sub(r'<[^>]+>', '', text)
        with io.BytesIO(plain_text.encode('utf-8')) as file_stream:
            file_stream.name = filename
            final_caption = caption or f"Natija '<code>{html.escape(filename)}</code>' faylida."

            sent_message = await retry_telegram_api_call(event.client.send_file, event.peer_id, file=file_stream, caption=final_caption, reply_to=event.id, **kwargs)  # Qo'shimcha parametrlarni (masalan, parse_mode) bu yerga uzatamiz

        await retry_telegram_api_call(event.delete)
        return sent_message

    except Exception as e:
        logger.error(f"send_as_file_if_long ichida xatolik: {e}", exc_info=True)
        try:
            return await retry_telegram_api_call(event.client.send_message, event.peer_id, "<b>❌ Xabarni qayta ishlashda xatolik yuz berdi.</b>", reply_to=event.id, parse_mode='html')
        except Exception as final_e:
            logger.critical(f"send_as_file_if_long yakuniy xato: {final_e}")
            return None


class PaginationHelper:
    """
    Katta hajmdagi ma'lumotlarni sahifalarga bo'lib, interaktiv boshqarish imkonini beruvchi klass.
    Endi sessiyani keshda xavfsiz lug'at (dict) ko'rinishida saqlaydi.
    """

    def __init__(self, context: AppContext, **kwargs):
        self.context = context
        # Keshdan tiklash uchun kerakli maydonlar
        self.items: List[str] = kwargs.get("items", [])
        self.title: str = kwargs.get("title", "")
        self.page_size: int = kwargs.get("page_size", 20)
        self.current_page: int = kwargs.get("current_page", 1)
        self.origin_event_id: int = kwargs.get("origin_event_id", 0)
        self.chat_id: int = kwargs.get("chat_id", 0)
        self.origin_sender_id: int = kwargs.get("origin_sender_id", 0)

        # Original eventdan birinchi marta yaratilganda
        origin_event: Optional[Message] = kwargs.get("origin_event")
        if origin_event:
            self.items = kwargs.get("items", [])
            self.title = kwargs.get("title", "")
            self.page_size = kwargs.get("page_size", 10)
            self.origin_event_id = origin_event.id
            self.chat_id = origin_event.chat_id
            self.origin_sender_id = origin_event.sender_id

        self.total_pages = max(1, (len(self.items) + self.page_size - 1) // self.page_size)
        self._cache_key = f"pagination:{self.chat_id}:{self.origin_event_id}"

    def to_dict(self) -> dict:
        """Keshda saqlash uchun obyekt holatini lug'atga o'tkazadi."""
        return {
            "items": self.items,
            "title": self.title,
            "page_size": self.page_size,
            "current_page": self.current_page,
            "origin_event_id": self.origin_event_id,
            "chat_id": self.chat_id,
            "origin_sender_id": self.origin_sender_id,
        }

    async def save_to_cache(self, ttl_seconds: int = 60):
        """Joriy holatni AppState orqali keshlaydi."""
        logger.debug(f"[PAGINATION_STATE_SAVE] Sessiya holatga saqlanmoqda. Kalit: '{self._cache_key}', TTL: {ttl_seconds}s")
        # AppState to'g'ridan-to'g'ri lug'at saqlay oladi, JSON konvertatsiya shart emas.
        await self.context.state.set(self._cache_key, self.to_dict(), ttl_seconds=ttl_seconds, persistent=False)

    def get_page_text(self, page_num: int) -> str:
        """Belgilangan sahifa uchun matnni formatlaydi (kengaytirilgan va chiroyli footer bilan)."""
        self.current_page = max(1, min(page_num, self.total_pages))
        start_index = (self.current_page - 1) * self.page_size
        end_index = start_index + self.page_size
        page_items = self.items[start_index:end_index]
        content = "\n".join(page_items) if page_items else "<i>(bo'sh)</i>"

        text = f"{self.title}\n\n{content}"

        # --- FOOTER QISMINI QAYTA YIG'ISH ---

        # 1. Ma'lumot qismi
        showing_str = f"({start_index + 1}-{min(end_index, len(self.items))} / {len(self.items)})"
        footer_info = f"<b>Sahifa:</b> {self.current_page}/{self.total_pages} {showing_str}"

        # 2. Buyruqlar qismi
        nav_cmds = []
        if self.current_page > 1:
            nav_cmds.extend(["<code>.first</code>", "<code>.prev</code>"])
        if self.current_page < self.total_pages:
            nav_cmds.extend(["<code>.next</code>", "<code>.last</code>"])
        nav_cmds.extend(["<code>.goto N</code>", "<code>.endp</code>"])
        footer_cmds = f"<b>Boshqaruv:</b> {' '.join(nav_cmds)}"

        # 3. Chiroyli ajratuvchi chiziq
        separator = "—" * 20

        # 4. Barcha qismlarni birlashtirish
        return f"{text}\n\n{separator}\n{footer_info}\n{footer_cmds}"

    async def start(self) -> bool:
        """Paginatsiyani boshlaydi va birinchi sahifani yuboradi."""
        if not (self.context and self.origin_event_id and self.chat_id):
            logger.error("PaginationHelper.start: Kontekst yoki original event ma'lumotlari yetishmayapti.")
            return False

        await self.save_to_cache()

        try:
            active_clients = self.context.client_manager.get_all_clients()
            if not active_clients:
                logger.error("PaginationHelper.start: Hech qanday faol klient topilmadi.")
                return False
            client = active_clients[0]

            messages = await retry_telegram_api_call(client.get_messages, self.chat_id, ids=self.origin_event_id)
            if not messages:
                logger.warning(f"Paginatsiya uchun original xabar topilmadi: chat={self.chat_id}, id={self.origin_event_id}")
                return False

            origin_event = messages[0] if isinstance(messages, list) else messages
            return await _safe_edit_message(origin_event, self.get_page_text(1), parse_mode='html')
        except Exception as e:
            logger.error(f"Paginatsiyani boshlashda kutilmagan xato: {e}", exc_info=True)
            return False

    @classmethod
    async def get_from_cache(cls, context: AppContext, message: Message) -> Optional['PaginationHelper']:
        """AppState'dan paginatsiya sessiyasini oladi va obyekt sifatida qaytaradi."""
        if not (message and message.chat_id and message.id):
            return None

        cache_key = f"pagination:{message.chat_id}:{message.id}"
        logger.debug(f"[PAGINATION_STATE_GET] Sessiya holatdan qidirilmoqda. Kalit: '{cache_key}'")

        session_data = context.state.get(cache_key)

        if session_data and isinstance(session_data, dict):
            logger.debug("[PAGINATION_STATE_GET] Sessiya holatdan topildi.")
            return cls(context=context, **session_data)

        logger.warning(f"[PAGINATION_STATE_GET] Sessiya holatdan topilmadi! Kalit: '{cache_key}'")
        return None

    async def end(self, message: Message):
        """Paginatsiya sessiyasini tugatadi, holatdan o'chiradi va xabarni tahrirlaydi."""
        logger.debug(f"[PAGINATION_END] Sessiya yakunlanmoqda. Kalit: '{self._cache_key}'")
        await self.context.state.delete(self._cache_key)

        clean_title = re.sub(r'<[^>]+>', '', self.title).strip()
        final_text = f"✅ Paginatsiya sessiyasi (<b>{html.escape(clean_title)}</b>) yakunlandi."
        await _safe_edit_message(message, final_text, parse_mode='html', buttons=None)


@asynccontextmanager
async def managed_animation(message: Message, text: str):
    """
    Animatsiyani boshqarish uchun qulay kontekst menejeri.
    `async with` bloki tugashi bilan animatsiya avtomatik to'xtaydi.

    Misol:
    async with managed_animation(event, "Ishlanmoqda"):
        await asyncio.sleep(5)
    """
    task = await animate_message(message, text)
    try:
        yield
    finally:
        if task:
            task.cancel()
            # Kichik pauza, xabar "to'xtatildi" degan statusga o'zgarguncha
            with suppress(asyncio.CancelledError):
                await asyncio.sleep(0.1)
