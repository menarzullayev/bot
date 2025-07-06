import pytest
import asyncio
import time
import traceback
from unittest.mock import MagicMock, AsyncMock, call, patch, ANY
import inspect
import random

import pytest_asyncio


from core.tasks import TaskRegistry, Task, FailureContext
from core.database import AsyncDatabase
from core.state import AppState
from core.config_manager import ConfigManager
from core.client_manager import ClientManager
from core.exceptions import DatabaseError, QueryError


from core.tasks import cleanup_old_database_entries, vacuum_database


@pytest.fixture
def mock_db() -> AsyncMock:
    db = AsyncMock(spec=AsyncDatabase)
    db.get_cleanup_configurations.return_value = {"test_table": "test_date_col"}
    db.transaction = MagicMock(return_value=AsyncMock(__aenter__=AsyncMock(), __aexit__=AsyncMock(return_value=False)))
    return db


@pytest.fixture
def mock_state() -> AsyncMock:
    return AsyncMock(spec=AppState)


@pytest.fixture
def mock_config() -> MagicMock:
    config = MagicMock(spec=ConfigManager)
    config.get.return_value = 7
    return config


@pytest.fixture
def mock_client_manager() -> MagicMock:
    client_mock = MagicMock()
    client_mock.is_connected = AsyncMock(return_value=True)

    manager = MagicMock(spec=ClientManager)
    manager.get_client.return_value = client_mock
    return manager


@pytest_asyncio.fixture
async def registry(mock_db: AsyncMock, mock_state: AsyncMock, mock_config: MagicMock, mock_client_manager: MagicMock) -> TaskRegistry:
    reg = TaskRegistry()
    reg.set_db_instance(mock_db)
    reg.set_state_instance(mock_state)
    reg.set_config_instance(mock_config)
    reg.set_client_manager(mock_client_manager)

    reg.register(key="system.cleanup_db", description="Periodically cleans up old records from the database.", singleton=True, retries=2, retry_delay=60)(cleanup_old_database_entries)

    reg.register(key="system.vacuum_db", description="Periodically performs VACUUM operation on the database.", singleton=True, retries=1, retry_delay=300, timeout=1800)(vacuum_database)

    return reg

