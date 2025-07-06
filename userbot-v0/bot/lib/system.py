# bot/lib/system.py

import asyncio
import html
import shlex
import time
from pathlib import Path
from typing import Tuple, Optional, List, Dict

from loguru import logger

# Loyihaning ildiz papkasini aniqlash
PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent.resolve()

# Xavfsizlik uchun ruxsat etilgan buyruqlar "oq ro'yxati"
ALLOWED_SHELL_COMMANDS = {
    "ls", "cat", "echo", "df", "du", "uptime", "pwd", "whoami",
    "git", "python", "python3", "pip", "pip3", "apt", "apt-get", "neofetch"
}


async def run_shell_command(command: str) -> Tuple[str, str, Optional[int], float]:
    """Shell buyrug'ini xavfsiz tarzda ishga tushiradi va natijasini qaytaradi."""
    logger.info(f"Shell buyrug'i bajarilmoqda: '{command}'")
    
    try:
        cmd_list = shlex.split(command)
    except ValueError as e:
        logger.warning(f"Shell buyrug'ini ajratishda xato: {e}")
        return "", f"<b>❌ Xato:</b> Buyruq argumentlari noto'g'ri. ({e})", -1, 0.0

    if not cmd_list:
        return "", "<b>❌ Buyruq bo'sh.</b>", -1, 0.0

    if cmd_list[0] not in ALLOWED_SHELL_COMMANDS:
        logger.warning(f"Xavfsizlik buzilishi: '{command}' (Ruxsat etilmagan buyruq: {cmd_list[0]})")
        return "", "<b>❌ Xavfsizlik cheklovi: Ruxsat etilmagan buyruq.</b>", -1, 0.0

    start_time = time.monotonic()
    try:
        process = await asyncio.create_subprocess_exec(
            *cmd_list,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE
        )
        stdout_b, stderr_b = await asyncio.wait_for(process.communicate(), timeout=60.0)
        duration = time.monotonic() - start_time
        
        stdout = stdout_b.decode('utf-8', 'ignore').strip()
        stderr = stderr_b.decode('utf-8', 'ignore').strip()
        
        logger.info(f"Shell buyrug'i yakunlandi: '{command}', Kod: {process.returncode}, Vaqt: {duration:.2f}s")
        if stderr:
            logger.warning(f"Shell buyrug'i xatosi (stderr): '{command}'\n{stderr}")
            
        return stdout, stderr, process.returncode, duration
    except asyncio.TimeoutError:
        logger.warning(f"Shell buyrug'i vaqti tugadi: '{command}'")
        return "", "<b>❌ Buyruq 60 soniyadan so'ng to'xtatildi.</b>", -1, 60.0
    except FileNotFoundError:
        logger.error(f"Buyruq topilmadi: {cmd_list[0]}")
        return "", f"<b>❌ Buyruq topilmadi:</b> <code>{html.escape(cmd_list[0])}</code>", -1, 0.0
    except Exception as e:
        logger.error(f"Shell buyrug'ini bajarishda kutilmagan xato: '{command}', Xato: {e}", exc_info=True)
        return "", f"<b>❌ Kutilmagan xato:</b> <code>{html.escape(str(e))}</code>", -1, 0.0


def resolve_secure_path(user_path: str) -> Optional[Path]:
    """Foydalanuvchi kiritgan yo'lni loyiha papkasi ichida ekanligini tekshirib, xavfsiz Path obyektini qaytaradi."""
    try:
        # .. kabi belgilarni oldini olish uchun resolve() ishlatamiz
        res_path = (PROJECT_ROOT / user_path).resolve()
        # Yo'l loyiha papkasidan tashqariga chiqmasligini ta'minlaymiz
        if res_path.is_relative_to(PROJECT_ROOT):
            return res_path
        logger.warning(f"Xavfli yo'lga urinish: '{user_path}' -> '{res_path}'")
        return None
    except Exception as e:
        logger.error(f"Yo'lni aniqlashda xato: {user_path}, {e}")
        return None

async def read_secure_file(file_path: str) -> Optional[str]:
    """Faylni xavfsiz tarzda o'qiydi."""
    if not (res_path := resolve_secure_path(file_path)):
        return None
    if not res_path.is_file():
        logger.warning(f"O'qish uchun fayl topilmadi: {res_path}")
        return None
    try:
        content = await asyncio.to_thread(res_path.read_text, encoding='utf-8')
        logger.info(f"Fayl o'qildi: {res_path}")
        return content
    except Exception as e:
        logger.error(f"Faylni o'qishda kutilmagan xato ({res_path}): {e}")
        return None

async def write_secure_file(file_path: str, content: str) -> bool:
    """Faylga xavfsiz tarzda ma'lumot yozadi."""
    if not (res_path := resolve_secure_path(file_path)):
        return False
    try:
        res_path.parent.mkdir(parents=True, exist_ok=True)
        await asyncio.to_thread(res_path.write_text, content, encoding='utf-8')
        logger.info(f"Faylga yozildi: {res_path}")
        return True
    except Exception as e:
        logger.error(f"Faylga yozishda kutilmagan xato ({res_path}): {e}")
        return False

