# bot/lib/auth.py
"""
Foydalanuvchi huquqlarini tekshirish (authentication) va ruxsatlarni
boshqarish (authorization) uchun yordamchi funksiyalar va dekoratorlar.
"""

import asyncio
from functools import wraps
from typing import Any, Callable, Coroutine, Set, TypeVar, cast

from loguru import logger
from telethon.tl.custom import Message

from core.app_context import AppContext
from bot.lib.ui import (
    _safe_edit_message,
    ERROR_ADMIN_ONLY,
    ERROR_OWNER_ONLY,
    ERROR_SUDO_REQUIRED,
)
from bot.lib.telegram import retry_telegram_api_call

# ----- SODDALASHTIRILGAN TIP ANOTATSIYALARI -----
F = TypeVar("F", bound=Callable[..., Coroutine[Any, Any, Any]])

# ----- HUQUQLARNI ANIQLASH FUNKSIYALARI -----

async def get_all_admin_ids(context: AppContext) -> Set[int]:
    """
    Barcha adminlarning (konfiguratsiya va bazadagi) ID raqamlari to'plamini qaytaradi.
    Natija 10 daqiqaga keshlanadi.
    """
    cache_key = "auth:admin_ids"
    if cached_ids := await context.cache.get(cache_key):
        if isinstance(cached_ids, set):
            return cached_ids

    db_admins_rows = await context.db.fetchall("SELECT user_id FROM admins")
    db_admins = {row["user_id"] for row in db_admins_rows}

    config_admins = set(context.config.get("ADMIN_IDS", []))
    all_admin_ids = db_admins.union(config_admins)

    if owner_id := context.config.get("OWNER_ID"):
        all_admin_ids.add(owner_id)

    await context.cache.set(cache_key, all_admin_ids, ttl=600)
    logger.debug(f"Admin kesh yangilandi. Jami adminlar: {len(all_admin_ids)}")
    return all_admin_ids


async def invalidate_admin_cache(context: AppContext) -> None:
    """Adminlar ro'yxati keshini majburan tozalaydi."""
    await context.cache.delete("auth:admin_ids")
    logger.info("Admin kesh tozalandi.")


# ----- RUXSATNI TEKSHIRUVCHI DEKORATORLAR -----

async def _handle_permission_denied(event: Message, error_message: str) -> None:
    """Ruxsat rad etilganida xabarni ko'rsatib, 3 soniyadan so'ng o'chiradi."""
    await _safe_edit_message(event, error_message)
    await asyncio.sleep(3)
    await retry_telegram_api_call(event.delete)


def owner_only(func: F) -> F:
    """Dekorator: Funksiyani faqat bot egasi ishlata olishini ta'minlaydi."""
    @wraps(func)
    async def wrapper(event: Message, context: AppContext, *args: Any, **kwargs: Any) -> Any:
        sender_id = getattr(event, "sender_id", None)
        if not sender_id or sender_id != context.config.get("OWNER_ID"):
            logger.warning(f"Ega buyrug'iga ruxsatsiz urinish: ID={sender_id}")
            await _handle_permission_denied(event, ERROR_OWNER_ONLY)
            return None
        return await func(event, context, *args, **kwargs)
    return cast(F, wrapper)


def admin_only(func: F) -> F:
    """Dekorator: Funksiyani adminlar (va ega) ishlata olishini ta'minlaydi."""
    @wraps(func)
    async def wrapper(event: Message, context: AppContext, *args: Any, **kwargs: Any) -> Any:
        sender_id = getattr(event, "sender_id", None)
        if not sender_id:
            return None
        admin_ids = await get_all_admin_ids(context)
        if sender_id not in admin_ids:
            logger.warning(f"Admin buyrug'iga ruxsatsiz urinish: ID={sender_id}")
            await _handle_permission_denied(event, ERROR_ADMIN_ONLY)
            return None
        return await func(event, context, *args, **kwargs)
    return cast(F, wrapper)


def sudo_required(func: F) -> F:
    """Dekorator: Xavfli buyruqlar uchun `.sudo` rejimi yoqilganini tekshiradi."""
    @wraps(func)
    async def wrapper(event: Message, context: AppContext, *args: Any, **kwargs: Any) -> Any:
        sender_id = getattr(event, "sender_id", None)
        command_meta = getattr(event, "command_meta", {})
        command_name = command_meta.get("name")
        dangerous_commands = context.config.get("DANGEROUS_COMMANDS", [])
        if command_name in dangerous_commands:
            sudo_key = f"sudo_mode:{sender_id}"
            if not await context.cache.get(sudo_key):
                logger.warning(f"'{command_name}' uchun sudo rejimi talab qilindi. (ID={sender_id})")
                await _safe_edit_message(event, ERROR_SUDO_REQUIRED.format(command=command_name))
                return None
        return await func(event, context, *args, **kwargs)
    return cast(F, wrapper)


async def get_user_permission_level(context: AppContext, user_id: int) -> int:
    """Foydalanuvchining ruxsat darajasini aniqlaydi."""
    if user_id == context.config.get("OWNER_ID"):
        return 100
    if user_id in context.config.get("ADMIN_IDS", []):
        return 95 # .env faylidagi adminlar uchun

    db_admin = await context.db.fetchone(
        "SELECT permission_level FROM admins WHERE user_id = ?", (user_id,)
    )
    if db_admin:
        return db_admin.get("permission_level", 50) # Standart DB admin darajasi

    return 0 # Oddiy foydalanuvchi