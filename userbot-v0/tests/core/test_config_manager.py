# tests/core/test_config_manager.py (ENG SO'NGGI, SODDA VA ISHONCHLI VERSIYA)

import pytest
import asyncio
from unittest.mock import MagicMock, AsyncMock, patch, Mock, ANY
from pydantic import SecretStr
from pathlib import Path
import json

import pytest_asyncio

# Test qilinadigan asosiy sinflar
from core.config_manager import ConfigManager
from core.config import StaticSettings
from core.database import AsyncDatabase
from core.exceptions import DatabaseError

# --- Sozlamalar (Fixtures) ---

@pytest.fixture
def mock_static_settings(tmp_path: Path) -> MagicMock:
    """Soxta (mock) StaticSettings obyektini yaratadi."""
    settings = MagicMock(spec=StaticSettings)
    settings.OWNER_ID = 12345
    settings.LOG_LEVEL = "INFO"
    settings.GEMINI_API_KEY = SecretStr("static_secret_key")
    settings.DB_PATH = tmp_path / "test.db"
    settings.DB_TABLE_WHITELIST = ["dynamic_settings"]
    settings.DB_COLUMN_WHITELIST = {"dynamic_settings": ["key", "value", "type", "description", "last_modified"]}
    settings.model_fields = {'OWNER_ID': None, 'LOG_LEVEL': None, 'GEMINI_API_KEY': None, 'DB_PATH': None, 'DB_TABLE_WHITELIST': None, 'DB_COLUMN_WHITELIST': None}
    return settings

@pytest.fixture
def mock_db() -> AsyncMock:
    """Soxta (mock) AsyncDatabase obyektini yaratadi."""
    db = AsyncMock(spec=AsyncDatabase)
    db.fetchall.return_value = []
    db.execute.return_value = 1
    db.configure = MagicMock()
    return db

@pytest_asyncio.fixture
async def config_manager(
    mock_static_settings: MagicMock, mock_db: AsyncMock
) -> ConfigManager:
    """Har bir test uchun yangi, toza ConfigManager obyektini yaratadi."""
    manager = ConfigManager(static_config=mock_static_settings)
    manager.set_db_instance(db_instance=mock_db)
    # Testdan oldin DB yuklanganini bildiramiz
    manager._db_loaded_event.set()
    return manager


# --- Testlar ---

# 1. Oddiy, sinxron testlar uchun alohida klass
class TestStaticAndCasting:
    """Sinxron metodlarni, xususan, _cast_value ni to'g'ridan-to'g'ri tekshiradi."""

    def test_get_static_setting(self, config_manager: ConfigManager):
        assert config_manager.get("LOG_LEVEL") == "INFO"

    def test_get_static_secret_setting(self, config_manager: ConfigManager):
        assert config_manager.get("GEMINI_API_KEY") == "static_secret_key"

    def test_get_non_existent_key_with_default(self, config_manager: ConfigManager):
        assert config_manager.get("non_existent_key", default="ok") == "ok"
    
    def test_cast_value_logic(self, config_manager: ConfigManager):
        """_cast_value funksiyasini to'g'ridan-to'g'ri tekshirish."""
        assert config_manager._cast_value("123", "int") == 123
        assert config_manager._cast_value("true", "bool") is True
        assert config_manager._cast_value("false", "bool") is False
        assert config_manager._cast_value('{"a": 1}', "json") == {"a": 1}
        assert isinstance(config_manager._cast_value("secret", "SecretStr"), SecretStr)
        assert config_manager._cast_value("1.23", "float") == 1.23
        assert config_manager._cast_value("hello", "str") == "hello"

    def test_cast_value_handles_errors(self, config_manager: ConfigManager):
        """_cast_value xato holatlarda ogohlantirish berib, asl qiymatni qaytarishini tekshirish."""
        with patch("core.config_manager.logger.warning") as mock_warn:
            # Xato int qiymat
            assert config_manager._cast_value("abc", "int") == "abc"
            # Xato json qiymat
            assert config_manager._cast_value("{'a':1}", "json") == "{'a':1}"
            
            # Ogohlantirish 2 marta chaqirilganini tekshiramiz
            assert mock_warn.call_count == 2
    
    def test_get_all_configs_basic(self, config_manager: ConfigManager):
        """Barcha konfiguratsiyalarni olishni tekshiradi, shu jumladan SecretStr ni ochish."""
        all_configs = config_manager.get_all_configs()
        assert all_configs["OWNER_ID"] == 12345
        assert all_configs["LOG_LEVEL"] == "INFO"
        assert all_configs["GEMINI_API_KEY"] == "static_secret_key" # SecretStr ochilgan holda
        assert "user_theme" not in all_configs # Hali dinamik sozlama o'rnatilmagan

    def test_get_type_str_all_types(self, config_manager: ConfigManager):
        """_get_type_str metodini barcha qo'llab-quvvatlanadigan turlar uchun tekshirish."""
        assert config_manager._get_type_str([]) == "json"
        assert config_manager._get_type_str({}) == "json"
        assert config_manager._get_type_str(True) == "bool"
        assert config_manager._get_type_str(123) == "int"
        assert config_manager._get_type_str(1.23) == "float"
        assert config_manager._get_type_str(SecretStr("s")) == "SecretStr"
        assert config_manager._get_type_str("hello") == "str"
        assert config_manager._get_type_str(None) == "str" # Default for None, if not explicitly handled


