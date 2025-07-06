# tests/core/test_main.py (To'liq yangilangan va kengaytirilgan versiya)

import pytest
import asyncio
from unittest.mock import patch, MagicMock, AsyncMock, call

# Loyihaning asosiy funksiyalarini testlash uchun import qilamiz
from main import create_application_instance, run_application_lifecycle, entrypoint

# Barcha testlarni asinxron rejimda ishga tushirish uchun belgi
pytestmark = pytest.mark.asyncio


@pytest.fixture
def mock_static_settings():
    """Soxta `StaticSettings` obyektini yaratadi."""
    settings = MagicMock()
    settings.LOG_FILE_PATH = "dummy_log.log"
    settings.LOG_LEVEL = "DEBUG"
    return settings


@pytest.fixture
def mock_dependencies():
    """
    `main.py`dagi barcha asosiy klasslar uchun "patch" (soxta obyekt) yaratadi.
    Bu bizga haqiqiy DB yoki Telegram klientisiz test qilish imkonini beradi.
    """
    with patch('main.ConfigManager') as mock_config_manager, \
         patch('main.CacheManager') as mock_cache_manager, \
         patch('main.AsyncDatabase') as mock_db, \
         patch('main.AppState') as mock_state, \
         patch('main.TaskRegistry') as mock_tasks, \
         patch('main.SchedulerManager') as mock_scheduler, \
         patch('main.AIService') as mock_ai, \
         patch('main.ClientManager') as mock_client_manager, \
         patch('main.PluginManager') as mock_plugin_manager, \
         patch('main.Application') as mock_app_class, \
         patch('main.asyncio.sleep', new_callable=AsyncMock) as mock_sleep:

        # Har bir soxta klass chaqirilganda, qaytariladigan soxta instansiyalarni yaratamiz
        mock_state_instance = AsyncMock(name="StateInstance")
        # Standart holatda `get` metodi "qayta ishga tushirish shart emas" (False) degan qiymat qaytaradi
        mock_state_instance.get.return_value = False
        mock_state.return_value = mock_state_instance
        
        mock_db_instance = AsyncMock(name="DBInstance")
        mock_db_instance.register_cleanup_table = MagicMock()
        mock_db.return_value = mock_db_instance

        mock_app_instance = AsyncMock(name="AppInstance")
        mock_app_class.return_value = mock_app_instance
        
        # Barcha soxta obyektlarni test funksiyalarida ishlatish uchun lug'at ko'rinishida qaytaramiz
        yield {
            "config_manager": mock_config_manager,
            "cache_manager": mock_cache_manager,
            "db": mock_db,
            "db_instance": mock_db_instance,
            "state": mock_state,
            "state_instance": mock_state_instance,
            "tasks": mock_tasks,
            "scheduler": mock_scheduler,
            "ai_service": mock_ai,
            "client_manager": mock_client_manager,
            "plugin_manager": mock_plugin_manager,
            "app_class": mock_app_class,
            "app_instance": mock_app_instance,
            "sleep": mock_sleep
        }


# --- Testlar To'plami ---