class TestTaskRegistration:
    """Vazifalarni ro'yxatdan o'tkazishni test qilish."""

    @pytest.mark.asyncio
    async def test_register_task_successfully(self, registry: TaskRegistry):
        """Oddiy vazifani muvaffaqiyatli ro'yxatdan o'tkazish."""

        @registry.register(key="test.task1")
        async def my_task():
            # Test uchun bo‘sh funksiyani ro‘yxatdan o‘tkazamiz
            return

        assert registry.get_task("test.task1") is not None
        assert registry.get_task("test.task1") is not None


    def test_register_non_async_task_fails(self, registry: TaskRegistry):
        """Sinxron funksiyani ro'yxatdan o'tkazishda xatolikni tekshirish."""
        with pytest.raises(TypeError, match="Vazifa asinxron"):

            @registry.register(key="test.sync_task")
            def my_sync_task():
                # Asinxron bo‘lmagan funksiya — xato keltiradi
                return "Hello"

    @pytest.mark.asyncio
    async def test_register_task_singleton_warning(self, registry: TaskRegistry):
        """Singleton vazifani max_concurrent_runs > 1 bilan ro'yxatdan o'tkazishda ogohlantirishni tekshirish."""
        with patch("core.tasks.logger.warning") as mock_warn:

            @registry.register(key="test.singleton_warn", singleton=True, max_concurrent_runs=2)
            async def my_singleton_warn_task():
                pass

            mock_warn.assert_called_once()
            assert "Singleton vazifa 'test.singleton_warn' uchun max_concurrent_runs 2 sifatida berildi, lekin u 1 ga o'rnatiladi." in mock_warn.call_args[0][0]

    @pytest.mark.asyncio
    async def test_register_task_re_registration_warning(self, registry: TaskRegistry):
        """Mavjud taskni qayta ro'yxatdan o'tkazishda ogohlantirishni tekshirish."""

        @registry.register(key="test.re_register")
        async def task_v1():
            pass

        with patch("core.tasks.logger.warning") as mock_warn:

            @registry.register(key="test.re_register")
            async def task_v2():
                pass

            mock_warn.assert_called_once()
            assert "Vazifa kaliti 'test.re_register' qayta ro'yxatdan o'tkazilmoqda." in mock_warn.call_args[0][0]

    @pytest.mark.asyncio
    async def test_add_task_invalid_type(self, registry: TaskRegistry):
        """Noto'g'ri turdagi ob'ektni add_task orqali qo'shishda xatolikni tekshirish."""
        # Bu test noto'g'ri tipdagi qiymat uchun xatolikni kutadi
        with pytest.raises(TypeError, match="add_task metodi faqat Task obyekti qabul qiladi."):
            registry.add_task("not_a_task")  # type: ignore

    @pytest.mark.asyncio
    async def test_add_task_existing_key(self, registry: TaskRegistry):
        """Mavjud task kalitini add_task orqali qayta qo'shishda ogohlantirishni tekshirish."""
        task1 = Task(key="existing.task", func=AsyncMock())
        registry.add_task(task1)
        with patch("core.tasks.logger.warning") as mock_warn:
            task2 = Task(key="existing.task", func=AsyncMock())
            registry.add_task(task2)
            mock_warn.assert_called_once()
            assert "Vazifa 'existing.task' allaqachon ro'yxatdan o'tgan. Qayta yozilmoqda." in mock_warn.call_args[0][0]

    @pytest.mark.asyncio
    async def test_remove_task_success(self, registry: TaskRegistry):
        """Taskni muvaffaqiyatli o'chirishni tekshirish."""
        task = Task(key="removable.task", func=AsyncMock())
        registry.add_task(task)
        with patch("core.tasks.logger.info") as mock_info:
            result = registry.remove_task("removable.task")
            assert result is True
            mock_info.assert_called_once()
            assert "Vazifa 'removable.task' ro'yxatdan o'chirildi." in mock_info.call_args[0][0]

    @pytest.mark.asyncio
    async def test_remove_task_not_found(self, registry: TaskRegistry):
        """Mavjud bo'lmagan taskni o'chirishda ogohlantirishni tekshirish."""
        with patch("core.tasks.logger.warning") as mock_warn:
            result = registry.remove_task("non_existent.task")
            assert result is False
            mock_warn.assert_called_once()
            assert "Vazifa 'non_existent.task' topilmadi, o'chirilmadi." in mock_warn.call_args[0][0]


