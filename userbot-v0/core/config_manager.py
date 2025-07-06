import asyncio
import json
from pathlib import Path
from typing import Any, Dict, Optional, Type, Union

from loguru import logger
from pydantic import ValidationError, SecretStr
from .config import StaticSettings
from .database import AsyncDatabase
from .exceptions import DatabaseError


class ConfigManager:
    """
    Statik va dinamik sozlamalarni boshqarish uchun markazlashgan menejer.
    Dinamik sozlamalar ma'lumotlar bazasida saqlanadi va yuklanadi.
    """

    def __init__(self, static_config: StaticSettings):
        self._static = static_config
        self._cache: Dict[str, Any] = {}
        self._db_loaded_event = asyncio.Event()
        self._db_instance: Optional[AsyncDatabase] = None

        logger.info("ConfigManager initsializatsiya qilindi.")

    def set_db_instance(self, db_instance: AsyncDatabase):
        """
        Ma'lumotlar bazasi instansiyasini ConfigManager bilan bog'laydi
        va AsyncDatabase ni statik sozlamalar asosida konfiguratsiya qiladi.
        """
        if self._db_instance is not None:
            logger.warning("Database instansi allaqachon o'rnatilgan. Qayta o'rnatilmoqda.")

        self._db_instance = db_instance
        self._db_instance.configure(db_path=self._static.DB_PATH, table_whitelist=self._static.DB_TABLE_WHITELIST, column_whitelist=self._static.DB_COLUMN_WHITELIST)
        logger.info("ConfigManager database instance bilan muvaffaqiyatli bog'landi va DB sozlandi.")

    async def initialize_db_schema(self):
        """
        Dinamik sozlamalar jadvalini yaratadi, agar mavjud bo'lmasa.
        """
        if self._db_instance is None:
            logger.error("Dinamik sozlamalar jadvalini yaratish uchun Database instansi o'rnatilmagan.")
            raise RuntimeError("Database instance not set for ConfigManager.")

        try:
            await self._db_instance.execute(
                """
                CREATE TABLE IF NOT EXISTS dynamic_settings (
                    key TEXT PRIMARY KEY UNIQUE NOT NULL,
                    value TEXT NOT NULL,
                    type TEXT NOT NULL,
                    description TEXT,
                    last_modified TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                );
            """
            )
            logger.debug("`dynamic_settings` jadvali mavjudligi tekshirildi/yaratildi.")
        except Exception as e:
            logger.critical(f"Dinamik sozlamalar jadvalini yaratishda halokatli xato: {e}", exc_info=True)
            raise DatabaseError(f"Failed to create dynamic_settings table: {e}") from e

    async def load_dynamic_settings(self):
        """
        Ma'lumotlar bazasidan dinamik sozlamalarni yuklaydi va keshlaydi.
        """
        await self.initialize_db_schema()

        if self._db_instance is None:
            logger.error("Dinamik sozlamalarni yuklash uchun Database instansi o'rnatilmagan (initialize_db_schema xato bergan bo'lishi mumkin).")
            self._db_loaded_event.set()
            return

        logger.info("Dinamik sozlamalar yuklanmoqda...")
        try:
            rows = await self._db_instance.fetchall("SELECT key, value, type FROM dynamic_settings", use_cache=True)
            loaded_count = 0
            for row in rows:
                try:
                    self._cache[row['key']] = self._cast_value(row['value'], row['type'])
                    loaded_count += 1
                except Exception as cast_err:
                    logger.error(f"Dinamik sozlama '{row['key']}' qiymatini o'girishda xato: {cast_err}. Qiymat e'tiborsiz qoldirildi.")

            self._db_loaded_event.set()
            logger.success(f"{loaded_count} ta dinamik sozlama muvaffaqiyatli yuklandi va keshlandi.")
        except Exception as e:
            logger.error(f"Dinamik sozlamalarni yuklashda xatolik: {e}. Faqat statik sozlamalar ishlatiladi.", exc_info=True)
            self._db_loaded_event.set()

    async def load_config(self):
        """
        Barcha konfiguratsiyalarni (dinamik va statik) qayta yuklaydi.
        """
        await self.load_dynamic_settings()
        logger.info("ConfigManager sozlamalari qayta yuklandi.")

    def get(self, key: str, default: Any = None) -> Any:
        """
        Sozlamani keshdan (dinamik) yoki statik konfiguratsiyadan oladi.
        """
        if key in self._cache:
            value = self._cache[key] # Keshdan qiymatni olish
            if isinstance(value, SecretStr): # YENGI: Keshdan olingan SecretStr ni ochish
                return value.get_secret_value()
            return value

        if hasattr(self._static, key):
            value = getattr(self._static, key)
            if isinstance(value, SecretStr):
                return value.get_secret_value()
            return value

        return default

    def get_all_configs(self) -> Dict[str, Any]:
        """
        Barcha statik va dinamik konfiguratsiya qiymatlarini lug'at sifatida qaytaradi.
        SecretStr qiymatlari ochilgan holda qaytariladi.
        """
        all_settings = {}
        for field_name, field_info in self._static.model_fields.items():
            value = getattr(self._static, field_name)
            if isinstance(value, SecretStr):
                all_settings[field_name] = value.get_secret_value()
            else:
                all_settings[field_name] = value

        all_settings.update(self._cache)
        return all_settings

    async def set(self, key: str, value: Any, description: Optional[str] = None):
        """
        Dinamik sozlamani ma'lumotlar bazasiga saqlaydi va keshni yangilaydi.
        """
        if self._db_instance is None:
            logger.error(f"Sozlamani '{key}' o'rnatib bo'lmadi: Database instansi o'rnatilmagan.")
            raise RuntimeError("Database instance not set for ConfigManager.")

        value_type = self._get_type_str(value)

        if isinstance(value, SecretStr):
            str_value = value.get_secret_value()
        elif value_type == 'json':
            str_value = json.dumps(value, ensure_ascii=False)
        elif isinstance(value, bool):
            str_value = "True" if value else "False"
        else:
            str_value = str(value)

        sql = """
            INSERT INTO dynamic_settings (key, value, type, description)
            VALUES (?, ?, ?, ?)
            ON CONFLICT(key) DO UPDATE SET
                value = excluded.value,
                type = excluded.type,
                description = COALESCE(excluded.description, ?),
                last_modified = CURRENT_TIMESTAMP
        """
        await self._db_instance.execute(sql, (key, str_value, value_type, description, description))
        self._cache[key] = value
        logger.info(f"Dinamik sozlama yangilandi: {key} = {value}")

    async def delete(self, key: str) -> bool:
        """
        Dinamik sozlamani ma'lumotlar bazasidan o'chiradi va keshdan olib tashlaydi.
        """
        if self._db_instance is None:
            logger.error(f"Sozlamani '{key}' o'chirib bo'lmadi: Database instansi o'rnatilmagan.")
            raise RuntimeError("Database instance not set for ConfigManager.")

        rows_deleted = await self._db_instance.execute("DELETE FROM dynamic_settings WHERE key = ?", (key,))
        if rows_deleted > 0:
            self._cache.pop(key, None)
            logger.info(f"Dinamik sozlama o'chirildi: {key}")
            return True
        return False

    def _cast_value(self, value: str, type_str: str) -> Any:
        """
        String qiymatni belgilangan turga o'giradi.
        """
        try:
            if type_str == 'int':
                return int(value)
            if type_str == 'float':
                return float(value)
            if type_str == 'bool':
                return value.lower() in ('true', '1', 'yes')
            if type_str == 'json':
                try:
                    return json.loads(value)
                except json.JSONDecodeError:
                    logger.warning(f"JSON qiymatini o'girishda xato ('{value}'). String sifatida qaytariladi.", exc_info=True)
                    return value
            if type_str == 'SecretStr':
                return SecretStr(value)
        except (ValueError, TypeError) as e:
            logger.warning(f"Qiymat '{value}'ni tur '{type_str}' ga o'girishda xato: {e}. String sifatida qaytariladi.", exc_info=True)
        return value

    def _get_type_str(self, value: Any) -> str:
        """
        Python qiymatining turini string sifatida qaytaradi.
        """
        if isinstance(value, (list, dict)):
            return 'json'
        if isinstance(value, bool):
            return 'bool'
        if isinstance(value, int):
            return 'int'
        if isinstance(value, float):
            return 'float'
        if isinstance(value, SecretStr):
            return 'SecretStr'
        return 'str'

    async def wait_for_load(self):
        """
        Dinamik sozlamalar ma'lumotlar bazasidan to'liq yuklanmaguncha kutadi.
        """
        await self._db_loaded_event.wait()


# ConfigManager instansiyasini global qilib yaratamiz
# StaticSettings() chaqiriladi, chunki config.py da global settings olib tashlangan.
# Bu qatorni o'chirib tashlaymiz va `main.py` da sozlaymiz.
# _initial_static_settings = StaticSettings() # type: ignore
# config = ConfigManager(StaticSettings(OWNER_ID=0)) # OWNER_ID=0 ni vaqtinchalik joylashtiramiz. `main.py` uni haqiqiy qiymat bilan yangilaydi.
