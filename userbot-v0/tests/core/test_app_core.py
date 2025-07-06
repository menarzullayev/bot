from contextlib import suppress
import pytest
import asyncio
import time
from unittest.mock import ANY, AsyncMock, patch, MagicMock, call, Mock
from pathlib import Path
import sys
import json
import html
from pydantic import SecretStr, ValidationError


from core.app_core import Application, cli_prompt, load_credentials_from_file
from core.app_context import AppContext
from core.database import AsyncDatabase
from core.config_manager import ConfigManager
from core.state import AppState
from core.cache import CacheManager
from core.client_manager import ClientManager
from core.scheduler import SchedulerManager
from core.ai_service import AIService
from bot.loader import PluginManager


pytestmark = pytest.mark.asyncio


@pytest.fixture
def mock_app_context() -> MagicMock:
    """Mock qilingan AppContext obyektini yaratadi."""
    mock_db = AsyncMock(spec=AsyncDatabase)
    mock_config = MagicMock(spec=ConfigManager)
    mock_state = AsyncMock(spec=AppState)
    mock_cache = AsyncMock(spec=CacheManager)
    mock_tasks = MagicMock()
    mock_scheduler = MagicMock(spec=SchedulerManager)
    mock_ai_service = AsyncMock(spec=AIService)
    mock_client_manager = AsyncMock(spec=ClientManager)
    mock_plugin_manager = AsyncMock(spec=PluginManager)

    mock_context = MagicMock(spec=AppContext)
    mock_context.db = mock_db
    mock_context.config = mock_config
    mock_context.state = mock_state
    mock_context.cache = mock_cache
    mock_context.tasks = mock_tasks
    mock_context.scheduler = mock_scheduler
    mock_context.ai_service = mock_ai_service
    mock_context.client_manager = mock_client_manager
    mock_context.plugin_manager = mock_plugin_manager

    mock_config.get.return_value = None

    return mock_context


@pytest.fixture
def app_instance(mock_app_context: MagicMock) -> Application:
    """Har bir test uchun Application instansiyasini yaratadi."""
    app = Application(context=mock_app_context)
    return app


@pytest.fixture
def mock_cli_prompt():
    """`cli_prompt` funksiyasini soxtalashtiradi."""
    with patch('core.app_core.cli_prompt') as mock:
        yield mock


@pytest.fixture
def mock_load_credentials():
    """`load_credentials_from_file` funksiyasini soxtalashtiradi."""
    with patch('core.app_core.load_credentials_from_file', return_value=[]) as mock:
        yield mock


