import asyncio
from datetime import datetime
import shutil
import time
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple, TYPE_CHECKING

import aiosqlite
from loguru import logger

# Circular import xatosini oldini olish uchun (TYPE_CHECKING)
if TYPE_CHECKING:  # pragma: no cover
    from .database import AsyncDatabase
    from core.config_manager import ConfigManager
    from core.cache import CacheManager

from .exceptions import DatabaseError, QueryError

# --- _run_cache_cleanup_util funksiyasi butunlay olib tashlandi ---


def _validate_table_name_util(table_name: str, table_whitelist: Optional[List[str]]):
    # Bu funksiya AsyncDatabase ning _config_manager dan olingan table_whitelist ni qabul qiladi.
    if table_whitelist is not None and table_name not in table_whitelist:
        logger.error(f"Xavfsizlik xatosi: Ruxsat etilmagan jadval nomi '{table_name}'.")
        raise QueryError(f"Ruxsat etilmagan jadval nomi: {table_name}")


def _validate_column_names_util(table_name: str, column_names: List[str], column_whitelist: Optional[Dict[str, List[str]]]):
    # Bu funksiya AsyncDatabase ning _config_manager dan olingan column_whitelist ni qabul qiladi.
    if column_whitelist is not None and table_name in column_whitelist:
        allowed_columns = column_whitelist[table_name]
        for col in column_names:
            if col not in allowed_columns:
                logger.error(f"Xavfsizlik xatosi: '{table_name}' jadvali uchun ruxsat etilmagan ustun nomi '{col}'.")
                raise QueryError(f"Ruxsat etilmagan ustun nomi: {col} for table {table_name}")


async def _get_db_stats_util(db_instance: "AsyncDatabase") -> Dict[str, Any]:
    if not db_instance.db_path:
        logger.warning("DB statistikasini olishda xatolik: Ma'lumotlar bazasi yo'li sozlanmagan.")
        return {"error": "Ma'lumotlar bazasi yo'li sozlanmagan."}

    stats: Dict[str, Any] = {}
    try:
        stats["file_size_bytes"] = db_instance.db_path.stat().st_size if db_instance.db_path.exists() else 0
        
        pragmas_to_check = [
            ("journal_mode", "PRAGMA journal_mode;"),
            ("foreign_keys", "PRAGMA foreign_keys;"),
            ("synchronous", "PRAGMA synchronous;"),
        ]
        pragma_results = {}
        for name, sql in pragmas_to_check:
            pragma_results[name] = await db_instance.fetch_val(sql)
        stats["pragmas"] = pragma_results

        tables_info = []
        tables = await db_instance.fetchall("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'")
        for table in tables:
            table_name = table['name']
            row_count = await db_instance.fetch_val(f'SELECT count(*) FROM "{table_name}"')
            indexes = await db_instance.fetchall(f"PRAGMA index_list('{table_name}')")
            
            # TUZATISH: `dbstat` ga bog'liq bo'lgan va xatolik berayotgan qatorlar olib tashlandi.
            tables_info.append({
                "name": table_name,
                "row_count": row_count,
                "indexes": [idx['name'] for idx in indexes]
            })

        stats["tables"] = tables_info
        stats["table_count"] = len(tables_info)
        stats["total_rows"] = sum(t.get("row_count", 0) for t in tables_info)
        
        if hasattr(db_instance, '_cache_manager'):
            stats["cache"] = await db_instance._cache_manager.get_stats()

    except Exception as e:
        logger.error(f"DB statistikasini olishda xatolik: {e}", exc_info=True)
        stats["error"] = str(e)
    return stats

