"""
Plaginlarda ishlatiladigan, qayta ishlatiluvchi maxsus dekoratorlar to'plami.
"""

import time
import asyncio
from functools import wraps
from typing import Callable, Coroutine, Any, TypeVar, cast

from loguru import logger
from telethon.tl.custom import Message

from core.app_context import AppContext

from bot.lib.ui import _safe_edit_message, MESSAGE_RATE_LIMITED

from typing import Dict

_last_calls_local: Dict[str, float] = {}


CallableT = TypeVar("CallableT", bound=Callable[..., Coroutine[Any, Any, Any]])


def rate_limit(seconds: int, name: str = "") -> Callable[[CallableT], CallableT]:
    """
    Buyruqni belgilangan vaqt ichida faqat bir marta ishlatish imkonini beradi.
    Agar `name` berilsa, bir nechta funksiya bitta cheklovdan foydalanishi mumkin.
    """

    def decorator(func: CallableT) -> CallableT:
        @wraps(func)
        async def wrapper(event: Message, context: AppContext, *args: Any, **kwargs: Any) -> Any:
            if not event.sender_id:
                return None

            func_name = name or func.__name__
            cache_key = f"rate_limit:{func_name}:{event.sender_id}"

            if last_call := await context.cache.get(cache_key):
                remaining = seconds - (time.monotonic() - float(last_call))
                if remaining > 0:
                    logger.debug(f"Rate limit faol: {event.sender_id} - {func_name}. Qoldi: {remaining:.2f}s.")

                    warn_msg = MESSAGE_RATE_LIMITED.format(remaining=remaining)
                    await _safe_edit_message(event, warn_msg)

                    await asyncio.sleep(2)

                    original_text = event.text or ""
                    await _safe_edit_message(event, original_text)
                    return None

            await context.cache.set(cache_key, time.monotonic(), ttl=seconds)
            return await func(event, context, *args, **kwargs)

        return cast(CallableT, wrapper)

    return decorator



from typing import List, Union

def register_command(
    command: Union[str, List[str]],
    category: str = "other",
    description: str = "Tavsif berilmagan.",
    usage: str = "",
) -> Callable[[CallableT], CallableT]:
    """
    Plagin buyruqlarini yordam menyusi va boshqaruv uchun ro'yxatdan o'tkazadi.

    Args:
        command: Buyruqning bir yoki bir nechta nomi (masalan, "ping" yoki ["p", "ping"]).
        category: Buyruq tegishli bo'lgan kategoriya (masalan, "tools", "profile").
        description: Buyruqning yordam menyusida ko'rinadigan tavsifi.
        usage: Buyruqdan qanday foydalanish haqida qisqa yo'riqnoma.
    """

    def decorator(func: CallableT) -> CallableT:
        commands = [command] if isinstance(command, str) else command
        # Buyruq metadatasini funksiyaning o'ziga atribut sifatida biriktiramiz.
        # Plagin yuklovchi (loader) keyinchalik shu metadatani o'qib oladi.
        meta = {
            "commands": [cmd.lower() for cmd in commands],
            "category": category.lower(),
            "description": description,
            "usage": usage,
            "handler": func,
            "module": func.__module__,
        }
        setattr(func, "_command_meta", meta)

        @wraps(func)
        async def wrapper(*args: Any, **kwargs: Any) -> Any:
            return await func(*args, **kwargs)

        return cast(CallableT, wrapper)

    return decorator