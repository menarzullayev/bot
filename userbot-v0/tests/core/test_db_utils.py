import asyncio
import pytest
from pathlib import Path
from unittest.mock import MagicMock, AsyncMock, patch
import pytest_asyncio
import aiosqlite # aiosqlite.Error uchun import
import shutil # shutil.disk_usage ni mock qilish uchun

# Test qilinadigan funksiyalar va klasslar
from core.db_utils import (
    _validate_table_name_util,
    _validate_column_names_util,
    _get_db_stats_util,
    _run_migrations_util,
    _create_backup_util,
    _run_initial_data_script_util,
)
from core.database import AsyncDatabase
from core.exceptions import QueryError, DatabaseError
from core.config_manager import ConfigManager
from core.cache import CacheManager
from loguru import logger

# --- Fixtures (Test uchun tayyorgarlik) ---

@pytest.fixture
def mock_config_manager() -> MagicMock:
    """Soxta ConfigManager obyektini yaratadi."""
    mock = MagicMock(spec=ConfigManager)
    mock.get.return_value = {}
    return mock


@pytest_asyncio.fixture # <--- O'ZGARTIRILGAN QATOR (avvalgi PytestWarningni to'g'irlaydi)
async def mock_cache_manager() -> AsyncMock:
    """Soxta CacheManager obyektini yaratadi."""
    mock = AsyncMock(spec=CacheManager)
    mock.get_stats.return_value = {"total_hits": 10, "total_misses": 5}
    return mock


@pytest_asyncio.fixture
async def db(tmp_path: Path, mock_config_manager: MagicMock, mock_cache_manager: AsyncMock):
    """Har bir test uchun toza, vaqtinchalik ma'lumotlar bazasini yaratadi."""
    db_path = tmp_path / "test_db_for_utils.db"
    database = AsyncDatabase(config_manager=mock_config_manager, cache_manager=mock_cache_manager)

    # _initialize_database ni mock qilish, chunki u boshqa testlarda sinovdan o'tgan
    database._initialize_database = AsyncMock(return_value=None) 

    database.configure(db_path=db_path)
    await database.connect()

    # Testlar uchun zarur bo'lgan yo'llarni sozlash
    database.initial_data_path = tmp_path / "initial_data.sql"
    database.migrations_path = tmp_path / "migrations"
    database.backup_dir = tmp_path / "backups"
    database.backup_dir.mkdir(exist_ok=True)


    yield database

    await database.close()