async def _run_migrations_util(db_instance: "AsyncDatabase"):
    if not db_instance.migrations_path.is_dir():
        logger.warning(f"Migratsiyalar papkasi topilmadi: {db_instance.migrations_path}")
        return

    async with db_instance.transaction():
        await db_instance.execute(
            """
            CREATE TABLE IF NOT EXISTS applied_migrations (
                id INTEGER PRIMARY KEY,
                filename TEXT UNIQUE NOT NULL,
                applied_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
            )
            """
        )
        applied_rows = await db_instance.fetchall("SELECT filename FROM applied_migrations")
        applied_files = {row['filename'] for row in applied_rows}

    migration_files = sorted([f for f in db_instance.migrations_path.glob("*.sql")], key=lambda f: f.name)
    applied_migrations_count = 0
    for migration_file in migration_files:
        if migration_file.name not in applied_files:
            logger.info("Yangi migratsiya qo'llanilmoqda: %s" % migration_file.name)
            try:
                with open(migration_file, 'r', encoding='utf-8') as f:
                    sql_script = f.read()

                conn = await db_instance._get_connection()
                await conn.executescript(sql_script)

                await db_instance.execute("INSERT INTO applied_migrations (filename) VALUES (?)", (migration_file.name,))
                logger.success(f"Migratsiya '{migration_file.name}' muvaffaqiyatli qo'llanildi.")
                applied_migrations_count += 1
            except aiosqlite.Error as e:
                logger.critical(f"Migratsiya '{migration_file.name}' bajarilishida xatolik: {e}", exc_info=True)
                raise QueryError(f"Migratsiya xatosi: {migration_file.name}") from e

    if applied_migrations_count == 0:
        logger.info("Ma'lumotlar bazasi sxemasi dolzarb. Yangi migratsiyalar yo'q.")


async def _run_initial_data_script_util(db_instance: "AsyncDatabase"):
    if not db_instance.initial_data_path.is_file():
        logger.debug("Boshlang'ich ma'lumotlar fayli topilmadi: %s. Yuklanish shart emas." % db_instance.initial_data_path)
        return

    async with db_instance.transaction():
        await db_instance.execute(
            """
            CREATE TABLE IF NOT EXISTS initial_data_loaded (
                id INTEGER PRIMARY KEY,
                script_name TEXT UNIQUE NOT NULL,
                loaded_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
            )
            """
        )

        loaded_scripts = await db_instance.fetch_val("SELECT script_name FROM initial_data_loaded WHERE script_name = ?", (db_instance.initial_data_path.name,))
        if loaded_scripts:
            logger.info("Boshlang'ich ma'lumotlar '%s' allaqachon yuklangan." % db_instance.initial_data_path.name)
            return

    logger.info("Boshlang'ich ma'lumotlar '%s' yuklanmoqda..." % db_instance.initial_data_path.name)
    try:
        with open(db_instance.initial_data_path, 'r', encoding='utf-8') as f:
            sql_script = f.read()

        conn = await db_instance._get_connection()
        await conn.executescript(sql_script)

        await db_instance.execute("INSERT INTO initial_data_loaded (script_name) VALUES (?)", (db_instance.initial_data_path.name,))
        logger.success(f"Boshlang'ich ma'lumotlar '{db_instance.initial_data_path.name}' muvaffaqiyatli yuklandi.")
    except aiosqlite.Error as e:
        logger.critical(f"Boshlang'ich ma'lumotlar '{db_instance.initial_data_path.name}' yuklashda xatolik: {e}", exc_info=True)
        raise QueryError(f"Boshlang'ich ma'lumotlar xatosi: {db_instance.initial_data_path.name}") from e
    except Exception as e:
        logger.critical(f"Boshlang'ich ma'lumotlar '{db_instance.initial_data_path.name}' o'qishda yoki bajarishda kutilmagan xatolik: {e}", exc_info=True)
        raise


async def _create_backup_util(db_instance: "AsyncDatabase") -> Path:
    if not db_instance.db_path or not db_instance.db_path.exists():
        raise DatabaseError("Zaxira nusxa yaratish uchun baza fayli mavjud emas.")

    timestamp = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
    backup_file = db_instance.backup_dir / f"{db_instance.db_path.name}.{timestamp}.bak"

    is_connected_before = db_instance._conn is not None
    if is_connected_before:
        await db_instance.close()

    try:
        await asyncio.to_thread(shutil.copy, db_instance.db_path, backup_file)
        logger.info(f"Ma'lumotlar bazasi zaxirasi yaratildi: {backup_file}")
        return backup_file
    except Exception as e:
        logger.error(f"Zaxira nusxa yaratishda xatolik: {e}", exc_info=True)
        raise DatabaseError(f"Zaxira nusxa yaratishda xatolik: {e}") from e
    finally:
        if is_connected_before:
            await db_instance.connect()


# GLOBAL obyektlar bu yerda yaratilmaydi.
