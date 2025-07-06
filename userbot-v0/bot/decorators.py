import re
from functools import wraps
from typing import Any, Callable, Coroutine, Optional, Pattern, TypeVar, ParamSpec, List, Dict


P = ParamSpec("P")
R = TypeVar("R")
AsyncFunc = Callable[P, Coroutine[Any, Any, R]]


def _create_final_pattern(command: Optional[str | List[str]], pattern: Optional[str | Pattern]) -> Pattern:
    """Berilgan 'command' yoki 'pattern'dan yakuniy regex andozasini yaratadi."""
    if command:
        cmds = [command] if isinstance(command, str) else command
        escaped_cmds = [re.escape(cmd.lstrip(".")) for cmd in cmds]
        pattern_str = rf"^\.(?:{'|'.join(escaped_cmds)})(?: |$)(.*)"
        return re.compile(pattern_str, re.IGNORECASE | re.DOTALL)

    if isinstance(pattern, str):
        final_pattern_str = f"^{pattern}" if not pattern.startswith("^") else pattern
        return re.compile(final_pattern_str)

    if isinstance(pattern, Pattern):
        return pattern

    raise TypeError("`pattern` noto'g'ri tipda: `str` yoki `re.Pattern` bo'lishi kerak.")


def userbot_handler(
    *,
    command: Optional[str | List[str]] = None,
    pattern: Optional[str | Pattern] = None,
    description: str = "Tavsif berilmagan.",
    **kwargs: Any,
) -> Callable[[AsyncFunc], AsyncFunc]:
    """
    Telethon hodisalarini (events) qayta ishlash uchun professional dekorator.
    Endi 'listen' argumentini ham qabul qiladi.
    """
    # --- YECHIM: 'listen' uchun tekshiruv qo'shildi ---
    if 'listen' not in kwargs and bool(command) == bool(pattern):
        raise ValueError("Argumentlardan faqat bittasi ishlatilishi kerak: 'command' yoki 'pattern'.")

    def decorator(func: AsyncFunc) -> AsyncFunc:
        default_handler_args: Dict[str, Any] = {'outgoing': True}
        handler_args = {**default_handler_args, **kwargs}

        # Agar 'listen' bo'lmasa, pattern yaratamiz
        if 'listen' not in handler_args:
            final_pattern = _create_final_pattern(command, pattern)
            handler_args['pattern'] = final_pattern
        
        usage_str = f"{(command[0] if isinstance(command, list) else command).split()[0]}" if command else "Regex/Event asosida"
        
        meta: Dict[str, Any] = {
            "description": description,
            "commands": [command] if isinstance(command, str) else (command or []),
            "pattern_str": handler_args.get('pattern', 'N/A'),
            "is_admin_only": kwargs.get("admin_only", False),
            "usage": usage_str,
        }

        setattr(func, "_userbot_handler", True)
        setattr(func, "_userbot_meta", meta)
        setattr(func, "_handler_args", handler_args)

        @wraps(func)
        async def wrapper(*args: P.args, **kwargs: P.kwargs) -> R:
            return await func(*args, **kwargs)

        return wrapper
    return decorator



userbot_cmd = userbot_handler