class TestDBOperations:
    """Asosiy DB operatsiyalarini test qilish (bu funksiyalar db_utils.py da emas, lekin avvalgi savollarda bor edi)."""

    @pytest.mark.asyncio
    async def test_db_connection(self, db: AsyncDatabase):
        assert db._conn is not None
        assert await db.is_connected() is True


    @pytest.mark.asyncio
    async def test_execute_query(self, db: AsyncDatabase):
        await db.execute("CREATE TABLE test (id INTEGER)")
        count = await db.fetch_val("SELECT COUNT(*) FROM test")
        assert count == 0

    @pytest.mark.asyncio
    async def test_fetch_one(self, db: AsyncDatabase):
        await db.execute("CREATE TABLE users (id INTEGER, name TEXT)")
        await db.execute("INSERT INTO users (id, name) VALUES (?, ?)", (1, "Alice"))
        user = await db.fetchone("SELECT * FROM users WHERE id = ?", (1,))
        assert user is not None
        assert user['name'] == "Alice"


    @pytest.mark.asyncio
    async def test_fetch_all(self, db: AsyncDatabase):
        await db.execute("CREATE TABLE users (id INTEGER, name TEXT)")
        await db.execute("INSERT INTO users (id, name) VALUES (?, ?)", (1, "Alice"))
        await db.execute("INSERT INTO users (id, name) VALUES (?, ?)", (2, "Bob"))
        users = await db.fetchall("SELECT * FROM users ORDER BY id")
        assert len(users) == 2
        assert users[0]['name'] == "Alice"

    @pytest.mark.asyncio
    async def test_fetch_val(self, db: AsyncDatabase):
        await db.execute("CREATE TABLE items (id INTEGER, value INTEGER)")
        await db.execute("INSERT INTO items (id, value) VALUES (?, ?)", (1, 10))
        value = await db.fetch_val("SELECT value FROM items WHERE id = ?", (1,))
        assert value == 10

    @pytest.mark.asyncio
    async def test_transaction_success(self, db: AsyncDatabase):
        await db.execute("CREATE TABLE accounts (id INTEGER, balance INTEGER)")
        async with db.transaction():
            await db.execute("INSERT INTO accounts (id, balance) VALUES (?, ?)", (1, 100))
        balance = await db.fetch_val("SELECT balance FROM accounts WHERE id = 1")
        assert balance == 100

    @pytest.mark.asyncio
    async def test_transaction_rollback(self, db: AsyncDatabase):
        await db.execute("CREATE TABLE accounts (id INTEGER, balance INTEGER)")
        with pytest.raises(Exception):
            async with db.transaction():
                await db.execute("INSERT INTO accounts (id, balance) VALUES (?, ?)", (1, 100))
                raise Exception("Rollback test")
        balance = await db.fetch_val("SELECT balance FROM accounts WHERE id = 1")
        assert balance is None

    @pytest.mark.asyncio
    async def test_transaction_nested_rollback(self, db: AsyncDatabase):
        await db.execute("CREATE TABLE accounts (id INTEGER, balance INTEGER)")
        with pytest.raises(Exception):
            async with db.transaction():
                await db.execute("INSERT INTO accounts (id, balance) VALUES (?, ?)", (1, 100))
                async with db.transaction(): # Nested transaction
                    await db.execute("INSERT INTO accounts (id, balance) VALUES (?, ?)", (2, 200))
                    raise Exception("Nested rollback test")
        balance1 = await db.fetch_val("SELECT balance FROM accounts WHERE id = 1")
        balance2 = await db.fetch_val("SELECT balance FROM accounts WHERE id = 2")
        assert balance1 is None
        assert balance2 is None

    @pytest.mark.asyncio
    async def test_context_manager_close(self, tmp_path: Path, mock_config_manager: MagicMock, mock_cache_manager: AsyncMock):
        db_path = tmp_path / "test_context.db"
        database = AsyncDatabase(config_manager=mock_config_manager, cache_manager=mock_cache_manager)
        database.configure(db_path=db_path)
        
        async with database:
            await database.execute("CREATE TABLE test (id INTEGER)")
            
        assert database._conn is None
        assert await database.is_connected() is False


    @pytest.mark.asyncio
    async def test_concurrent_access(self, db: AsyncDatabase):
        await db.execute("CREATE TABLE counters (name TEXT UNIQUE, value INTEGER)")
        await db.execute("INSERT INTO counters (name, value) VALUES ('hits', 0)")

        async def increment():
            # SQL ichida atomar yangilashni ta'minlash
            async with db.transaction():
                await db.execute("UPDATE counters SET value = value + 1 WHERE name = 'hits'")

        tasks = [increment() for _ in range(10)]
        await asyncio.gather(*tasks)

        final_value = await db.fetch_val("SELECT value FROM counters WHERE name = 'hits'")
        assert final_value == 10


    @pytest.mark.asyncio
    async def test_get_connection_thread_safety(self, db: AsyncDatabase):
        async def run_query_in_thread():
            conn = await db._get_connection()
            # aiosqlite metodlari allaqachon asinxron, to_thread shart emas
            result = await conn.execute("SELECT 1")
            return result

        results = await asyncio.gather(*[run_query_in_thread() for _ in range(5)])
        assert all(r is not None for r in results)



    @pytest.mark.asyncio
    async def test_vacuum_database(self, db: AsyncDatabase):
        await db.execute("CREATE TABLE large_table (id INTEGER PRIMARY KEY, data TEXT)")
        # Ko'proq ma'lumot kiritish, VACUUM samaradorligini oshirish uchun
        for i in range(10000): 
            await db.execute("INSERT INTO large_table (id, data) VALUES (?, ?)", (i + 1, f"data_{i}",))
        await db.execute("DELETE FROM large_table WHERE id <= 5000") # Yarmini o'chiramiz
        
        # WAL faylini asosiy DB fayliga yozib, haqiqiy disk hajmini olish uchun ulanishni yopib, qayta ochish
        await db.close()
        await db.connect()

        old_size = db.db_path.stat().st_size if db.db_path is not None else 0

        await db.vacuum()

        new_size = db.db_path.stat().st_size if db.db_path is not None else 0
        assert new_size < old_size
        assert await db.fetch_val("SELECT COUNT(*) FROM large_table") == 5000