class TestTaskExecution:
    """Vazifalarni ishga tushirish mantig'ini test qilish."""

    @pytest.mark.asyncio
    async def test_run_simple_task_manually(self, registry: TaskRegistry):
        mock_func = AsyncMock()
        registry.add_task(Task(key="manual.run", func=mock_func))
        await registry.run_task_manually("manual.run")
        await asyncio.sleep(0.01)
        mock_func.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_task_retries_on_failure(self, registry: TaskRegistry):
        mock_func = AsyncMock(side_effect=[ValueError("Xato"), "OK"])
        task = Task(key="retry.task", func=mock_func, retries=1, retry_delay=0)
        registry.add_task(task)
        await registry.run_task_manually("retry.task")

        for _ in range(10):
            if task.status == "success":
                break
            await asyncio.sleep(0.1)

        assert mock_func.call_count == 2
        assert task.status == "success"

    @pytest.mark.asyncio
    async def test_task_fails_after_all_retries(self, registry: TaskRegistry):
        mock_func = AsyncMock(side_effect=ValueError("Doimiy xato"))
        mock_on_failure = AsyncMock()
        task = Task(key="fail.task", func=mock_func, retries=2, retry_delay=0, on_failure=mock_on_failure)
        registry.add_task(task)

        await registry.run_task_manually("fail.task")

        await asyncio.sleep(0.1)  # Fon vazifasi tugashini kutish

        assert mock_func.call_count == 3
        assert task.status == "failed"
        mock_on_failure.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_task_timeout(self, registry: TaskRegistry):
        """Task belgilangan vaqt ichida yakunlanmasa, timeout bo'lishini tekshirish."""
        mock_func = AsyncMock()
        task = Task(key="timeout.task", func=mock_func, timeout=1, retries=0)
        registry.add_task(task)

        async def timeout_side_effect(*args, **kwargs):
            await asyncio.sleep(1.1)

        mock_func.side_effect = timeout_side_effect

        with patch("core.tasks.logger.error") as mock_error:
            await registry.run_task_manually("timeout.task")
            await asyncio.sleep(1.2)  # Vazifaning timeout bo'lishini kutish

            mock_error.assert_called_once_with("Vazifa 'timeout.task' belgilangan 1 soniyada yakunlanmadi. (Urinish 1/1)")

        assert task.status == "failed"
        assert isinstance(task.last_error, asyncio.TimeoutError)

    @pytest.mark.asyncio
    async def test_on_failure_callback_exception(self, registry: TaskRegistry):
        """on_failure callback'i xato berganda uni qayta ishlashni tekshirish."""
        mock_func = AsyncMock(side_effect=ValueError("Main task error"))
        mock_on_failure = AsyncMock(side_effect=Exception("Callback error"))
        task = Task(key="on_failure.exception", func=mock_func, retries=0, on_failure=mock_on_failure)
        registry.add_task(task)

        with patch("core.tasks.logger.error") as mock_error:
            await registry.run_task_manually("on_failure.exception")
            await asyncio.sleep(0.1)  # Fon vazifasini kutish

            # Asosiy xato va callback xatosi log qilinganini tekshirish
            assert mock_error.call_count == 2
            # Birinchi xato - barcha urinishlar muvaffaqiyatsiz bo'lgani haqida
            assert f"Vazifa '{task.key}' barcha urinishlardan so'ng ham muvaffaqiyatsiz yakunlandi" in mock_error.call_args_list[0].args[0]
            # Ikkinchi xato - on_failure callback'i o'zi xato bergani haqida
            assert f"'on_failure' callback'ini bajarishda xato" in mock_error.call_args_list[1].args[0]

        assert task.status == "failed"
        mock_on_failure.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_singleton_task_is_skipped(self, registry: TaskRegistry, mock_db: AsyncMock):
        """Singleton task bir vaqtda ikki marta ishga tushmasligini tekshirish."""
        slow_func_event = asyncio.Event()

        async def slow_func():
            await slow_func_event.wait()

        task = Task(key="singleton.task", func=slow_func, max_concurrent_runs=1)
        registry.add_task(task)

        first_run_task = asyncio.create_task(registry.run_task_manually("singleton.task"))
        await asyncio.sleep(0.01)

        assert "singleton.task" in registry.get_running_tasks()
        assert task.status == "running"

        with patch("loguru.logger.warning") as mock_warn:
            result = await registry.run_task_manually("singleton.task")
            assert result is False
            mock_warn.assert_called_once_with(f"Vazifa '{task.key}' ishga tushirilmadi, chunki uning yagona nusxasi allaqachon ishlamoqda.")
        # run_task_manually dagi o'zgarish tufayli endi bu yerda log yoziladi
        await asyncio.sleep(0.1)  # log_task_execution asinxron chaqirilishini kutish
        mock_db.log_task_execution.assert_called_once_with(task.key, 0, "SKIPPED", "Singleton vazifa allaqachon ishlamoqda.")

        assert task.status == "skipped"

        slow_func_event.set()
        await first_run_task
        await asyncio.sleep(0.01)

        assert "singleton.task" not in registry.get_running_tasks()
        assert task.status == "success"

    @pytest.mark.asyncio
    async def test_run_task_manually_non_existent(self, registry: TaskRegistry):
        """Mavjud bo'lmagan taskni qo'lda ishga tushirishda xatolikni tekshirish."""
        with patch("core.tasks.logger.error") as mock_error:
            result = await registry.run_task_manually("non_existent_manual.task")
            assert result is False
            mock_error.assert_called_once()
            assert "Qo'lda ishga tushirish uchun vazifa topilmadi: 'non_existent_manual.task'" in mock_error.call_args[0][0]

    @pytest.mark.asyncio
    async def test_run_task_manually_dependency_fail(self, registry: TaskRegistry):
        """Qo'lda ishga tushirilgan taskning bog'liqligi tayyorlanishi muvaffaqiyatsiz tugasa."""

        @registry.register(key="fail_dep.task")
        async def task_with_client_dep(client):
            pass

        with patch("core.tasks.logger.error") as mock_error:
            result = await registry.run_task_manually("fail_dep.task")
            assert result is False
            await asyncio.sleep(0.01)  # Xatolik logi yozilishini kutish
            mock_error.assert_called_once()
            assert "Vazifa 'fail_dep.task' uchun 'account_id' topilmadi." in mock_error.call_args[0][0]

        task = registry.get_task("fail_dep.task")
        assert task is not None
        assert task.status == "failed_dependency"

    @pytest.mark.asyncio
    async def test_task_with_traceback_logging(self, registry: TaskRegistry, mock_db: AsyncMock):
        """Xatolik yuz berganda traceback to'liq log qilinishini tekshirish."""
        traceback_str = "Test Traceback"
        try:
            raise ValueError("Traceback Test")
        except ValueError:
            traceback_str = traceback.format_exc()

        mock_func = AsyncMock(side_effect=ValueError("Doimiy xato"))
        # _execute_task_with_retries ichidagi traceback.format_exc() ni patch qilamiz
        with patch("traceback.format_exc", return_value=traceback_str):
            task = Task(key="traceback.task", func=mock_func, retries=0)
            registry.add_task(task)
            await registry.run_task_manually("traceback.task")
            await asyncio.sleep(0.1)

        mock_db.log_task_execution.assert_called_once_with("traceback.task", ANY, "FAILURE", traceback_str)

    @pytest.mark.asyncio
    async def test_multiple_concurrent_runs(self, registry: TaskRegistry):
        """Bir vaqtda bir nechta vazifa nusxasi ishga tushishini tekshirish."""
        first_task_started = asyncio.Event()
        second_task_started = asyncio.Event()
        tasks_can_finish = asyncio.Event()
        call_count = 0

        async def concurrent_func():
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                first_task_started.set()
            else:
                second_task_started.set()
            await tasks_can_finish.wait()

        task = Task(key="concurrent.task", func=concurrent_func, max_concurrent_runs=2)
        registry.add_task(task)

        # Vazifalarni ishga tushiramiz
        run1 = asyncio.create_task(registry.run_task_manually("concurrent.task"))
        run2 = asyncio.create_task(registry.run_task_manually("concurrent.task"))

        # Ikkala vazifa ham boshlanishini kutamiz
        await asyncio.wait_for(first_task_started.wait(), timeout=1)
        await asyncio.wait_for(second_task_started.wait(), timeout=1)

        # Endi ikkala vazifa ham aktiv bo'lishi kerak
        assert task.current_active_runs == 2
        assert call_count == 2

        # Vazifalarni yakunlaymiz
        tasks_can_finish.set()
        await asyncio.gather(run1, run2)
        await asyncio.sleep(0.01)
        assert task.current_active_runs == 0


