import asyncio
from datetime import datetime
import time
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any, Callable, Coroutine, Dict, List, Optional, Tuple, TypeVar, ParamSpec, AsyncGenerator, Hashable, TYPE_CHECKING
from functools import wraps

import aiosqlite
from loguru import logger
from .config import BASE_DIR
# ConfigManager va CacheManager uchun type-hinting
if TYPE_CHECKING:
    from core.config_manager import ConfigManager 
    from core.cache import CacheManager 


from .exceptions import DatabaseError, DBConnectionError, QueryError
from .db_utils import (
    _validate_table_name_util,
    _validate_column_names_util,
    _get_db_stats_util,
    _run_migrations_util,
    _run_initial_data_script_util,
    _create_backup_util
)


P = ParamSpec("P")
R = TypeVar("R")


def retry_on_lock(retries: int = 5, delay: float = 0.2) -> Callable[[Callable[P, Coroutine[Any, Any, R]]], Callable[P, Coroutine[Any, Any, R]]]:
    def decorator(func: Callable[P, Coroutine[Any, Any, R]]) -> Callable[P, Coroutine[Any, Any, R]]:
        @wraps(func)
        async def wrapper(*args: P.args, **kwargs: P.kwargs) -> R:
            last_exception: Optional[Exception] = None
            for attempt in range(retries):
                try:
                    return await func(*args, **kwargs)
                except aiosqlite.OperationalError as e:
                    last_exception = e
                    error_message = str(e).lower()
                    if "locked" in error_message or "busy" in error_message:
                        if attempt < retries - 1:
                            logger.warning(f"DB bloklandi ({error_message}). {delay:.2f} soniyadan so'ng qayta urinish ({attempt + 1}/{retries})...")
                            await asyncio.sleep(delay + (attempt * delay))
                        else:
                            logger.error(f"DB bloklanishi bartaraf etilmadi. Barcha {retries} urinishlar muvaffaqiyatsiz.")
                            raise QueryError(f"Database lock/busy error not resolved after {retries} retries.") from e
                    else:
                        logger.error(f"DB da tuzatib bo'lmaydigan operatsion xatolik: {e}", exc_info=True) 
                        raise QueryError(f"Unhandled operational error: {e}") from e
                except Exception as e:
                    last_exception = e
                    logger.error(f"So'rovni bajarishda kutilmagan xatolik: {e}", exc_info=True) 
                    raise QueryError(f"So'rovni bajarishda kutilmagan xatolik: {e}") from e
            raise QueryError("Funksiya barcha urinishlardan so'ng qiymat qaytarmadi.") from last_exception
        return wrapper
    return decorator