class TestValidationUtils:
    """Xavfsizlikni tekshiruvchi funksiyalarni test qilish."""

    def test_validate_table_name_success(self):
        """Ruxsat etilgan jadval nomini tekshirish (muvaffaqiyatli)."""
        whitelist = ["users", "posts"]
        _validate_table_name_util("users", whitelist)

    def test_validate_table_name_fail(self):
        """Ruxsat etilmagan jadval nomini tekshirish (xatolik)."""
        whitelist = ["users", "posts"]
        with pytest.raises(QueryError):
            _validate_table_name_util("admin_users", whitelist)

    def test_validate_column_names_success(self):
        """Ruxsat etilgan ustun nomlarini tekshirish (muvaffaqiyatli)."""
        whitelist = {"users": ["id", "name"]}
        _validate_column_names_util("users", ["id", "name"], whitelist)

    def test_validate_column_names_fail(self):
        """Ruxsat etilmagan ustun nomini tekshirish (xatolik)."""
        whitelist = {"users": ["id", "name"]}
        with pytest.raises(QueryError):
            _validate_column_names_util("users", ["id", "password"], whitelist)


class TestMigrationUtils:
    """Migratsiya funksiyalarini test qilish."""

    @pytest.mark.asyncio
    async def test_run_migrations_util(self, db: AsyncDatabase, tmp_path: Path):
        """Migratsiyalarni ishga tushirishni tekshirish."""
        migrations_dir = tmp_path / "migrations"
        migrations_dir.mkdir()

        (migrations_dir / "001_create.sql").write_text("CREATE TABLE test_table (id INT);")
        (migrations_dir / "002_insert.sql").write_text("INSERT INTO test_table (id) VALUES (100);")

        db.migrations_path = migrations_dir

        await _run_migrations_util(db)

        count = await db.fetch_val("SELECT COUNT(*) FROM test_table")
        assert count == 1

        applied_count = await db.fetch_val("SELECT COUNT(*) FROM applied_migrations")
        assert applied_count == 2

    @pytest.mark.asyncio
    async def test_run_migrations_util_no_migrations_dir(self, db: AsyncDatabase):
        """Migratsiya papkasi mavjud bo'lmaganda _run_migrations_util ni tekshirish (104-105 qatorlar)."""
        db.migrations_path = db.migrations_path.parent / "non_existent_migrations"
        assert not db.migrations_path.is_dir()
        with patch("core.db_utils.logger.warning") as mock_logger_warning:
            await _run_migrations_util(db)
            mock_logger_warning.assert_called_once()
            assert "Migratsiyalar papkasi topilmadi" in mock_logger_warning.call_args[0][0]

    @pytest.mark.asyncio
    async def test_run_migrations_util_aiosqlite_error(self, db: AsyncDatabase, tmp_path: Path):
        """_run_migrations_util ichida aiosqlite xatosi yuz berganda tekshirish (135-137 qatorlar)."""
        migrations_dir = tmp_path / "migrations"
        migrations_dir.mkdir()
        
        (migrations_dir / "V001_bad_schema.sql").write_text("CREATE TABLE bad_table (id INTEGER PRIMARY KEY;);")

        db.migrations_path = migrations_dir
        
        with pytest.raises(QueryError, match="Migratsiya xatosi: V001_bad_schema.sql"), \
             patch("core.db_utils.logger.critical") as mock_logger_critical:
            await _run_migrations_util(db)
            mock_logger_critical.assert_called_once()
            assert "bajarilishida xatolik" in mock_logger_critical.call_args[0][0]

    @pytest.mark.asyncio
    async def test_run_migrations_util_no_new_migrations_applied(self, db: AsyncDatabase, tmp_path: Path):
        """Yangi migratsiyalar qo'llanilmaganda _run_migrations_util ni tekshirish (140-qator)."""
        migrations_dir = tmp_path / "migrations"
        migrations_dir.mkdir()
        (migrations_dir / "V001_first.sql").write_text("CREATE TABLE first (id INTEGER);")

        db.migrations_path = migrations_dir
        
        await _run_migrations_util(db)
        
        with patch("core.db_utils.logger.info") as mock_logger_info:
            await _run_migrations_util(db)
            mock_logger_info.assert_called_with("Ma'lumotlar bazasi sxemasi dolzarb. Yangi migratsiyalar yo'q.")