@pytest.mark.asyncio
class TestDependencyInjection:
    """Bog'liqliklarni vazifaga to'g'ri uzatishni tekshirish."""

    async def test_dependencies_are_injected(self, registry: TaskRegistry, mock_db, mock_state, mock_config, mock_client_manager):
        mock_task_func = AsyncMock()

        @registry.register("deps.task")
        async def my_deps_task(client, db, state, config, **kwargs):
            await mock_task_func(client=client, db=db, state=state, config=config)

        await registry.run_task_manually("deps.task", account_id=123)
        await asyncio.sleep(0.01)

        mock_task_func.assert_awaited_once()
        _, kwargs = mock_task_func.call_args
        assert kwargs['db'] == mock_db
        assert kwargs['state'] == mock_state
        assert kwargs['config'] == mock_config
        assert kwargs['client'] == mock_client_manager.get_client(123)

    @pytest.mark.parametrize(
        "dependency_name, manager_attr, expected_log_part",
        [
            ("client", "_client_manager", "TaskRegistry uchun ClientManager o'rnatilmagan."),
            ("db", "_db", "TaskRegistry uchun Database instance o'rnatilmagan."),
            ("state", "_state", "TaskRegistry uchun AppState instance o'rnatilmagan."),
            ("config", "_config", "TaskRegistry uchun ConfigManager instance o'rnatilmagan."),
        ],
    )
    async def test_prepare_dependencies_missing_manager(self, registry: TaskRegistry, dependency_name, manager_attr, expected_log_part):
        """Menejer (client, db, state, config) o'rnatilmaganda bog'liqlik tayyorlash xatoligini tekshirish."""

        original_manager = getattr(registry, manager_attr)
        setattr(registry, manager_attr, None)

        async def _dynamic_task_func(**kwargs):
            pass

        param_kind = inspect.Parameter.POSITIONAL_OR_KEYWORD
        new_params = [inspect.Parameter(dependency_name, param_kind), inspect.Parameter('kwargs', inspect.Parameter.VAR_KEYWORD)]
        _dynamic_task_func.__signature__ = inspect.Signature(new_params)  # type: ignore

        registry.register(key=f"dep_missing_{dependency_name}.task")(_dynamic_task_func)

        with patch("loguru.logger.error") as mock_error:
            account_id_val = 123 if dependency_name == "client" else None
            result = await registry.run_task_manually(f"dep_missing_{dependency_name}.task", account_id=account_id_val)
            assert result is False
            mock_error.assert_called_once()

            assert expected_log_part in mock_error.call_args[0][0]

        setattr(registry, manager_attr, original_manager)

    @pytest.mark.asyncio
    async def test_prepare_dependencies_client_not_ready(self, registry: TaskRegistry, mock_client_manager: MagicMock):
        """Client ulanmaganligi sababli bog'liqlik tayyorlash xatoligini tekshirish."""
        mock_client = AsyncMock()
        mock_client.is_connected = AsyncMock(return_value=False)
        mock_client_manager.get_client.return_value = mock_client

        @registry.register("client_not_ready.task")
        async def task_with_client_dep(client):
            pass

        with patch("loguru.logger.warning") as mock_warn:
            result = await registry.run_task_manually("client_not_ready.task", account_id=456)
            assert result is False
            mock_warn.assert_called_once_with("Vazifa 'client_not_ready.task' uchun klient (ID: 456) topilmadi yoki ulanmagan.")

        task = registry.get_task("client_not_ready.task")
        assert task is not None
        assert task.status == "failed_dependency"
        assert isinstance(task.last_error, RuntimeError)

    @pytest.mark.asyncio
    async def test_dependency_client_missing_account_id(self, registry: TaskRegistry):
        """`client` bog'liqligi uchun `account_id` berilmagan holatini tekshirish."""

        @registry.register("client_missing_id.task")
        async def task_with_client(client):
            pass

        with patch("core.tasks.logger.error") as mock_error:
            result = await registry.run_task_manually("client_missing_id.task")
            assert result is False
            mock_error.assert_called_once_with("Vazifa 'client_missing_id.task' uchun 'account_id' topilmadi. Vazifa to'xtatildi.")

    @pytest.mark.asyncio
    async def test_account_id_is_popped_from_kwargs(self, registry: TaskRegistry):
        """`account_id` vazifa funksiyasiga uzatilmasligini tekshirish (agar u argument sifatida bo'lmasa)."""
        mock_func = AsyncMock()

        @registry.register("kwarg_pop.task")
        async def my_task_without_account_id(client, **kwargs):
            await mock_func(client=client, **kwargs)

        await registry.run_task_manually("kwarg_pop.task", account_id=123, other_arg="test")
        await asyncio.sleep(0.01)

        mock_func.assert_awaited_once()
        _, called_kwargs = mock_func.call_args
        assert "account_id" not in called_kwargs
        assert called_kwargs.get("other_arg") == "test"