class TestMainLogic:
    """`main.py` faylining asosiy mantiqiy qismlarini tekshiruvchi testlar."""

    # 1-TEST
    async def test_successful_single_run(self, mock_dependencies, mock_static_settings):
        """Dasturning xatolarsiz, bir martalik ishga tushishini tekshiradi."""
        await run_application_lifecycle(mock_static_settings)

        # Asosiy obyektlar to'g'ri sozlamalar bilan yaratilganini tekshiramiz
        mock_dependencies['config_manager'].assert_called_once_with(static_config=mock_static_settings)
        mock_dependencies['db'].assert_called_once()
        mock_dependencies['state'].assert_called_once()
        
        # `create_application_instance` va `app.run` bir marta chaqirilishi kerak
        mock_dependencies['app_class'].assert_called_once()
        mock_dependencies['app_instance'].run.assert_awaited_once()
        
        # Qayta ishga tushirish funksiyalari chaqirilmasligi kerak
        mock_dependencies['app_instance'].cleanup_for_restart.assert_not_called()
        mock_dependencies['sleep'].assert_not_called()

    # 2-TEST
    async def test_restart_logic_once(self, mock_dependencies, mock_static_settings):
        """Dasturning bir marta qayta ishga tushish mantig'ini tekshiradi."""
        # `state.get` birinchi marta `True` (restart kerak), ikkinchi marta `False` qaytaradi
        mock_dependencies['state_instance'].get.side_effect = [True, False]
        await run_application_lifecycle(mock_static_settings)

        # `Application` klassi va uning `run` metodi ikki marta chaqirilishi kerak
        assert mock_dependencies['app_class'].call_count == 2
        assert mock_dependencies['app_instance'].run.await_count == 2
        
        # Tozalash va kutish funksiyalari faqat bir marta chaqirilishi kerak
        mock_dependencies['app_instance'].cleanup_for_restart.assert_awaited_once()
        mock_dependencies['sleep'].assert_awaited_once_with(2)

    # 3-TEST
    async def test_force_menu_argument_passed_to_run(self, mock_dependencies, mock_static_settings):
        """`--menu` argumenti berilganda, app.run to'g'ri chaqirilishini tekshiradi."""
        # `sys.argv` ni vaqtincha o'zgartiramiz
        with patch('main.sys.argv', ['main.py', '--menu']):
            await run_application_lifecycle(mock_static_settings)
        
        # `app.run` metodi `force_menu=True` parametri bilan chaqirilganini tekshiramiz
        mock_dependencies['app_instance'].run.assert_awaited_once_with(force_menu=True)

    # 4-TEST
    async def test_create_application_instance_logic(self, mock_dependencies):
        """`create_application_instance` funksiyasining to'g'ri ishlashini tekshiradi."""
        # Bu funksiyani chaqirish uchun kerakli soxta obyektlarni tayyorlaymiz
        mock_db = MagicMock()
        mock_config = MagicMock()
        mock_state = MagicMock()
        mock_cache = MagicMock()
        mock_tasks = MagicMock()
        mock_scheduler = MagicMock()
        mock_ai = MagicMock()

        # Funksiyani test qilamiz
        app = create_application_instance(mock_db, mock_config, mock_state, mock_cache, mock_tasks, mock_scheduler, mock_ai)

        # `ClientManager` va `PluginManager` to'g'ri argumentlar bilan yaratilganini tekshiramiz
        mock_dependencies['client_manager'].assert_called_with(database=mock_db, config=mock_config, state=mock_state)
        mock_dependencies['plugin_manager'].assert_called_with(
            client_manager=mock_dependencies['client_manager'].return_value, 
            state=mock_state,
            config_manager=mock_config # <-- YANGI QATOR: config_manager parametrini qo'shdik
        )
        
        # `Application` klassi to'g'ri `AppContext` bilan yaratilganini tekshiramiz
        mock_dependencies['app_class'].assert_called_once()
        # `app` o'zgaruvchisi `Application` klassining qaytargan qiymati ekanligini tekshiramiz
        assert app == mock_dependencies['app_class'].return_value

    # 5-TEST
    async def test_db_cleanup_tables_registered(self, mock_dependencies, mock_static_settings):
        """Ma'lumotlar bazasini tozalash jadvallari ro'yxatdan o'tishini tekshiradi."""
        await run_application_lifecycle(mock_static_settings)

        # `register_cleanup_table` metodiga qilingan chaqiruvlarni tekshiramiz
        calls = [
            call("afk_mentions", "mention_time"),
            call("logged_media", "timestamp")
        ]
        mock_dependencies['db_instance'].register_cleanup_table.assert_has_calls(calls, any_order=True)

    # 6-TEST
    async def test_loop_exits_immediately_if_restart_is_false(self, mock_dependencies, mock_static_settings):
        """Agar boshidanoq qayta ishga tushish kerak bo'lmasa, sikl bir marta ishlashini tekshiradi."""
        # `state.get` doim `False` qaytaradi (bu standart holat, lekin aniqlik uchun yozdik)
        mock_dependencies['state_instance'].get.return_value = False
        await run_application_lifecycle(mock_static_settings)
        
        # `run` metodi faqat bir marta chaqirilishini tasdiqlaymiz
        mock_dependencies['app_instance'].run.assert_awaited_once()
        # `state.get` ham bir marta chaqirilishi kerak
        mock_dependencies['state_instance'].get.assert_awaited_once_with('system.restart_pending', False)

    # 7-TEST
    async def test_long_lived_objects_created_once(self, mock_dependencies, mock_static_settings):
        """Restart talab qilmaydigan (uzoq yashovchi) obyektlar faqat bir marta yaratilishini tekshiradi."""
        # Siklni ikki marta aylantiramiz
        mock_dependencies['state_instance'].get.side_effect = [True, False]
        await run_application_lifecycle(mock_static_settings)
        
        # Bu obyektlar sikl tashqarisida bo'lgani uchun faqat bir marta yaratilishi kerak
        mock_dependencies['config_manager'].assert_called_once()
        mock_dependencies['cache_manager'].assert_called_once()
        mock_dependencies['db'].assert_called_once()
        mock_dependencies['state'].assert_called_once()
        mock_dependencies['tasks'].assert_called_once()
        mock_dependencies['scheduler'].assert_called_once()
        mock_dependencies['ai_service'].assert_called_once()
        
        # Bu obyektlar sikl ichida bo'lgani uchun ikki marta yaratilishi kerak
        assert mock_dependencies['client_manager'].call_count == 2
        assert mock_dependencies['plugin_manager'].call_count == 2
        
    # 8-TEST
    async def test_entrypoint_calls_run_lifecycle(self, mock_static_settings):
        """`entrypoint` funksiyasi `run_application_lifecycle`ni chaqirishini tekshiradi."""
        # `run_application_lifecycle`ni "patch" qilamiz
        with patch('main.run_application_lifecycle', new_callable=AsyncMock) as mock_run_lifecycle:
            await entrypoint(mock_static_settings)
            
            # `run_application_lifecycle` bir marta, to'g'ri argument bilan chaqirilganini tekshiramiz
            mock_run_lifecycle.assert_awaited_once_with(mock_static_settings)

    # 9-TEST
    async def test_no_restart_on_app_run_exception(self, mock_dependencies, mock_static_settings):
        """Agar `app.run()` xatolik bersa, qayta ishga tushishga harakat qilinmasligini tekshiradi."""
        # `app.run()` metodini xatolik beradigan qilib sozlaymiz
        mock_dependencies['app_instance'].run.side_effect = Exception("Test exception from app.run")
        
        # `run_application_lifecycle` xatolikni ushlamaydi, uni yuqoriga uzatadi.
        # Shuning uchun biz bu xatolikni kutishimiz kerak.
        with pytest.raises(Exception, match="Test exception from app.run"):
            await run_application_lifecycle(mock_static_settings)
            
        # Xatolikdan keyin `cleanup_for_restart` chaqirilmasligi kerak
        mock_dependencies['app_instance'].cleanup_for_restart.assert_not_called()
        mock_dependencies['sleep'].assert_not_called()

    # 10-TEST
    async def test_correct_arguments_for_core_components(self, mock_dependencies, mock_static_settings):
        """Asosiy komponentlar to'g'ri bog'liqliklar bilan yaratilishini tekshiradi."""
        await run_application_lifecycle(mock_static_settings)
        
        # Har bir komponent o'ziga kerakli boshqa komponent bilan yaratilganini tekshirish
        mock_config = mock_dependencies['config_manager'].return_value
        mock_cache = mock_dependencies['cache_manager'].return_value
        mock_db_instance = mock_dependencies['db'].return_value
        
        mock_dependencies['cache_manager'].assert_called_with(config_manager=mock_config)
        mock_dependencies['db'].assert_called_with(config_manager=mock_config, cache_manager=mock_cache)
        mock_dependencies['ai_service'].assert_called_with(config_manager=mock_config, cache_manager=mock_cache)
        mock_dependencies['scheduler'].assert_called_with(database=mock_db_instance)