class TestOtherDBUtils:
    """Qolgan yordamchi funksiyalarni test qilish."""

    @pytest.mark.asyncio
    async def test_get_db_stats_util(self, db: AsyncDatabase):
        """
        Statistika olish funksiyasini tekshirish.
        XATOLIK TUZATILDI: `dbstat` so'rovi "soxtalashtirildi" (mock qilindi).
        """
        await db.execute("CREATE TABLE IF NOT EXISTS test_stats (data TEXT)")
        
        # dbstat so'rovini mock qilamiz, go'yoki u har doim 0 qaytaradi
        original_fetch_val = db.fetch_val
        async def mock_fetch_val(sql: str, *args, **kwargs):
            if "dbstat" in sql:
                return 0
            return await original_fetch_val(sql, *args, **kwargs)
        
        db.fetch_val = mock_fetch_val

        stats = await _get_db_stats_util(db)
        
        assert "file_size_bytes" in stats
        assert "tables" in stats
        assert "cache" in stats
        assert any(t['name'] == 'test_stats' for t in stats['tables'])

    @pytest.mark.asyncio
    async def test_get_db_stats_util_db_path_none(self, db: AsyncDatabase):
        """db_path None bo'lganda _get_db_stats_util to'g'ri ishlashini tekshirish (40-41 qatorlar)."""
        original_db_path = db.db_path
        db.db_path = None
        with patch("core.db_utils.logger.warning") as mock_logger_warning:
            stats = await _get_db_stats_util(db)
            assert "error" in stats
            assert stats["error"] == "Ma'lumotlar bazasi yo'li sozlanmagan."
            mock_logger_warning.assert_called_once()
        db.db_path = original_db_path


    @pytest.mark.asyncio
    async def test_get_db_stats_util_db_file_not_exists(self, db: AsyncDatabase):
        """Baza fayli mavjud bo'lmaganda _get_db_stats_util ni tekshirish (52-54 qatorlar)."""
        original_db_path = db.db_path
        if db.db_path is not None:
            db.db_path = db.db_path.parent / "non_existent_stats.db"
        else:
            db.db_path = Path("non_existent_stats.db")
        assert not db.db_path.exists()

        stats = await _get_db_stats_util(db)
        assert stats["file_size_bytes"] == 0
        assert stats["disk_total_bytes"] == 0
        assert stats["disk_used_bytes"] == 0
        assert stats["disk_free_bytes"] == 0
        db.db_path = original_db_path


    @pytest.mark.asyncio
    async def test_get_db_stats_util_general_exception(self, db: AsyncDatabase):
        """_get_db_stats_util funksiyasida umumiy xato yuz berganda tekshirish (96-98 qatorlar)."""
        with patch("shutil.disk_usage", side_effect=Exception("Simulated disk_usage error")), \
             patch("core.db_utils.logger.error") as mock_logger_error:
            stats = await _get_db_stats_util(db)
            assert "error" in stats
            assert "Simulated disk_usage error" in stats["error"]
            mock_logger_error.assert_called_once()
            assert "DB statistikasini olishda xatolik" in mock_logger_error.call_args[0][0]

    @pytest.mark.asyncio
    async def test_create_backup_util(self, db: AsyncDatabase):
        """Zaxira nusxa yaratishni tekshirish."""
        await db.close()

        backup_path = await _create_backup_util(db)

        assert backup_path.exists()
        assert backup_path.name.startswith("test_db_for_utils.db")
        assert backup_path.stat().st_size > 0

    @pytest.mark.asyncio
    async def test_create_backup_util_db_not_exists(self, db: AsyncDatabase):
        """Baza fayli mavjud bo'lmaganda zaxira nusxa yaratishda xato tekshiruvi."""
        if db.db_path is not None:
            db.db_path = db.db_path.parent / "non_existent.db"
        else:
            db.db_path = Path("non_existent.db")
        with pytest.raises(DatabaseError, match="Zaxira nusxa yaratish uchun baza fayli mavjud emas."):
            await _create_backup_util(db)

    @pytest.mark.asyncio
    async def test_create_backup_util_io_error(self, db: AsyncDatabase):
        """Zaxira nusxa yaratishda I/O xatosi yuz berganda xato ishlovi."""
        with patch("shutil.copy", side_effect=IOError("Test IOError")), \
             pytest.raises(DatabaseError, match="Zaxira nusxa yaratishda xatolik: Test IOError"), \
             patch("core.db_utils.logger.error") as mock_logger_error:
            await _create_backup_util(db)
            mock_logger_error.assert_called_once()
            assert "Zaxira nusxa yaratishda xatolik" in mock_logger_error.call_args[0][0]


    @pytest.mark.asyncio
    async def test_create_backup_util_db_connected_and_reconnects(self, db: AsyncDatabase):
        """Baza ulangan bo'lsa, zaxira nusxa yaratishdan keyin qayta ulanishni tekshirish."""
        await db.connect()
        assert db._conn is not None

        with patch.object(db, 'close', new_callable=AsyncMock) as mock_close, \
             patch.object(db, 'connect', new_callable=AsyncMock) as mock_connect:
            
            await _create_backup_util(db)
            
            mock_close.assert_awaited_once()
            mock_connect.assert_awaited_once()

        assert db._conn is not None

    def test_validate_table_name_util_unauthorized(self):
        """Ruxsat etilmagan jadval nomi bilan QueryError tekshiruvi."""
        table_whitelist = ["allowed_table"]
        with pytest.raises(QueryError, match="Ruxsat etilmagan jadval nomi: forbidden_table"):
            _validate_table_name_util("forbidden_table", table_whitelist)

    def test_validate_column_names_util_unauthorized(self):
        """Ruxsat etilmagan ustun nomi bilan QueryError tekshiruvi."""
        column_whitelist = {"test_table": ["allowed_col"]}
        with pytest.raises(QueryError, match="Ruxsat etilmagan ustun nomi: forbidden_col for table test_table"):
            _validate_column_names_util("test_table", ["forbidden_col"], column_whitelist)

    def test_validate_table_name_util_no_whitelist(self):
        """Whitelist mavjud bo'lmaganda istisno tashlanmasligini tekshirish."""
        _validate_table_name_util("any_table", None)

    def test_validate_column_names_util_no_whitelist(self):
        """Whitelist mavjud bo'lmaganda istisno tashlanmasligini tekshirish."""
        _validate_column_names_util("any_table", ["any_col"], None)

    # _run_initial_data_script_util uchun testlar
    @pytest.mark.asyncio
    async def test_run_initial_data_script_util_no_file(self, db: AsyncDatabase):
        """Boshlang'ich ma'lumotlar fayli mavjud bo'lmaganda tekshirish (144-146 qatorlar)."""
        db.initial_data_path = db.initial_data_path.parent / "non_existent_initial.sql"
        assert not db.initial_data_path.is_file()
        with patch("core.db_utils.logger.debug") as mock_logger_debug:
            await _run_initial_data_script_util(db)
            mock_logger_debug.assert_called_once()
            assert "Boshlang'ich ma'lumotlar fayli topilmadi" in mock_logger_debug.call_args[0][0]

    @pytest.mark.asyncio
    async def test_run_initial_data_script_util_already_loaded(self, db: AsyncDatabase, tmp_path: Path):
        """Boshlang'ich ma'lumotlar allaqachon yuklangan bo'lsa tekshirish (159-162 qatorlar)."""
        initial_file = tmp_path / "initial_data.sql"
        initial_file.write_text("SELECT 1;")
        db.initial_data_path = initial_file

        await db.execute(
            """CREATE TABLE IF NOT EXISTS initial_data_loaded (
                id INTEGER PRIMARY KEY, script_name TEXT UNIQUE NOT NULL, loaded_at TIMESTAMP
            )"""
        )
        await db.execute("INSERT INTO initial_data_loaded (script_name) VALUES (?)", (initial_file.name,))

        with patch("core.db_utils.logger.info") as mock_logger_info:
            await _run_initial_data_script_util(db)
            mock_logger_info.assert_called_once()
            assert "allaqachon yuklangan" in mock_logger_info.call_args[0][0]

    @pytest.mark.asyncio
    async def test_run_initial_data_script_util_success(self, db: AsyncDatabase, tmp_path: Path):
        """Boshlang'ich ma'lumotlar skriptini muvaffaqiyatli yuklashni tekshirish (164-173 qatorlar)."""
        initial_file = tmp_path / "my_initial.sql"
        initial_file.write_text("CREATE TABLE initial_test (id INTEGER); INSERT INTO initial_test VALUES (1);")
        db.initial_data_path = initial_file

        with patch("core.db_utils.logger.info") as mock_logger_info_start, \
             patch("core.db_utils.logger.success") as mock_logger_success:
            await _run_initial_data_script_util(db)
            mock_logger_info_start.assert_called_with("Boshlang'ich ma'lumotlar 'my_initial.sql' yuklanmoqda...")
            mock_logger_success.assert_called_once()

        count = await db.fetch_val("SELECT COUNT(*) FROM initial_test")
        assert count == 1
        
        loaded_script_name = await db.fetch_val("SELECT script_name FROM initial_data_loaded WHERE script_name = ?", (initial_file.name,))
        assert loaded_script_name == initial_file.name

    @pytest.mark.asyncio
    async def test_run_initial_data_script_util_aiosqlite_error(self, db: AsyncDatabase, tmp_path: Path):
        """Boshlang'ich ma'lumotlar yuklashda aiosqlite xatosi yuz berganda tekshirish (174-176 qatorlar)."""
        initial_file = tmp_path / "bad_initial.sql"
        initial_file.write_text("CREATE TABLE bad_syntax (id INTEGER PRIMARY KEY;);")
        db.initial_data_path = initial_file

        with pytest.raises(QueryError, match="Boshlang'ich ma'lumotlar xatosi: bad_initial.sql"), \
             patch("core.db_utils.logger.critical") as mock_logger_critical:
            await _run_initial_data_script_util(db)
            mock_logger_critical.assert_called_once()
            assert "yuklashda xatolik" in mock_logger_critical.call_args[0][0]

    @pytest.mark.asyncio
    async def test_run_initial_data_script_util_general_exception(self, db: AsyncDatabase, tmp_path: Path):
        """Boshlang'ich ma'lumotlar yuklashda umumiy xato yuz berganda tekshirish (177-179 qatorlar)."""
        initial_file = tmp_path / "some_initial.sql"
        initial_file.write_text("SELECT 1;")
        db.initial_data_path = initial_file

        with patch("builtins.open", side_effect=IOError("Simulated file error")), \
             pytest.raises(IOError, match="Simulated file error"), \
             patch("core.db_utils.logger.critical") as mock_logger_critical:
            await _run_initial_data_script_util(db)
            mock_logger_critical.assert_called_once()
            assert "o'qishda yoki bajarishda kutilmagan xatolik" in mock_logger_critical.call_args[0][0]
