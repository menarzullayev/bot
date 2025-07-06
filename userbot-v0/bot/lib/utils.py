# bot/lib/utils.py
"""
Boshqa modullarga sig'maydigan, umumiy maqsadli yordamchi funksiyalar
va klasslar to'plami.
"""

import argparse
import asyncio
import json
import math
from typing import Any, Coroutine, List

from loguru import logger

class RaiseArgumentParser(argparse.ArgumentParser):
    """
    Argumentlarni parse qilishda xatolik yuz berganda dasturni to'xtatmasdan,
    istisno (exception) qaytaradigan maxsus ArgumentParser.
    """
    def __init__(self, *args, **kwargs):
        # Yordam (-h) argumentini avtomatik qo'shishni o'chiramiz
        kwargs.setdefault('add_help', False)
        super().__init__(*args, **kwargs)

    def error(self, message: str):
        """Standart `exit()` o'rniga `ValueError` qaytaradi."""
        raise ValueError(message)
    
    
    

def humanbytes(size: float) -> str:
    """
    Baytlarni odam o'qishi uchun qulay formatga (B, KB, MB, GB) o'tkazadi.
    """
    if size is None or not isinstance(size, (int, float)) or size < 0:
        return "N/A"
    if size == 0:
        return "0 B"
    
    unit_labels = ["B", "KB", "MB", "GB", "TB", "PB", "EB", "ZB", "YB"]
    try:
        i = int(math.floor(math.log(size, 1024)))
        p = math.pow(1024, i)
        s = round(size / p, 2)
        return f"{s} {unit_labels[i]}"
    except (ValueError, IndexError):
        return "N/A"


def format_time_delta(seconds: float) -> str:
    """
    Sekundlarni kun, soat, daqiqa va soniyalarga bo'lib, o'qish uchun
    qulay matn ko'rinishida qaytaradi. Masalan: "2 kun 5 soat 34 daqiqa"
    """
    if seconds is None or not isinstance(seconds, (int, float)) or seconds < 0:
        return "N/A"

    seconds = int(seconds)
    if seconds == 0:
        return "0 soniya"

    days, seconds = divmod(seconds, 86400)
    hours, seconds = divmod(seconds, 3600)
    minutes, seconds = divmod(seconds, 60)

    parts: List[str] = []
    if days > 0:
        parts.append(f"{days} kun")
    if hours > 0:
        parts.append(f"{hours} soat")
    if minutes > 0:
        parts.append(f"{minutes} daqiqa")
    if seconds > 0:
        parts.append(f"{seconds} soniya")

    return " ".join(parts)


def parse_string_to_value(value_str: str) -> Any:
    """Matnni mos tipga (bool, int, float, list, dict) o'girishga harakat qiladi."""
    if not isinstance(value_str, str):
        return value_str # Agar matn bo'lmasa, o'zini qaytaramiz

    value_str = value_str.strip()
    if value_str.lower() == 'true':
        return True
    if value_str.lower() == 'false':
        return False
    
    try:
        # JSONni tekshirish eng ishonchli usul, chunki u son, list, dict'larni qamrab oladi
        return json.loads(value_str)
    except json.JSONDecodeError:
        # Agar JSON bo'lmasa, bu oddiy matn
        return value_str


def run_in_background(coro: Coroutine[Any, Any, Any]) -> asyncio.Task:
    """
    Asinxron funksiyani (coroutine) fonda ishga tushiradi va uning
    Task obyektini qaytaradi.
    """
    task = asyncio.create_task(coro)
    
    # Vazifaga nom berish (debugging uchun qulay)
    try:
        task.set_name(coro.__qualname__)
    except Exception:
        pass # Nom berishda xato bo'lsa, indamaymiz
        
    logger.debug(f"Fon vazifasi yaratildi: {task.get_name()}")
    return task