class AsyncDatabase:
    """
    Asinxron ma'lumotlar bazasi (SQLite) bilan ishlash uchun interfeys.
    """
    def __init__(self, config_manager: 'ConfigManager', cache_manager: 'CacheManager'):
        self.db_path: Optional[Path] = None
        self.backup_dir = BASE_DIR / "data" / "backups" 
        self.migrations_path = BASE_DIR / "data" / "migrations" 
        self.initial_data_path = BASE_DIR / "data" / "initial_data.sql" 
        self._conn: Optional[aiosqlite.Connection] = None
        self._lock = asyncio.Lock()
        
        self._table_whitelist: Optional[List[str]] = None
        self._column_whitelist: Dict[str, List[str]] = {}
        self._config_manager = config_manager 
        self._cache_manager = cache_manager 

        # YANGI QATOR: Tozalash konfiguratsiyalarini saqlash uchun lug'at
        self._cleanup_configurations: Dict[str, str] = {} 

    def configure(self, db_path: Path, table_whitelist: Optional[List[str]] = None, column_whitelist: Optional[Dict[str, List[str]]] = None): 
        if self.db_path and self.db_path != db_path:
            logger.warning(f"Ma'lumotlar bazasi yo'li '{self.db_path}' dan '{db_path}' ga qayta sozlanmoqda. Bu kutilmagan holat bo'lishi mumkin.")
        self.db_path = db_path
        self.backup_dir.mkdir(parents=True, exist_ok=True)
        
        self._table_whitelist = table_whitelist if table_whitelist is not None else self._config_manager.get("DB_TABLE_WHITELIST")
        self._column_whitelist = column_whitelist if column_whitelist is not None else (self._config_manager.get("DB_COLUMN_WHITELIST") or {})

        logger.info(f"Database Manager (Professional v2) '{self.db_path}' uchun sozlandi.")
        
    async def connect(self) -> None:
        if not self.db_path:
            raise DBConnectionError("Ma'lumotlar bazasi yo'li sozlanmagan. Dastlab `db.configure()` metodini chaqiring.")

        async with self._lock:
            if self.is_connected():
                logger.debug("Ma'lumotlar bazasi ulanishi allaqachon mavjud.")
                return

            try:
                self.db_path.parent.mkdir(parents=True, exist_ok=True)
                self._conn = await aiosqlite.connect(self.db_path, timeout=10)
                self._conn.row_factory = aiosqlite.Row

                await self._conn.executescript(
                    """
                    PRAGMA journal_mode=WAL;
                    PRAGMA foreign_keys = ON;
                    PRAGMA synchronous = NORMAL;
                    PRAGMA cache_size = -8000;
                    PRAGMA temp_store = MEMORY;
                    """
                )
                await self._initialize_database()
                logger.success("Ma'lumotlar bazasi muvaffaqiyatli ulandi va sozlandi.")
                
            except aiosqlite.Error as e:
                logger.critical(f"DB ulanishida yoki sozlashda xatolik yuz berdi: {e}", exc_info=True) 
                self._conn = None
                raise DBConnectionError(e) from e


    async def close(self) -> None:
        async with self._lock:
            if self._conn:
                try:
                    await self._conn.executescript("PRAGMA wal_checkpoint(TRUNCATE);")
                except aiosqlite.Error as e:
                    logger.warning(f"WAL checkpointni bajarishda xatolik: {e}")
                await self._conn.close()
                self._conn = None
                logger.info("Ma'lumotlar bazasi bilan ulanish yopildi.")
            
    def is_connected(self) -> bool:
        """Ma'lumotlar bazasi bilan ulanish mavjud va aktiv ekanligini tekshiradi."""
        return self._conn is not None


    async def _get_connection(self) -> aiosqlite.Connection:
        if not self.is_connected():
            await self.connect()
        if self._conn is None:
            raise DBConnectionError("Ma'lumotlar bazasi bilan ulanib bo'lmadi.")
        return self._conn


    @asynccontextmanager
    async def transaction(self) -> AsyncGenerator[aiosqlite.Cursor, None]:
        conn = await self._get_connection()
        try:
            async with conn.cursor() as cursor:
                yield cursor
            await conn.commit()
        except Exception:
            await conn.rollback()
            logger.error("Tranzaksiya xatolik bilan yakunlandi va o'zgarishlar bekor qilindi.", exc_info=True)
            raise

    @retry_on_lock()
    async def execute(self, sql: str, params: Tuple = ()) -> int:
        logger.trace(f"EXECUTE SQL: {sql} | PARAMS: {params}")
        conn = await self._get_connection()
        async with conn.execute(sql, params) as cursor:
            return cursor.rowcount

    @retry_on_lock()
    async def executemany(self, sql: str, params: List[Tuple]) -> int:
        logger.trace(f"EXECUTEMANY SQL: {sql} | PARAMS_COUNT: {len(params)}")
        conn = await self._get_connection()
        async with conn.executemany(sql, params) as cursor:
            return cursor.rowcount

    @retry_on_lock()
    async def execute_insert(self, sql: str, params: Tuple = ()) -> Optional[int]:
        logger.trace(f"INSERT SQL: {sql} | PARAMS: {params}")
        conn = await self._get_connection()
        async with conn.execute(sql, params) as cursor:
            return cursor.lastrowid


    @retry_on_lock()
    async def fetchone(self, sql: str, params: Tuple = (), *, use_cache: bool = False) -> Optional[Dict[str, Any]]:
        logger.trace(f"FETCHONE SQL: {sql} | PARAMS: {params}")
        cache_key: Optional[str] = None 

        if use_cache:
            cache_key = f"fetchone:{sql}:{params}"
            cached_result = await self._cache_manager.get(cache_key, namespace="db_queries") 
            if cached_result is not None:
                return cached_result
        
        conn = await self._get_connection()
        async with conn.execute(sql, params) as cursor:
            row = await cursor.fetchone()
            result = dict(row) if row else None
            if use_cache and result and cache_key: 
                await self._cache_manager.set(cache_key, result, namespace="db_queries", ttl=self._config_manager.get("CACHE_DEFAULT_TTL")) 
            return result

    @retry_on_lock()
    async def fetchall(self, sql: str, params: Tuple = (), *, use_cache: bool = False) -> List[Dict[str, Any]]:
        logger.trace(f"FETCHALL SQL: {sql} | PARAMS: {params}")
        cache_key: Optional[str] = None 

        if use_cache:
            cache_key = f"fetchall:{sql}:{params}"
            cached_result = await self._cache_manager.get(cache_key, namespace="db_queries") 
            if cached_result is not None:
                return cached_result
        
        conn = await self._get_connection()
        async with conn.execute(sql, params) as cursor:
            rows = await cursor.fetchall()
            result = [dict(row) for row in rows]
            if use_cache and result and cache_key: 
                await self._cache_manager.set(cache_key, result, namespace="db_queries", ttl=self._config_manager.get("CACHE_DEFAULT_TTL")) 
            return result

    @retry_on_lock()
    async def fetch_val(self, sql: str, params: Tuple = (), *, use_cache: bool = False) -> Optional[Any]:
        logger.trace(f"FETCH_VAL SQL: {sql} | PARAMS: {params}")
        cache_key: Optional[str] = None 

        if use_cache:
            cache_key = f"fetchval:{sql}:{params}"
            cached_result = await self._cache_manager.get(cache_key, namespace="db_queries") 
            if cached_result is not None:
                return cached_result
        
        conn = await self._get_connection()
        async with conn.execute(sql, params) as cursor:
            row = await cursor.fetchone()
            result = row[0] if row else None
            if use_cache and result is not None and cache_key: 
                await self._cache_manager.set(cache_key, result, namespace="db_queries", ttl=self._config_manager.get("CACHE_DEFAULT_TTL")) 
            return result

    def clear_cache(self):
        asyncio.create_task(self._cache_manager.clear_namespace("db_queries")) 
        logger.info("Ma'lumotlar bazasi so'rovlari keshi tozalandi.")

    def _validate_table_name(self, table_name: str):
        _validate_table_name_util(table_name, self._config_manager.get("DB_TABLE_WHITELIST")) 
        
    def _validate_column_names(self, table_name: str, column_names: List[str]):
        _validate_column_names_util(table_name, column_names, self._config_manager.get("DB_COLUMN_WHITELIST"))

    async def insert(self, table_name: str, data: Dict[str, Any]) -> Optional[int]:
        self._validate_table_name(table_name)
        self._validate_column_names(table_name, list(data.keys()))

        keys = ", ".join(data.keys())
        placeholders = ", ".join("?" for _ in data)
        sql = f"INSERT INTO {table_name} ({keys}) VALUES ({placeholders})"
        return await self.execute_insert(sql, tuple(data.values()))

    async def update(self, table_name: str, data: Dict[str, Any], where: str, where_params: Tuple = ()) -> int:
        self._validate_table_name(table_name)
        self._validate_column_names(table_name, list(data.keys()))

        set_clause = ", ".join(f"{key} = ?" for key in data)
        sql = f"UPDATE {table_name} SET {set_clause} WHERE {where}"
        return await self.execute(sql, tuple(data.values()) + where_params)

    async def upsert(self, table_name: str, data: Dict[str, Any], conflict_target: List[str]) -> Optional[int]:
        self._validate_table_name(table_name)
        self._validate_column_names(table_name, list(data.keys()))
        self._validate_column_names(table_name, conflict_target)

        keys = ", ".join(data.keys())
        placeholders = ", ".join("?" for _ in data)
        conflict_keys = ", ".join(conflict_target)
        update_keys = ", ".join(f"{k} = excluded.{k}" for k in data if k not in conflict_target)

        sql = f"""
            INSERT INTO {table_name} ({keys}) VALUES ({placeholders})
            ON CONFLICT({conflict_keys}) DO UPDATE SET {update_keys}
        """
        return await self.execute_insert(sql, tuple(data.values()))

    async def vacuum(self):
        if not self.db_path:
            raise QueryError("VACUUM uchun ma'lumotlar bazasi yo'li topilmadi.")

        logger.info("VACUUM operatsiyasi boshlandi. Asosiy DB ulanishi vaqtincha yopiladi...")
        
        is_connected_before = self._conn is not None
        if is_connected_before:
            await self.close()
        
        try:
            logger.debug("VACUUM uchun eksklyuziv ulanish ochilmoqda...")
            async with aiosqlite.connect(self.db_path) as temp_conn:
                await temp_conn.execute("VACUUM")
                await temp_conn.commit()
            logger.success("✅ VACUUM operatsiyasi muvaffaqiyatli yakunlandi.")
        except Exception as e:
            logger.exception("VACUUM operatsiyasi davomida kutilmagan xatolik yuz berdi.")
            raise QueryError(f"VACUUM failed: {e}") from e
        finally:
            if is_connected_before:
                await self.connect()

    async def _initialize_database(self):
        try:
            await _run_migrations_util(self)
            await _run_initial_data_script_util(self)
            logger.success("Ma'lumotlar bazasi tayyor va barcha migratsiyalar qo'llanildi.")
        except Exception as e:
            logger.critical(f"Ma'lumotlar bazasini initsializatsiya qilishda halokatli xato: {e}", exc_info=True) 
            raise

    async def db_stats(self) -> Dict[str, Any]:
        return await _get_db_stats_util(self)

    async def log_task_execution(self, task_key: str, duration_ms: float, status: str, details: Optional[str] = None, run_at: Optional[float] = None):
        """Vazifaning bajarilish natijasini DBga yozadi."""
        sql = """
            INSERT INTO task_logs (task_key, duration_ms, status, details, run_at)
            VALUES (?, ?, ?, ?, ?)
        """
        try:
            execution_time = datetime.fromtimestamp(run_at) if run_at is not None else datetime.now()
            await self.execute(sql, (task_key, duration_ms, status, details, execution_time))
        except Exception as e:
            logger.critical(f"Vazifa '{task_key}' uchun log yozishda KRITIK xatolik: {e}", exc_info=True)




    async def create_backup(self) -> Path:
        return await _create_backup_util(self)

    async def get_log_text_settings(self, chat_id: int) -> Optional[Dict[str, Any]]:
        return await self.fetchone("SELECT * FROM text_log_settings WHERE chat_id = ?", (chat_id,))

    async def add_text_log_ignored_user(self, user_id: int) -> Optional[int]:
        return await self.insert("text_log_ignored_users", {"user_id": user_id})


    def register_cleanup_table(self, table_name: str, date_column: str): 
        """
        Vaqtinchalik ma'lumotlar bazasi jadvallarini tozalash uchun ro'yxatdan o'tkazadi.
        
        Args:
            table_name (str): Tozalanadigan jadval nomi.
            date_column (str): Jadvaldagi sanani saqlovchi ustun nomi (yozuv eski ekanligini aniqlash uchun).
        """
        if table_name in self._cleanup_configurations:
            logger.warning(f"Jadval '{table_name}' allaqachon tozalash uchun ro'yxatdan o'tgan. Ustuni yangilanmoqda.")
        self._cleanup_configurations[table_name] = date_column
        logger.debug(f"Jadval '{table_name}' ({date_column} ustuni bilan) tozalash uchun ro'yxatdan o'tkazildi.")

    def get_cleanup_configurations(self) -> Dict[str, str]:
        """
        Tozalash uchun ro'yxatdan o'tgan barcha jadval va sana ustunlari konfiguratsiyalarini qaytaradi.
        
        Returns:
            Dict[str, str]: Jadval nomlari va ularning sana ustunlari xaritasi.
        """
        return self._cleanup_configurations.copy() # Xavfsiz nusxasini qaytarish
    
    async def __aenter__(self):
        """Asinxron kontekst menejeriga kirish."""
        await self.connect()
        return self


    async def __aexit__(self, exc_type, exc_val, exc_tb):
        """Asinxron kontekst menejeridan chiqish."""
        await self.close()


# GLOBAL obyektni bu yerda yaratmaymiz.
# U main.py da yaratilib, Application ga uzatiladi.
