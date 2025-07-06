import pytest
import asyncio
from pathlib import Path
from typing import AsyncGenerator, Optional, List, Dict
from unittest.mock import MagicMock, AsyncMock, patch

import pytest_asyncio

from core.database import AsyncDatabase
from core.exceptions import QueryError, DatabaseError, DBConnectionError
from core.config_manager import ConfigManager
from core.cache import CacheManager
from core.config import BASE_DIR
import aiosqlite
import shutil

pytestmark = pytest.mark.asyncio


pytestmark = pytest.mark.asyncio


@pytest.fixture
def mock_config_manager() -> MagicMock:
    """Soxta (mock) ConfigManager obyektini yaratadi."""
    mock = MagicMock(spec=ConfigManager)
    mock.get.side_effect = lambda key, default=None: {
        "DB_TABLE_WHITELIST": ["users", "settings", "text_log_ignored_users", "task_logs", "text_log_settings", "large_data", "backup_test"],
        "DB_COLUMN_WHITELIST": {
            "users": ["id", "name", "age", "email"],
            "settings": ["key", "value"],
            "text_log_ignored_users": ["user_id"],
            "task_logs": ["id", "task_key", "duration_ms", "status", "details", "logged_at"],
            "text_log_settings": ["chat_id", "setting_key", "setting_value"],
            "large_data": ["id", "content"],
            "backup_test": ["id"],
        },
    }.get(key, default)
    return mock


@pytest.fixture
def mock_cache_manager() -> AsyncMock:
    """Soxta (mock) CacheManager obyektini yaratadi."""
    mock = AsyncMock(spec=CacheManager)
    mock.get.return_value = None
    return mock


@pytest_asyncio.fixture
async def db(
    tmp_path: Path,
    mock_config_manager: MagicMock,
    mock_cache_manager: AsyncMock,
    monkeypatch,
) -> AsyncGenerator[AsyncDatabase, None]:
    """
    Har bir test uchun yangi ma'lumotlar bazasini yaratadi.
    Haqiqiy migratsiyalar ishga tushmasligi uchun monkeypatch orqali bloklanadi.
    """

    async def mock_do_nothing(*args, **kwargs):
        pass

    monkeypatch.setattr("core.database._run_migrations_util", mock_do_nothing)
    monkeypatch.setattr("core.database._run_initial_data_script_util", mock_do_nothing)

    db_path = tmp_path / "test.db"
    database = AsyncDatabase(config_manager=mock_config_manager, cache_manager=mock_cache_manager)
    database.configure(db_path=db_path)

    await database.connect()

    await database.execute(
        """
        CREATE TABLE users (
            id INTEGER PRIMARY KEY,
            name TEXT NOT NULL UNIQUE, -- 'name' ustuniga UNIQUE qo'shildi
            age INTEGER,
            email TEXT UNIQUE
        );
        """
    )
    await database.execute(
        "INSERT INTO users (name, age, email) VALUES (?, ?, ?)",
        ("John Doe", 30, "john.doe@example.com"),
    )

    await database._conn.commit()  # type: ignore

    yield database

    await database.close()