@pytest.mark.filterwarnings("ignore:coroutine 'AsyncMockMixin._execute_mock_call' was never awaited:RuntimeWarning")
class TestApplicationCore:
    """Application klassining asosiy funksionalliklarini test qilish."""

    async def test_initialization(self, app_instance: Application, mock_app_context: MagicMock):
        """1. Ilova to'g'ri initsializatsiya qilinganligini tekshirish."""
        assert app_instance.context == mock_app_context
        assert app_instance.client_manager == mock_app_context.client_manager
        assert app_instance.plugin_manager == mock_app_context.plugin_manager
        mock_app_context.tasks.set_client_manager.assert_called_once_with(mock_app_context.client_manager)
        mock_app_context.tasks.set_db_instance.assert_called_once_with(mock_app_context.db)
        mock_app_context.tasks.set_state_instance.assert_called_once_with(mock_app_context.state)

    async def test_run_successful_startup_interactive(self, app_instance: Application, mock_app_context: MagicMock, mock_cli_prompt: MagicMock, mock_load_credentials: MagicMock):
        """2. Interaktiv rejimda ilovaning muvaffaqiyatli ishga tushishi."""
        mock_app_context.config.get.return_value = False
        mock_app_context.db.fetchall.return_value = [{'id': 1, 'session_name': 'test_session', 'telegram_id': 12345, 'is_active': True}]
        mock_cli_prompt.return_value = "1"

        await app_instance.run()

        mock_app_context.db.connect.assert_awaited()
        mock_app_context.state.load_from_disk.assert_awaited()
        mock_app_context.cache.load_from_disk.assert_awaited()
        mock_app_context.client_manager.start_client_by_id.assert_awaited_with(1)
        mock_app_context.scheduler.start.assert_called_once()
        mock_app_context.scheduler.load_jobs_from_db.assert_awaited_once()
        mock_app_context.scheduler.schedule_system_tasks.assert_awaited_once()
        mock_app_context.plugin_manager.load_all_plugins.assert_awaited_once()
        mock_app_context.state.set.assert_called()

    async def test_run_successful_startup_non_interactive(self, app_instance: Application, mock_app_context: MagicMock):
        """3. Non-interaktiv rejimda ilovaning muvaffaqiyatli ishga tushishi."""
        mock_app_context.config.get.side_effect = lambda key, default=None: {"NON_INTERACTIVE": True, "NEW_ACCOUNT_API_ID": 123, "NEW_ACCOUNT_API_HASH": "abc", "NEW_ACCOUNT_SESSION_NAME": "auto_sess", "NEW_ACCOUNT_PHONE": "+998901234567"}.get(
            key, default
        )
        mock_app_context.db.fetchone.return_value = None
        mock_app_context.client_manager.add_account_non_interactive.return_value = 1

        await app_instance.run()

        mock_app_context.db.connect.assert_awaited()
        mock_app_context.client_manager.add_account_non_interactive.assert_awaited_once()
        mock_app_context.db.execute.assert_awaited_with("UPDATE accounts SET is_active = ? WHERE id = ?", (True, 1))
        mock_app_context.client_manager.start_client_by_id.assert_awaited_with(1)
        mock_app_context.scheduler.start.assert_called_once()
        mock_app_context.plugin_manager.load_all_plugins.assert_awaited_once()

    async def test_full_shutdown_logic(self, app_instance: Application, mock_app_context: MagicMock, tmp_path: Path):
        """4. Ilovani to'liq yopish funksiyasini tekshirish."""
        data_path = tmp_path / "data"
        data_path.mkdir(exist_ok=True)
        shutdown_notice_path = data_path / "shutdown_notice.json"
        file_content = '{"chat_id": 1, "message_id": 123, "original_text": "Bot o\'chirilmoqda...", "reason": "Test Reason"}'
        shutdown_notice_path.write_text(file_content)

        mock_client = AsyncMock()
        mock_client.is_connected = MagicMock(return_value=True)
        mock_app_context.client_manager.get_all_clients.return_value = [mock_client]

        app_instance.is_running = True

        with patch('pathlib.Path.exists', return_value=True), patch('pathlib.Path.open', MagicMock(return_value=MagicMock(__enter__=lambda self: MagicMock(read=lambda: file_content), __exit__=lambda *args: None))), patch(
            'pathlib.Path.unlink', return_value=None
        ):

            await app_instance.full_shutdown()

        assert app_instance.is_running is False
        mock_app_context.scheduler.shutdown.assert_called_once()
        mock_app_context.client_manager.stop_all_clients.assert_awaited_once()
        mock_app_context.db.close.assert_awaited_once()
        mock_app_context.cache.save_to_disk.assert_awaited_once()
        mock_app_context.state.save_to_disk.assert_awaited_once()

        expected_original_text = html.escape("Bot o'chirilmoqda...")
        expected_reason_text = html.escape("Test Reason")
        expected_text_output = f"<s>{expected_original_text}</s>\n\n✅ <b>Muvaffaqiyatli o'chirildi.</b>\nSabab: <i>{expected_reason_text}</i>"

        mock_client.edit_message.assert_awaited_once_with(entity=1, message=123, text=expected_text_output, parse_mode='html')

    async def test_full_shutdown_edit_message_error(self, app_instance: Application, mock_app_context: MagicMock, tmp_path: Path):
        """Shutdown xabarini tahrirlashda xatolik yuz berganda uni qayta ishlashni tekshiradi."""
        data_path = tmp_path / "data"
        data_path.mkdir(exist_ok=True)
        shutdown_notice_path = data_path / "shutdown_notice.json"
        shutdown_notice_path.write_text('{"chat_id": 1, "message_id": 123, "original_text": "Bot o\'chirilmoqda..."}')

        mock_client = AsyncMock()
        mock_client.is_connected = MagicMock(return_value=True)
        mock_client.edit_message.side_effect = Exception("Edit message failed")
        mock_app_context.client_manager.get_all_clients.return_value = [mock_client]

        app_instance.is_running = True

        with patch('pathlib.Path.exists', return_value=True), patch('pathlib.Path.open', MagicMock(return_value=MagicMock(__enter__=lambda self: MagicMock(read=lambda: '{"chat_id": 1, "message_id": 123}'), __exit__=lambda *args: None))), patch(
            'pathlib.Path.unlink', return_value=None
        ):
            with patch("core.app_core.logger.error") as mock_log_error:
                await app_instance.full_shutdown()
                mock_log_error.assert_called_once()
                assert "Shutdown xabarini tahrirlashda xatolik:" in mock_log_error.call_args[0][0]

    async def test_cleanup_for_restart_logic(self, app_instance: Application, mock_app_context: MagicMock):
        """5. Qayta ishga tushirishdan oldin tozalash funksiyasini tekshirish."""
        app_instance.periodic_save_task = asyncio.create_task(asyncio.sleep(0.01))

        await app_instance.cleanup_for_restart()

        mock_app_context.client_manager.stop_all_clients.assert_awaited_once()
        mock_app_context.scheduler.shutdown.assert_called_once()
        mock_app_context.db.close.assert_awaited_once()
        mock_app_context.cache.save_to_disk.assert_awaited_once()
        mock_app_context.state.save_to_disk.assert_awaited_once()
        mock_app_context.tasks.clear.assert_called_once()
        assert app_instance.periodic_save_task.done()
        assert app_instance.periodic_save_task.cancelled()

    async def test_periodic_persistence_task_normal_run_and_cancel(self, app_instance: Application, mock_app_context: MagicMock):
        """_periodic_persistence_task normal ishlashini va bekor qilinganda to'g'ri to'xtashini tekshiradi."""
        mock_app_context.config.get.return_value = 0.05

        app_instance.periodic_save_task = asyncio.create_task(app_instance._periodic_persistence_task())

        await asyncio.sleep(0.1)

        app_instance.periodic_save_task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await app_instance.periodic_save_task

        mock_app_context.cache.save_to_disk.assert_awaited()
        mock_app_context.state.save_to_disk.assert_awaited()
        assert mock_app_context.cache.save_to_disk.await_count >= 1
        assert mock_app_context.state.save_to_disk.await_count >= 1

    async def test_periodic_persistence_task_exception_handling(self, app_instance: Application, mock_app_context: MagicMock):
        """_periodic_persistence_task ichida kutilmagan xatolik yuz berganda uni qayta ishlashni tekshiradi."""
        mock_app_context.config.get.return_value = 0.05
        mock_app_context.cache.save_to_disk.side_effect = Exception("Disk full error")

        app_instance.periodic_save_task = asyncio.create_task(app_instance._periodic_persistence_task())

        with patch("core.app_core.logger.error") as mock_log_error:
            await asyncio.sleep(0.1)

            mock_log_error.assert_called_once()
            assert "Avtomatik saqlashda kutilmagan xatolik" in mock_log_error.call_args[0][0]

        app_instance.periodic_save_task.cancel()
        with suppress(asyncio.CancelledError):
            await app_instance.periodic_save_task

    async def test_handle_post_restart_actions(self, app_instance: Application, mock_app_context: MagicMock, tmp_path: Path):
        """6. Qayta ishga tushirishdan keyingi amallarni tekshirish (xabarni tahrirlash)."""
        data_path = tmp_path / "data"
        data_path.mkdir(exist_ok=True)
        restart_notice_path = data_path / "restart_notice.json"
        file_content = '{"chat_id": 1, "message_id": 123, "original_text": "Bot qayta ishga tushirilmoqda..."}'
        restart_notice_path.write_text(file_content)

        mock_client = AsyncMock()
        mock_client.is_connected = MagicMock(return_value=True)
        mock_app_context.client_manager.get_all_clients.return_value = [mock_client]

        with patch('pathlib.Path.exists', return_value=True), patch('pathlib.Path.open', MagicMock(return_value=MagicMock(__enter__=lambda self: MagicMock(read=lambda: file_content), __exit__=lambda *args: None))), patch(
            'pathlib.Path.unlink', return_value=None
        ):

            await app_instance._handle_post_restart_actions()

        mock_client.edit_message.assert_awaited_once_with(entity=1, message=123, text="<s>Bot qayta ishga tushirilmoqda...</s>\n\n✅ <b>Muvaffaqiyatli qayta ishga tushirildi</b>", parse_mode='HTML')

    async def test_handle_post_restart_actions_no_active_client(self, app_instance: Application, mock_app_context: MagicMock, tmp_path: Path):
        """Restart xabarini tahrirlash uchun aktiv klient topilmaganda ogohlantirish berilishini tekshiradi."""
        data_path = tmp_path / "data"
        data_path.mkdir(exist_ok=True)
        restart_notice_path = data_path / "restart_notice.json"
        restart_notice_path.write_text('{}')

        mock_app_context.client_manager.get_all_clients.return_value = []

        with patch('pathlib.Path.exists', return_value=True), patch('pathlib.Path.open', MagicMock(return_value=MagicMock(__enter__=lambda self: MagicMock(read=lambda: '{}'), __exit__=lambda *args: None))), patch(
            'pathlib.Path.unlink', return_value=None
        ):
            with patch("core.app_core.logger.warning") as mock_log_warn:
                await app_instance._handle_post_restart_actions()
                mock_log_warn.assert_called_once()
                assert "Restart xabarini tahrirlash uchun aktiv klient topilmadi." in mock_log_warn.call_args[0][0]

    async def test_handle_post_restart_actions_edit_error(self, app_instance: Application, mock_app_context: MagicMock, tmp_path: Path):
        """Restart xabarini tahrirlashda xatolik yuz berganda uni qayta ishlashni tekshiradi."""
        data_path = tmp_path / "data"
        data_path.mkdir(exist_ok=True)
        restart_notice_path = data_path / "restart_notice.json"
        restart_notice_path.write_text('{"chat_id": 1, "message_id": 123}')

        mock_client = AsyncMock()
        mock_client.is_connected = MagicMock(return_value=True)
        mock_client.edit_message.side_effect = Exception("Edit failed on restart")
        mock_app_context.client_manager.get_all_clients.return_value = [mock_client]

        with patch('pathlib.Path.exists', return_value=True), patch('pathlib.Path.open', MagicMock(return_value=MagicMock(__enter__=lambda self: MagicMock(read=lambda: '{"chat_id": 1, "message_id": 123}'), __exit__=lambda *args: None))), patch(
            'pathlib.Path.unlink', return_value=None
        ):
            with patch("core.app_core.logger.error") as mock_log_error:
                await app_instance._handle_post_restart_actions()
                mock_log_error.assert_called_once()
                assert "Restart xabarini tahrirlashda xatolik:" in mock_log_error.call_args[0][0]

    async def test_run_no_account_selected(self, app_instance: Application, mock_app_context: MagicMock, mock_cli_prompt: MagicMock, mock_load_credentials: MagicMock):
        """7. Interaktiv rejimda akkaunt tanlanmaganda ilova to'xtatilishini tekshirish."""
        mock_app_context.config.get.return_value = False
        mock_app_context.db.fetchall.return_value = []
        mock_app_context.client_manager.add_new_account_interactive.return_value = None
        mock_cli_prompt.return_value = "q"

        await app_instance.run()

        assert app_instance.is_running is False
        mock_app_context.client_manager.start_client_by_id.assert_not_awaited()

    async def test_run_client_startup_failure(self, app_instance: Application, mock_app_context: MagicMock):
        """8. Tanlangan klientni ishga tushirishda xatolik yuz berganda."""
        mock_app_context.config.get.return_value = False
        mock_app_context.db.fetchall.return_value = [{'id': 1, 'session_name': 'test_session', 'telegram_id': 12345, 'is_active': True}]
        mock_app_context.client_manager.start_client_by_id.return_value = False

        await app_instance.run()

        assert app_instance.is_running is False
        mock_app_context.scheduler.start.assert_not_called()
        mock_app_context.plugin_manager.load_all_plugins.assert_not_called()

    async def test_run_keyboard_interrupt(self, app_instance: Application, mock_app_context: MagicMock):
        """9. `KeyboardInterrupt` (CTRL+C) bilan ilovani yopish."""
        mock_app_context.config.get.return_value = False
        mock_app_context.db.fetchall.return_value = [{'id': 1, 'session_name': 'test_session', 'is_active': True, 'telegram_id': 123}]
        mock_app_context.client_manager.start_client_by_id.return_value = True

        mock_periodic_task_future = asyncio.Future()
        mock_periodic_task_future.set_exception(KeyboardInterrupt())
        app_instance.periodic_save_task = asyncio.create_task(asyncio.sleep(0))
        app_instance.periodic_save_task.cancel()

        with patch.object(app_instance, 'full_shutdown', new_callable=AsyncMock) as mock_full_shutdown:
            with patch('asyncio.gather', new_callable=AsyncMock) as mock_gather:
                mock_gather.side_effect = KeyboardInterrupt

                with pytest.raises(KeyboardInterrupt):
                    await app_instance.run()

                assert app_instance.is_running is False
                mock_full_shutdown.assert_awaited_once()

    async def test_run_general_exception_handled(self, app_instance: Application, mock_app_context: MagicMock):
        """10. `run` metodi ichida kutilmagan umumiy xatolik yuz berganda uni qayta ishlash."""
        mock_app_context.config.get.side_effect = Exception("Test konfiguratsiya xatosi")

        with patch.object(app_instance, 'full_shutdown', new_callable=AsyncMock) as mock_full_shutdown:
            await app_instance.run()

            assert app_instance.is_running is False
            mock_full_shutdown.assert_awaited_once()

    async def test_load_credentials_from_file_io_error(self, tmp_path: Path):
        """accounts.json fayli mavjud bo'lmasa yoki o'qishda xato bo'lsa tekshirish."""

        with patch('pathlib.Path.is_file', return_value=True), patch('pathlib.Path.stat', return_value=MagicMock(st_size=10)), patch('pathlib.Path.open', side_effect=IOError("File read error")):
            with patch("core.app_core.logger.warning") as mock_warn:
                result = load_credentials_from_file()
                assert result == []
                mock_warn.assert_called_once()
                assert "accounts.json faylini o'qib bo'lmadi" in mock_warn.call_args[0][0]

    async def test_load_credentials_from_file_json_decode_error(self, tmp_path: Path):
        """accounts.json fayli buzilgan JSON bo'lsa tekshirish."""
        test_file = tmp_path / "accounts.json"
        test_file.write_text("invalid json {", encoding='utf-8')

        with patch('pathlib.Path.is_file', return_value=True), patch('pathlib.Path.stat', return_value=MagicMock(st_size=10)), patch(
            'pathlib.Path.open', MagicMock(return_value=MagicMock(__enter__=lambda self: MagicMock(read=lambda: "invalid json {"), __exit__=lambda *args: None))
        ) :
            with patch("core.app_core.logger.warning") as mock_warn:
                result = load_credentials_from_file()
                assert result == []
                mock_warn.assert_called_once()
                assert "accounts.json faylini o'qib bo'lmadi" in mock_warn.call_args[0][0]

    async def test_cli_prompt_function(self):
        """cli_prompt funksiyasini to'g'ridan-to'g'ri testlash."""
        with patch('asyncio.to_thread', new_callable=AsyncMock) as mock_to_thread:
            mock_to_thread.return_value = "user_input"
            result = await cli_prompt("Enter something: ")
            mock_to_thread.assert_awaited_once_with(input, "Enter something: ")
            assert result == "user_input"

    async def test_interactive_startup_menu_restore_account_choose_add_new(self, app_instance: Application, mock_app_context: MagicMock, mock_cli_prompt: MagicMock, mock_load_credentials: MagicMock):
        """Akkauntni tiklash menyusida '0' ni tanlab, yangi akkaunt qo'shish."""
        mock_app_context.db.fetchall.return_value = []
        mock_cli_prompt.side_effect = ["0", "new_account_data", "q"]
        mock_app_context.client_manager.add_new_account_interactive.return_value = 100

        json_credentials_content = '[{"session_name": "restore_sess", "telegram_id": 1}]'
        mock_load_credentials.return_value = json.loads(json_credentials_content)

        selected_id = await app_instance.interactive_startup_menu()
        assert selected_id == 100
        mock_app_context.db.execute.assert_awaited_with("UPDATE accounts SET is_active = ? WHERE id = ?", (True, 100))
        mock_app_context.client_manager.add_new_account_interactive.assert_awaited_once_with(mock_cli_prompt)

    async def test_interactive_startup_menu_restore_account_invalid_input(self, app_instance: Application, mock_app_context: MagicMock, mock_cli_prompt: MagicMock, mock_load_credentials: MagicMock):
        """Akkauntni tiklash menyusida noto'g'ri (raqam bo'lmagan) ma'lumot kiritish."""
        mock_app_context.db.fetchall.return_value = []
        mock_cli_prompt.side_effect = ["abc", "q"]

        json_credentials_content = '[{"session_name": "restore_sess", "telegram_id": 1}]'
        mock_load_credentials.return_value = json.loads(json_credentials_content)

        with patch("builtins.print") as mock_print:
            selected_id = await app_instance.interactive_startup_menu()
            assert selected_id is None
            mock_print.assert_any_call("Xato: Raqam kiriting.")

    async def test_interactive_startup_menu_manage_choose_add_new_success(self, app_instance: Application, mock_app_context: MagicMock, mock_cli_prompt: MagicMock, mock_load_credentials: MagicMock):
        """Userbotni Boshqarish Menyusida '0' ni tanlab, yangi akkaunt qo'shish va muvaffaqiyatli yakunlash."""
        mock_app_context.db.fetchall.return_value = [{'id': 1, 'session_name': 'existing_sess', 'telegram_id': 123, 'is_active': False}]
        mock_cli_prompt.side_effect = ["0", "q"]
        mock_app_context.client_manager.add_new_account_interactive.return_value = 200

        mock_load_credentials.return_value = []

        selected_id = await app_instance.interactive_startup_menu(force_menu=True)
        assert selected_id == 200
        mock_app_context.client_manager.add_new_account_interactive.assert_awaited_once_with(mock_cli_prompt)
        mock_app_context.db.execute.assert_awaited_once_with("UPDATE accounts SET is_active = ? WHERE id = ?", (True, 200))

    async def test_interactive_startup_menu_manage_choose_add_new_fail(self, app_instance: Application, mock_app_context: MagicMock, mock_cli_prompt: MagicMock, mock_load_credentials: MagicMock):
        """Userbotni Boshqarish Menyusida '0' ni tanlab, yangi akkaunt qo'shish muvaffaqiyatsiz tugasa."""
        mock_app_context.db.fetchall.return_value = [{'id': 1, 'session_name': 'existing_sess', 'telegram_id': 123, 'is_active': False}]
        mock_cli_prompt.side_effect = ["0", "q"]
        mock_app_context.client_manager.add_new_account_interactive.return_value = None

        mock_load_credentials.return_value = []

        with patch("builtins.print"):
            selected_id = await app_instance.interactive_startup_menu(force_menu=True)
            assert selected_id is None
            mock_app_context.client_manager.add_new_account_interactive.assert_awaited_once_with(mock_cli_prompt)

            mock_app_context.db.execute.assert_not_awaited()

    async def test_interactive_startup_menu_restore_account_success(self, app_instance: Application, mock_app_context: MagicMock, mock_cli_prompt: MagicMock, mock_load_credentials: MagicMock):
        """DB bo'sh, lekin accounts.json da ma'lumot bor va foydalanuvchi akkauntni tiklaydi."""
        mock_app_context.db.fetchall.return_value = []
        mock_cli_prompt.side_effect = ["1"]
        mock_app_context.client_manager.add_new_account_interactive.return_value = 100

        json_credentials_content = '[{"session_name": "restore_sess", "api_id": 1, "api_hash": "a", "telegram_id": 1}]'
        mock_load_credentials.return_value = json.loads(json_credentials_content)

        selected_id = await app_instance.interactive_startup_menu()
        assert selected_id == 100
        mock_app_context.db.execute.assert_awaited_with("UPDATE accounts SET is_active = ? WHERE id = ?", (True, 100))
        mock_app_context.client_manager.add_new_account_interactive.assert_awaited_once_with(mock_cli_prompt, prefilled_data={"session_name": "restore_sess", "api_id": 1, "api_hash": "a", "telegram_id": 1})

    async def test_interactive_startup_menu_restore_account_fail(self, app_instance: Application, mock_app_context: MagicMock, mock_cli_prompt: MagicMock, mock_load_credentials: MagicMock):
        """Akkauntni tiklashda xato (add_new_account_interactive None qaytarsa)."""
        mock_app_context.db.fetchall.return_value = []
        mock_cli_prompt.side_effect = ["1", "q"]
        mock_app_context.client_manager.add_new_account_interactive.return_value = None

        json_credentials_content = '[{"session_name": "restore_fail_sess", "telegram_id": 1}]'
        mock_load_credentials.return_value = json.loads(json_credentials_content)

        with patch("builtins.print") as mock_print:
            selected_id = await app_instance.interactive_startup_menu()
            assert selected_id is None
            mock_print.assert_any_call("Xato: Akkauntni tiklash muvaffaqiyatsiz tugadi.")
            mock_app_context.db.execute.assert_not_awaited()

    async def test_interactive_startup_menu_new_account_option(self, app_instance: Application, mock_app_context: MagicMock, mock_cli_prompt: MagicMock, mock_load_credentials: MagicMock):
        """Interaktiv menyuda yangi akkaunt qo'shish tanlansa."""
        mock_app_context.db.fetchall.return_value = []
        mock_cli_prompt.side_effect = ["0", "yangi_akkaunt_data"]
        mock_app_context.client_manager.add_new_account_interactive.return_value = 200

        mock_load_credentials.return_value = []
        with patch("builtins.print"):
            selected_id = await app_instance.interactive_startup_menu()
            assert selected_id == 200
            mock_app_context.client_manager.add_new_account_interactive.assert_awaited_once_with(mock_cli_prompt)
            mock_app_context.db.execute.assert_awaited_once_with("UPDATE accounts SET is_active = ? WHERE id = ?", (True, 200))

    async def test_interactive_startup_menu_invalid_choice(self, app_instance: Application, mock_app_context: MagicMock, mock_cli_prompt: MagicMock, mock_load_credentials: MagicMock):
        """Interaktiv menyuda noto'g'ri raqam yoki harf kiritilsa."""
        mock_app_context.db.fetchall.return_value = [{'id': 1, 'session_name': 'test', 'is_active': False, 'telegram_id': None}]
        mock_cli_prompt.side_effect = ["abc", "q"]
        mock_app_context.client_manager.add_new_account_interactive.return_value = 1

        mock_load_credentials.return_value = []
        with patch("builtins.print") as mock_print:
            selected_id = await app_instance.interactive_startup_menu(force_menu=True)
            assert selected_id is None
            mock_print.assert_any_call("Xato: Raqam yoki 'q'/'0' harflaridan birini kiriting.")

    async def test_interactive_startup_menu_exit_option(self, app_instance: Application, mock_app_context: MagicMock, mock_cli_prompt: MagicMock, mock_load_credentials: MagicMock):
        """Interaktiv menyudan 'q' bilan chiqib ketish."""
        mock_app_context.db.fetchall.return_value = [{'id': 1, 'session_name': 'test', 'is_active': False, 'telegram_id': None}]
        mock_cli_prompt.return_value = "q"

        mock_load_credentials.return_value = []
        selected_id = await app_instance.interactive_startup_menu()
        assert selected_id is None
        mock_app_context.client_manager.start_client_by_id.assert_not_awaited()

    async def test_interactive_startup_menu_select_existing_account(self, app_instance: Application, mock_app_context: MagicMock, mock_cli_prompt: MagicMock, mock_load_credentials: MagicMock):
        """Mavjud akkauntni tanlash va aktiv qilish."""
        mock_app_context.db.fetchall.return_value = [{'id': 1, 'session_name': 'sess1', 'telegram_id': 101, 'is_active': False}, {'id': 2, 'session_name': 'sess2', 'telegram_id': 102, 'is_active': True}]
        mock_cli_prompt.return_value = "1"

        mock_load_credentials.return_value = []
        selected_id = await app_instance.interactive_startup_menu(force_menu=True)
        assert selected_id == 1
        mock_app_context.db.executemany.assert_awaited_with("UPDATE accounts SET is_active = ? WHERE id = ?", [(False, 2)])
        mock_app_context.db.execute.assert_awaited_with("UPDATE accounts SET is_active = ? WHERE id = ?", (True, 1))

    async def test_interactive_startup_menu_single_active_auto_select(self, app_instance: Application, mock_app_context: MagicMock, mock_load_credentials: MagicMock):
        """Yagona aktiv akkaunt mavjud bo'lsa, avtomatik tanlanishini tekshirish."""
        mock_app_context.db.fetchall.return_value = [
            {'id': 1, 'session_name': 'sess1', 'telegram_id': 101, 'is_active': True},
        ]
        mock_load_credentials.return_value = []
        selected_id = await app_instance.interactive_startup_menu()
        assert selected_id == 1
        mock_app_context.config.get.assert_not_called()

    async def test_non_interactive_setup_existing_active(self, app_instance: Application, mock_app_context: MagicMock):
        """Non-interaktiv rejimda mavjud aktiv akkauntni topish."""
        mock_app_context.db.fetchone.return_value = {'id': 5}
        account_id = await app_instance.non_interactive_setup()
        assert account_id == 5
        mock_app_context.db.connect.assert_awaited_once()

    @pytest.mark.parametrize("missing_field", ["NEW_ACCOUNT_API_ID", "NEW_ACCOUNT_API_HASH", "NEW_ACCOUNT_SESSION_NAME"])
    async def test_non_interactive_setup_missing_critical_env(self, app_instance: Application, mock_app_context: MagicMock, missing_field):
        """Non-interaktiv rejimda kritik .env sozlamalari yo'q bo'lsa, xato berishini tekshirish."""

        def mock_config_get(key, default=None):
            if key == missing_field:
                return None
            return {
                "NON_INTERACTIVE": True,
                "NEW_ACCOUNT_API_ID": 123,
                "NEW_ACCOUNT_API_HASH": "abc",
                "NEW_ACCOUNT_SESSION_NAME": "auto_sess",
            }.get(key, default)

        mock_app_context.config.get.side_effect = mock_config_get
        mock_app_context.db.fetchone.return_value = None

        with patch("core.app_core.logger.critical") as mock_log:
            result = await app_instance.non_interactive_setup()
            assert result is None
            mock_log.assert_called_once()
            assert "Kritik xato: Interaktiv bo'lmagan rejimda" in mock_log.call_args[0][0]

    async def test_non_interactive_setup_add_account_success(self, app_instance: Application, mock_app_context: MagicMock):
        """Non-interaktiv rejimda yangi akkaunt muvaffaqiyatli qo'shilsa."""
        mock_app_context.db.fetchone.return_value = None
        mock_app_context.config.get.side_effect = lambda key, default=None: {"NEW_ACCOUNT_API_ID": 1, "NEW_ACCOUNT_API_HASH": SecretStr("a"), "NEW_ACCOUNT_SESSION_NAME": "new_sess"}.get(key, default)
        mock_app_context.client_manager.add_account_non_interactive.return_value = 101

        new_id = await app_instance.non_interactive_setup()
        assert new_id == 101
        mock_app_context.db.execute.assert_awaited_once_with("UPDATE accounts SET is_active = ? WHERE id = ?", (True, 101))

    async def test_non_interactive_setup_add_account_fail(self, app_instance: Application, mock_app_context: MagicMock):
        """Non-interaktiv rejimda yangi akkaunt qo'shish muvaffaqiyatsiz bo'lsa."""
        mock_app_context.db.fetchone.return_value = None
        mock_app_context.config.get.side_effect = lambda key, default=None: {"NEW_ACCOUNT_API_ID": 1, "NEW_ACCOUNT_API_HASH": SecretStr("a"), "NEW_ACCOUNT_SESSION_NAME": "new_sess"}.get(key, default)
        mock_app_context.client_manager.add_account_non_interactive.return_value = None

        with patch("core.app_core.logger.error") as mock_log_error:
            result = await app_instance.non_interactive_setup()
            assert result is None
            mock_log_error.assert_called_once()
            assert "Yangi akkauntni .env sozlamalari orqali qo'shib bo'lmadi." in mock_log_error.call_args[0][0]

    async def test_run_loop_sleep_inf_covered(self, app_instance: Application, mock_app_context: MagicMock):
        """run() metodining asyncio.sleep(float('inf')) qatori qamrab olinganligini tekshirish."""
        mock_app_context.config.get.return_value = False
        mock_app_context.db.fetchall.return_value = [{'id': 1, 'session_name': 'test_session', 'is_active': True, 'telegram_id': 123}]
        mock_app_context.client_manager.start_client_by_id.return_value = True

        mock_app_context.client_manager.get_all_clients.return_value = []

        with patch('asyncio.sleep', new_callable=AsyncMock) as mock_sleep:
            mock_sleep.side_effect = asyncio.CancelledError("Test tugadi")

            with pytest.raises(asyncio.CancelledError):
                await app_instance.run()

            mock_sleep.assert_awaited_once_with(float('inf'))