# 2. Asinxron va DB bilan bog'liq testlar uchun alohida klass
@pytest.mark.asyncio
class TestAsyncOperations:
    """Asinxron va ma'lumotlar bazasi bilan ishlaydigan metodlarni test qiladi."""

    async def test_set_and_get_dynamic(self, config_manager: ConfigManager):
        await config_manager.set("user_theme", "dark")
        assert config_manager.get("user_theme") == "dark"

    async def test_dynamic_overrides_static(self, config_manager: ConfigManager):
        await config_manager.set("LOG_LEVEL", "DEBUG")
        assert config_manager.get("LOG_LEVEL") == "DEBUG"

    async def test_load_dynamic_settings(self, config_manager: ConfigManager, mock_db: AsyncMock):
        mock_db.fetchall.return_value = [{"key": "lang", "value": "uz", "type": "str"}]
        await config_manager.load_dynamic_settings()
        assert config_manager.get("lang") == "uz"

    async def test_delete_dynamic_setting(self, config_manager: ConfigManager, mock_db: AsyncMock):
        await config_manager.set("key_to_delete", "value")
        mock_db.execute.return_value = 1
        assert await config_manager.delete("key_to_delete") is True
        assert config_manager.get("key_to_delete") is None
    
    async def test_runtime_error_if_db_not_set(self, mock_static_settings: MagicMock):
        manager = ConfigManager(static_config=mock_static_settings) # DB yo'q
        with pytest.raises(RuntimeError):
            await manager.set("k", "v")
            
    async def test_db_init_error_is_critical(self, config_manager: ConfigManager, mock_db: AsyncMock):
        """Jadval yaratishda xato bo'lsa, 'critical' log yozilishini tekshirish."""
        mock_db.execute.side_effect = Exception("DB is on fire")
        with patch("core.config_manager.logger.critical") as mock_log, pytest.raises(DatabaseError):
            await config_manager.initialize_db_schema()
            mock_log.assert_called_once()
            
    async def test_wait_for_load(self, config_manager: ConfigManager):
        """`wait_for_load` metodi `_db_loaded_event`ni kutishini tekshirish."""
        config_manager._db_loaded_event.clear()
        
        # Fon vazifasini yaratib, uni kutamiz
        load_task = asyncio.create_task(config_manager.load_dynamic_settings())
        await config_manager.wait_for_load() # Bu metod event o'rnatilguncha kutadi
        
        # Vazifa tugaganiga ishonch hosil qilamiz
        await load_task
        assert config_manager._db_loaded_event.is_set()

    async def test_set_db_instance_warning(self, config_manager: ConfigManager, mock_db: AsyncMock):
        """Database instansi allaqachon o'rnatilganida ogohlantirish berilishini tekshiradi."""
        with patch("core.config_manager.logger.warning") as mock_warn:
            config_manager.set_db_instance(mock_db) # Ikkinchi marta o'rnatish
            mock_warn.assert_called_once()
            assert "Database instansi allaqachon o'rnatilgan." in mock_warn.call_args[0][0]

    async def test_initialize_db_schema_no_db_instance(self, mock_static_settings: MagicMock):
        """DB instansi o'rnatilmaganda initialize_db_schema RuntimeError berishini tekshiradi."""
        manager = ConfigManager(static_config=mock_static_settings)
        with patch("core.config_manager.logger.error") as mock_error, pytest.raises(RuntimeError):
            await manager.initialize_db_schema()
            mock_error.assert_called_once()
            assert "Database instansi o'rnatilmagan." in mock_error.call_args[0][0]

    async def test_load_dynamic_settings_db_not_set(self, mock_static_settings: MagicMock, mock_db: AsyncMock):
        """load_dynamic_settings db instansi o'rnatilmaganda to'g'ri ishlashini tekshiradi."""
        manager = ConfigManager(static_config=mock_static_settings)
        manager._db_instance = None # initialize_db_schema ni chetlab o'tish uchun DB ni None qildik

        with patch.object(manager, 'initialize_db_schema', new=AsyncMock()): # initialize_db_schema ni mockladik, xato bermasligi uchun
            with patch("core.config_manager.logger.error") as mock_error:
                await manager.load_dynamic_settings() # DB o'rnatilmagan
                mock_error.assert_called_once()
                assert "Database instansi o'rnatilmagan" in mock_error.call_args[0][0]
            assert manager._db_loaded_event.is_set() # Event set bo'lishi kerak

    async def test_load_dynamic_settings_db_error(self, config_manager: ConfigManager, mock_db: AsyncMock):
        """load_dynamic_settings da fetchall xato berganda 'error' log yozilishini tekshiradi."""
        mock_db.fetchall.side_effect = Exception("DB connection lost")
        with patch("core.config_manager.logger.error") as mock_error:
            await config_manager.load_dynamic_settings()
            mock_error.assert_called_once()
            assert "Dinamik sozlamalarni yuklashda xatolik:" in mock_error.call_args[0][0]
        assert config_manager._db_loaded_event.is_set() # Event set bo'lishi kerak

    async def test_load_dynamic_settings_cast_error(self, config_manager: ConfigManager, mock_db: AsyncMock):
        """load_dynamic_settings ichida _cast_value xato berganda log yozilishini tekshiradi."""
        mock_db.fetchall.return_value = [{"key": "bad_int", "value": "not_an_int", "type": "int"}]
        with patch("core.config_manager.logger.error") as mock_error, patch("core.config_manager.logger.warning") as mock_warn:
            await config_manager.load_dynamic_settings()
            mock_warn.assert_called_once()
            assert "Qiymat 'not_an_int'ni tur 'int' ga o'girishda xato: invalid literal for int() with base 10: 'not_an_int'. String sifatida qaytariladi." in mock_warn.call_args[0][0]
            mock_error.assert_not_called()
        assert config_manager.get("bad_int") == "not_an_int" # Assertionni to'g'riladik

    async def test_set_no_db_instance(self, mock_static_settings: MagicMock):
        """DB instansi o'rnatilmaganda set RuntimeErrors berishini tekshiradi."""
        manager = ConfigManager(static_config=mock_static_settings)
        with patch("core.config_manager.logger.error") as mock_error, pytest.raises(RuntimeError):
            await manager.set("some_key", "some_value")
            mock_error.assert_called_once()
            assert "Database instansi o'rnatilmagan" in mock_error.call_args[0][0]

    async def test_delete_no_db_instance(self, mock_static_settings: MagicMock):
        """DB instansi o'rnatilmaganda delete RuntimeErrors berishini tekshiradi."""
        manager = ConfigManager(static_config=mock_static_settings)
        with patch("core.config_manager.logger.error") as mock_error, pytest.raises(RuntimeError):
            await manager.delete("some_key")
            mock_error.assert_called_once()
            assert "Database instansi o'rnatilmagan" in mock_error.call_args[0][0]

    async def test_delete_setting_not_found(self, config_manager: ConfigManager, mock_db: AsyncMock):
        """Dinamik sozlama topilmaganda delete False qaytarishini tekshiradi."""
        mock_db.execute.return_value = 0
        assert await config_manager.delete("non_existent_key") is False
        mock_db.execute.assert_called_once_with("DELETE FROM dynamic_settings WHERE key = ?", ("non_existent_key",))

    @pytest.mark.parametrize("key_name, value, expected_type_str", [
        ("json_setting", {"data": [1, 2], "type": "test"}, "json"),
        ("bool_setting", True, "bool"),
        ("secret_setting", SecretStr("my_secret_token"), "SecretStr"),
        ("int_setting", 123, "int"),
        ("float_setting", 1.23, "float"),
        ("str_setting", "hello", "str")
    ])
    async def test_set_with_various_types(self, config_manager: ConfigManager, mock_db: AsyncMock, key_name, value, expected_type_str):
        """Har xil turdagi qiymatlarni saqlashni tekshiradi."""
        await config_manager.set(key_name, value)
        
        # get() SecretStr ni ochib berishini tekshirish
        expected_get_value = value.get_secret_value() if isinstance(value, SecretStr) else value
        assert config_manager.get(key_name) == expected_get_value

        # DBga to'g'ri qiymat va tur saqlanganligini tekshirish
        expected_db_value = value.get_secret_value() if isinstance(value, SecretStr) else (json.dumps(value, ensure_ascii=False) if expected_type_str == "json" else str(value))
        
        mock_db.execute.assert_called_with(
            ANY, # SQL
            (key_name, expected_db_value, expected_type_str, None, None)
        )
        mock_db.execute.reset_mock() # Ikkinchi chaqiruvni to'g'ri tekshirish uchun reset

    async def test_load_dynamic_settings_with_secret_str(self, config_manager: ConfigManager, mock_db: AsyncMock):
        """SecretStr turidagi qiymatni yuklash va keshda SecretStr obyektiga aylantirishni tekshiradi."""
        mock_db.fetchall.return_value = [{"key": "my_secret_key_db", "value": "loaded_secret", "type": "SecretStr"}]
        await config_manager.load_dynamic_settings()
        loaded_secret = config_manager.get("my_secret_key_db")
        assert isinstance(config_manager._cache["my_secret_key_db"], SecretStr) # Keshda SecretStr bo'lishi kerak
        assert loaded_secret == SecretStr("loaded_secret").get_secret_value() # .get_secret_value() qo'shildi

    async def test_get_all_configs_with_dynamic(self, config_manager: ConfigManager, mock_db: AsyncMock):
        """Dinamik sozlamalar ham all_configs ga qo'shilishini tekshiradi."""
        await config_manager.set("user_theme", "light")
        all_configs = config_manager.get_all_configs()
        assert all_configs["user_theme"] == "light"
        assert all_configs["LOG_LEVEL"] == "INFO" # Dinamik statikni o'zgartirmasligi kerak, faqat ustidan yozishi