class TestAsyncDatabase:
    """AsyncDatabase klassining funksionalligini test qilish."""

    async def test_connection(self, db: AsyncDatabase):
        assert db._conn is not None
        await db.close()
        assert db._conn is None

    async def test_execute_and_fetchone(self, db: AsyncDatabase):
        user = await db.fetchone("SELECT * FROM users WHERE name = ?", ("John Doe",))
        assert user is not None
        assert user["name"] == "John Doe"

    async def test_fetchall(self, db: AsyncDatabase):
        await db.execute("INSERT INTO users (name, age) VALUES (?, ?)", ("Jane Doe", 28))
        users = await db.fetchall("SELECT * FROM users ORDER BY age")
        assert len(users) == 2
        assert users[0]["name"] == "Jane Doe"

    async def test_fetch_val(self, db: AsyncDatabase):
        count = await db.fetch_val("SELECT COUNT(*) FROM users")
        assert count == 1

    async def test_insert_helper(self, db: AsyncDatabase):
        new_id = await db.insert("users", {"name": "Peter Pan", "age": 12})
        assert new_id is not None
        user = await db.fetchone("SELECT * FROM users WHERE id = ?", (new_id,))
        assert user is not None
        assert user["name"] == "Peter Pan"

    async def test_update_helper(self, db: AsyncDatabase):
        rows_affected = await db.update("users", {"age": 31}, "name = ?", ("John Doe",))
        assert rows_affected == 1
        user = await db.fetchone("SELECT age FROM users WHERE name = ?", ("John Doe",))
        assert user is not None
        assert user["age"] == 31

    async def test_transaction_commit(self, db: AsyncDatabase):
        """
        XATOLIK TUZATILDI: Tranzaksiya `cursor` orqali boshqariladi.
        """
        async with db.transaction() as cursor:
            await cursor.execute("UPDATE users SET age = ? WHERE name = ?", (99, "John Doe"))

        user = await db.fetchone("SELECT age FROM users WHERE name = 'John Doe'")
        assert user is not None
        assert user['age'] == 99

    async def test_transaction_rollback(self, db: AsyncDatabase):
        """
        XATOLIK TUZATILDI: Tranzaksiya `cursor` orqali boshqariladi,
        bu esa `ROLLBACK` to'g'ri ishlashini ta'minlaydi.
        """
        initial_age = await db.fetch_val("SELECT age FROM users WHERE name = 'John Doe'")
        assert initial_age == 30

        with pytest.raises(ValueError):
            async with db.transaction() as cursor:
                await cursor.execute("UPDATE users SET age = ? WHERE name = ?", (55, "John Doe"))
                raise ValueError("Test xatoligi")

        current_age = await db.fetch_val("SELECT age FROM users WHERE name = 'John Doe'")
        assert current_age == initial_age

    async def test_whitelisting_table_fail(self, db: AsyncDatabase):
        with pytest.raises(QueryError):
            await db.insert("secrets", {"key": "123"})

    async def test_whitelisting_column_fail(self, db: AsyncDatabase):
        with pytest.raises(QueryError):
            await db.insert("users", {"name": "Hacker", "malicious_data": "exploit"})

    async def test_caching(self, db: AsyncDatabase, mock_cache_manager: AsyncMock):
        query = "SELECT * FROM users WHERE name = ?"
        params = ("John Doe",)

        await db.fetchone(query, params, use_cache=True)
        mock_cache_manager.get.assert_called_once()
        mock_cache_manager.set.assert_called_once()

        mock_cache_manager.reset_mock()
        mock_cache_manager.get.return_value = {"id": 1, "name": "Cached User"}

        cached_user = await db.fetchone(query, params, use_cache=True)
        assert cached_user['name'] == "Cached User"  # type: ignore
        mock_cache_manager.get.assert_called_once()
        mock_cache_manager.set.assert_not_called()

        mock_cache_manager.reset_mock()
        mock_cache_manager.get.return_value = [{"id": 1, "name": "Cached User A"}, {"id": 2, "name": "Cached User B"}]
        cached_users = await db.fetchall(query, params, use_cache=True)
        assert len(cached_users) == 2
        mock_cache_manager.get.assert_called_once()
        mock_cache_manager.set.assert_not_called()

        mock_cache_manager.reset_mock()
        mock_cache_manager.get.return_value = "Cached Value"
        cached_val = await db.fetch_val(query, params, use_cache=True)
        assert cached_val == "Cached Value"
        mock_cache_manager.get.assert_called_once()
        mock_cache_manager.set.assert_not_called()

    async def test_clear_cache(self, db: AsyncDatabase, mock_cache_manager: AsyncMock):
        db.clear_cache()
        mock_cache_manager.clear_namespace.assert_called_once_with("db_queries")

    async def test_insert(self, db: AsyncDatabase):
        last_id = await db.insert("users", {"name": "Test User", "age": 30})
        assert last_id is not None
        user = await db.fetchone("SELECT * FROM users WHERE id = ?", (last_id,))
        assert user['name'] == "Test User"  # type: ignore
        assert user['age'] == 30  # type: ignore

    async def test_update(self, db: AsyncDatabase):
        await db.insert("users", {"name": "Update Me", "age": 25})
        rows_affected = await db.update("users", {"age": 26}, "name = ?", ("Update Me",))
        assert rows_affected == 1
        user = await db.fetchone("SELECT * FROM users WHERE name = ?", ("Update Me",))
        assert user['age'] == 26  # type: ignore

    async def test_upsert(self, db: AsyncDatabase):

        last_id = await db.upsert("users", {"name": "Upsert User", "age": 40}, ["name"])
        assert last_id is not None
        user = await db.fetchone("SELECT * FROM users WHERE name = ?", ("Upsert User",))
        assert user['age'] == 40  # type: ignore

        rows_affected = await db.upsert("users", {"name": "Upsert User", "age": 41, "email": "test@example.com"}, ["name"])

        user = await db.fetchone("SELECT * FROM users WHERE name = ?", ("Upsert User",))
        assert user['age'] == 41  # type: ignore
        assert user['email'] == "test@example.com"  # type: ignore
        assert rows_affected == user['id']  # type: ignore

    async def test_vacuum(self, db: AsyncDatabase):

        await db.execute("CREATE TABLE IF NOT EXISTS large_data (id INTEGER PRIMARY KEY, content TEXT)")
        for i in range(1000):
            await db.execute("INSERT INTO large_data (id, content) VALUES (?, ?)", (i, "x" * 100))

        await db.execute("DELETE FROM large_data WHERE id < 500")

        await db.close()
        await db.connect()

        old_size = db.db_path.stat().st_size  # type: ignore

        await db.vacuum()

        new_size = db.db_path.stat().st_size  # type: ignore
        assert new_size < old_size, f"VACUUM file size did not decrease. Old: {old_size}, New: {new_size}"
        assert await db.fetch_val("SELECT COUNT(*) FROM large_data") == 500

    async def test_log_task_execution(self, db: AsyncDatabase):

        await db.execute(
            """
            CREATE TABLE IF NOT EXISTS task_logs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                task_key TEXT NOT NULL,
                duration_ms REAL NOT NULL,
                status TEXT NOT NULL,
                details TEXT,
                logged_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """
        )
        await db.log_task_execution("my_task", 123.45, "SUCCESS", "Details here")
        log_entry = await db.fetchone("SELECT * FROM task_logs WHERE task_key = ?", ("my_task",))
        assert log_entry is not None
        assert log_entry['status'] == "SUCCESS"

    async def test_create_backup(self, db: AsyncDatabase, tmp_path: Path):
        db.backup_dir = tmp_path / "backups_for_test_create"
        db.backup_dir.mkdir(exist_ok=True)
        await db.execute("CREATE TABLE backup_test (id INTEGER)")
        await db.execute("INSERT INTO backup_test (id) VALUES (1)")

        await db.close()

        backup_path = await db.create_backup()
        assert backup_path.exists()
        assert backup_path.name.startswith("test.db")
        assert backup_path.stat().st_size > 0

        await db.connect()
        assert db._conn is not None
        assert await db.is_connected() is True
        count = await db.fetch_val("SELECT COUNT(*) FROM backup_test")
        assert count == 1

    async def test_register_cleanup_table(self, db: AsyncDatabase):
        db.register_cleanup_table("old_messages", "message_date")
        configs = db.get_cleanup_configurations()
        assert "old_messages" in configs
        assert configs["old_messages"] == "message_date"

        with patch("core.database.logger.warning") as mock_logger_warning:
            db.register_cleanup_table("old_messages", "another_date_column")
            mock_logger_warning.assert_called_once()
            configs = db.get_cleanup_configurations()
            assert configs["old_messages"] == "another_date_column"

    async def test_get_log_text_settings(self, db: AsyncDatabase):

        await db.execute(
            """
            CREATE TABLE IF NOT EXISTS text_log_settings (
                chat_id INTEGER PRIMARY KEY,
                setting_key TEXT,
                setting_value TEXT
            )
        """
        )
        await db.execute("INSERT INTO text_log_settings (chat_id, setting_key, setting_value) VALUES (?, ?, ?)", (123, "enabled", "1"))

        settings = await db.get_log_text_settings(123)
        assert settings is not None
        assert settings['chat_id'] == 123
        assert settings['setting_key'] == "enabled"

        no_settings = await db.get_log_text_settings(999)
        assert no_settings is None

    async def test_add_text_log_ignored_user(self, db: AsyncDatabase):

        await db.execute(
            """
            CREATE TABLE IF NOT EXISTS text_log_ignored_users (
                user_id INTEGER PRIMARY KEY
            )
        """
        )
        last_id = await db.add_text_log_ignored_user(456)
        assert last_id == 456

        ignored_user = await db.fetchone("SELECT * FROM text_log_ignored_users WHERE user_id = ?", (456,))
        assert ignored_user is not None
        assert ignored_user['user_id'] == 456

        with pytest.raises(QueryError):
            await db.add_text_log_ignored_user(456)

    async def test_retry_on_lock_generic_exception(self, db: AsyncDatabase):

        with patch.object(db._conn, 'execute', side_effect=ValueError("generic error")):
            with pytest.raises(QueryError, match="So'rovni bajarishda kutilmagan xatolik: generic error"):
                await db.execute("SELECT 1")

    async def test_connect_error(self, tmp_path: Path, mock_config_manager: MagicMock, mock_cache_manager: AsyncMock):
        db_path = tmp_path / "connect_error.db"
        database = AsyncDatabase(config_manager=mock_config_manager, cache_manager=mock_cache_manager)
        database.configure(db_path=db_path)

        with patch('aiosqlite.connect', side_effect=aiosqlite.Error("test connect error")):
            with pytest.raises(DBConnectionError, match="test connect error"):
                await database.connect()
            assert database._conn is None

    async def test_close_wal_checkpoint_error(self, db: AsyncDatabase):

        await db.connect()

        with patch.object(db._conn, 'executescript', side_effect=AsyncMock(side_effect=aiosqlite.Error("wal error"))) as mock_executescript:
            with patch("core.database.logger.warning") as mock_logger_warning:
                await db.close()
                mock_executescript.assert_called_once_with("PRAGMA wal_checkpoint(TRUNCATE);")
                mock_logger_warning.assert_called_once_with(f"WAL checkpointni bajarishda xatolik: wal error")
            assert db._conn is None

    async def testis_connected_error(self, db: AsyncDatabase):

        await db.connect()

        with patch.object(db._conn, 'execute', side_effect=aiosqlite.OperationalError("db closed")):
            assert await db.is_connected() is False

        with patch.object(db._conn, 'execute', side_effect=aiosqlite.ProgrammingError("programming error")):
            assert await db.is_connected() is False

    async def test_get_connection_error_no_conn(self, tmp_path: Path, mock_config_manager: MagicMock, mock_cache_manager: AsyncMock):
        db_path = tmp_path / "no_conn.db"
        database = AsyncDatabase(config_manager=mock_config_manager, cache_manager=mock_cache_manager)
        database.configure(db_path=db_path)
        database._conn = None

        with patch.object(database, 'connect', side_effect=DBConnectionError("failed to connect")):
            with pytest.raises(DBConnectionError, match="failed to connect"):
                await database._get_connection()

    async def test_configure_warning(self, tmp_path: Path, mock_config_manager: MagicMock, mock_cache_manager: AsyncMock):
        db_path_1 = tmp_path / "test1.db"
        db_path_2 = tmp_path / "test2.db"
        database = AsyncDatabase(config_manager=mock_config_manager, cache_manager=mock_cache_manager)
        database.configure(db_path=db_path_1)
        with patch("core.database.logger.warning") as mock_logger_warning:
            database.configure(db_path=db_path_2)
            mock_logger_warning.assert_called_once()
            assert f"Ma'lumotlar bazasi yo'li '{db_path_1}' dan '{db_path_2}' ga qayta sozlanmoqda." in mock_logger_warning.call_args[0][0]

    async def test_configure_uses_config_manager_defaults(self, tmp_path: Path):
        mock_config = MagicMock(spec=ConfigManager)

        mock_config.get.side_effect = lambda key, default=None: {
            "DB_TABLE_WHITELIST": None,
            "DB_COLUMN_WHITELIST": None,
        }.get(key, default)

        mock_cache = AsyncMock(spec=CacheManager)

        db_path = tmp_path / "test_config_defaults.db"
        database = AsyncDatabase(config_manager=mock_config, cache_manager=mock_cache)

        with patch.object(database, '_config_manager', mock_config):
            database.configure(db_path=db_path)

            assert database._table_whitelist is None
            assert database._column_whitelist == {}
            mock_config.get.assert_any_call("DB_TABLE_WHITELIST")
            mock_config.get.assert_any_call("DB_COLUMN_WHITELIST")

    async def test_fetchone_cache_no_result_no_set(self, db: AsyncDatabase, mock_cache_manager: AsyncMock):
        mock_cache_manager.get.return_value = None

        with patch.object(db, 'execute', return_value=AsyncMock(fetchone=AsyncMock(return_value=None))):
            result = await db.fetchone("SELECT * FROM users WHERE id = ?", (999,), use_cache=True)
            assert result is None
            mock_cache_manager.get.assert_called_once()
            mock_cache_manager.set.assert_not_called()

    async def test_fetchall_cache_no_result_no_set(self, db: AsyncDatabase, mock_cache_manager: AsyncMock):
        mock_cache_manager.get.return_value = None

        with patch.object(db, 'execute', return_value=AsyncMock(fetchall=AsyncMock(return_value=[]))):
            result = await db.fetchall("SELECT * FROM users WHERE name LIKE 'NonExistent%'", use_cache=True)
            assert result == []
            mock_cache_manager.get.assert_called_once()
            mock_cache_manager.set.assert_not_called()

    async def test_fetch_val_cache_no_result_no_set(self, db: AsyncDatabase, mock_cache_manager: AsyncMock):
        mock_cache_manager.get.return_value = None

        with patch.object(db, 'execute', return_value=AsyncMock(fetchone=AsyncMock(return_value=None))):
            result = await db.fetch_val("SELECT age FROM users WHERE id = ?", (999,), use_cache=True)
            assert result is None
            mock_cache_manager.get.assert_called_once()
            mock_cache_manager.set.assert_not_called()

    async def test_log_task_execution_error(self, db: AsyncDatabase):
        with patch.object(db, 'execute', side_effect=Exception("log error")), patch("core.database.logger.error") as mock_logger_error:
            await db.log_task_execution("failed_task", 10.0, "FAILED")
            mock_logger_error.assert_called_once()
            assert "Vazifa 'failed_task' uchun log yozishda xatolik" in mock_logger_error.call_args[0][0]

    async def test_create_backup_error(self, db: AsyncDatabase, tmp_path: Path):
        db.backup_dir = tmp_path / "backups_error"
        db.backup_dir.mkdir(exist_ok=True)

        (tmp_path / "test.db").touch()
        db.db_path = tmp_path / "test.db"

        with patch("shutil.copy", side_effect=IOError("backup copy error")), pytest.raises(DatabaseError, match="Zaxira nusxa yaratishda xatolik: backup copy error"), patch("core.database.logger.error") as mock_logger_error:
            await db.create_backup()
            mock_logger_error.assert_called_once()
            assert "Zaxira nusxa yaratishda xatolik" in mock_logger_error.call_args[0][0]

    async def test_database_init_base_dir_path(self, tmp_path: Path, mock_config_manager: MagicMock, mock_cache_manager: AsyncMock):

        with patch('core.database.BASE_DIR', tmp_path):
            database = AsyncDatabase(config_manager=mock_config_manager, cache_manager=mock_cache_manager)

            database.configure(db_path=tmp_path / "dummy_test.db")

            expected_backup_dir = tmp_path / "data" / "backups"
            assert database.backup_dir == expected_backup_dir

            assert database.backup_dir.is_dir()

            assert database.initial_data_path == tmp_path / "data" / "initial_data.sql"
            assert database.migrations_path == tmp_path / "data" / "migrations"