class TestRegistryUtilityMethods:
    """TaskRegistryning yordamchi metodlarini test qilish."""

    @pytest.mark.asyncio
    async def test_get_running_tasks_empty(self, registry: TaskRegistry):
        """Ishlayotgan tasklar ro'yxati bo'shligini tekshirish."""
        assert registry.get_running_tasks() == set()

    @pytest.mark.asyncio
    async def test_get_task_status_non_existent(self, registry: TaskRegistry):
        """Mavjud bo'lmagan task statusini olishni tekshirish."""
        assert registry.get_task_status("non_existent.status") is None

    @pytest.mark.asyncio
    async def test_get_task_status_existing(self, registry: TaskRegistry):
        """Mavjud task statusini olishni tekshirish."""
        task_obj = Task(key="status.task", func=AsyncMock())
        registry.add_task(task_obj)
        status = registry.get_task_status("status.task")
        assert status is not None
        assert status['key'] == "status.task"
        assert status['status'] == "pending"

    @pytest.mark.asyncio
    async def test_get_all_task_statuses(self, registry: TaskRegistry):
        """Barcha tasklarning statuslarini olishni tekshirish."""
        task1 = Task(key="all.task1", func=AsyncMock())
        task2 = Task(key="all.task2", func=AsyncMock())
        registry.add_task(task1)
        registry.add_task(task2)

        all_statuses = registry.get_all_task_statuses()

        assert len(all_statuses) == 4
        assert any(s['key'] == 'all.task1' for s in all_statuses)
        assert any(s['key'] == 'system.cleanup_db' for s in all_statuses)

    @pytest.mark.asyncio
    async def test_list_tasks_method(self, registry: TaskRegistry):
        """list_tasks metodini tekshirish."""
        task1 = Task(key="list.task1", func=AsyncMock())
        registry.add_task(task1)
        tasks_list = registry.list_tasks()

        assert len(tasks_list) == 3
        assert tasks_list[0].key == "system.cleanup_db"
        assert tasks_list[2].key == "list.task1"

    @pytest.mark.asyncio
    async def test_clear_method(self, registry: TaskRegistry):
        """clear metodini tekshirish."""
        task1 = Task(key="clear.task1", func=AsyncMock())
        registry.add_task(task1)
        assert registry.get_task("clear.task1") is not None
        registry.clear()
        assert registry.get_task("clear.task1") is None
        assert registry.get_all_task_statuses() == []


class TestTaskRunner:
    """Scheduler orqali ishlaydigan get_task_runner metodini test qilish."""

    @pytest.mark.asyncio
    async def test_get_task_runner_not_found(self, registry: TaskRegistry):
        """get_task_runner task topilmaganda None qaytarishini tekshirish."""
        with patch("core.tasks.logger.error") as mock_error:
            runner = registry.get_task_runner("non_existent.runner")
            assert runner is None
            mock_error.assert_called_once()
            assert "Scheduler uchun vazifa topilmadi:" in mock_error.call_args[0][0]

    @pytest.mark.asyncio
    async def test_get_task_runner_success(self, registry: TaskRegistry):
        """get_task_runner muvaffaqiyatli task runner qaytarishini tekshirish."""
        mock_func = AsyncMock()
        task = Task(key="runner.task", func=mock_func)
        registry.add_task(task)

        runner = registry.get_task_runner("runner.task", job_kwargs={"account_id": 123})
        assert asyncio.iscoroutinefunction(runner)

        with patch.object(registry, '_prepare_and_run', new=AsyncMock()) as mock_prepare_and_run:
            await runner()
            mock_prepare_and_run.assert_awaited_once_with(task, {"account_id": 123})


class TestSystemTasks:
    """Tizim vazifalarini test qilish."""

    @pytest.mark.asyncio
    async def test_cleanup_db_task_execution_and_error(self, registry: TaskRegistry, mock_db: AsyncMock, mock_config: MagicMock):
        """cleanup_old_database_entries taskini bajarish va undagi xatolikni tekshirish."""
        mock_db.execute.return_value = 5
        mock_db.execute.side_effect = None  # Oldingi testlardan qolgan side_effect'ni tozalash

        with patch("core.tasks.logger.info") as mock_info, patch("core.tasks.logger.success") as mock_success:
            await registry.run_task_manually("system.cleanup_db")
            await asyncio.sleep(0.1)

            mock_info.assert_any_call(f"🧹 Ma'lumotlar bazasini tozalash vazifasi ishga tushdi. {mock_config.get.return_value} kundan eski yozuvlar o'chiriladi...")
            mock_success.assert_any_call("✅ Ma'lumotlar bazasini tozalash vazifasi muvaffaqiyatli yakunlandi. Jami 5 ta yozuv o'chirildi.")
            mock_db.execute.assert_awaited_once_with(f"DELETE FROM test_table WHERE test_date_col < date('now', '-{mock_config.get.return_value} days')")

        mock_db.reset_mock()
        # Endi xatolik holatini tekshiramiz
        mock_db.execute.side_effect = DatabaseError("DB cleanup failed")
        with patch("core.tasks.logger.exception") as mock_exception:
            await registry.run_task_manually("system.cleanup_db")
            await asyncio.sleep(0.1)

            mock_exception.assert_called_once()
            assert "Ma'lumotlar bazasini tozalash vaqtida xatolik yuz berdi" in mock_exception.call_args[0][0]

    @pytest.mark.asyncio
    async def test_vacuum_db_task_execution_and_error(self, registry: TaskRegistry, mock_db: AsyncMock):
        """vacuum_database taskini bajarish va undagi xatolikni tekshirish."""
        mock_db.vacuum.return_value = None
        mock_db.vacuum.side_effect = None  # Oldingi testlardan qolgan side_effect'ni tozalash

        with patch("core.tasks.logger.info") as mock_info, patch("core.tasks.logger.success") as mock_success:
            await registry.run_task_manually("system.vacuum_db")
            await asyncio.sleep(0.1)

            mock_info.assert_any_call("⚙️ Ma'lumotlar bazasida VACUUM operatsiyasi boshlandi...")
            mock_db.vacuum.assert_awaited_once()
            mock_success.assert_any_call("✅ Ma'lumotlar bazasi muvaffaqiyatli VACUUM qilindi.")

        mock_db.reset_mock()
        # Endi xatolik holatini tekshiramiz
        mock_db.vacuum.side_effect = DatabaseError("VACUUM failed")
        with patch("core.tasks.logger.exception") as mock_exception:
            await registry.run_task_manually("system.vacuum_db")
            await asyncio.sleep(0.1)

            mock_exception.assert_called_once()
            assert "Ma'lumotlar bazasini VACUUM qilishda xatolik yuz berdi" in mock_exception.call_args[0][0]
