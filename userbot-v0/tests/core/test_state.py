import json
from loguru import logger
import pytest
import asyncio
import time
from pathlib import Path
from typing import AsyncGenerator
from unittest.mock import AsyncMock, patch, Mock
from contextlib import suppress

import pytest_asyncio
from core.state import AppState

pytestmark = pytest.mark.asyncio


@pytest.fixture
def disable_cleanup_task():
    """AppState ning ichki tozalash vazifasini testlar paytida o'chiradi."""
    with patch("core.state.AppState._ensure_cleanup_task", return_value=None):
        yield


# --- YENGI O'ZGARISH YAKUNLANGAN JOYI ---


@pytest_asyncio.fixture
async def state(tmp_path: Path, disable_cleanup_task) -> AsyncGenerator[AppState, None]:
    """
    Asosiy testlar uchun AppState yaratadi.
    Bu yerda tozalash vazifasi testlarga xalaqit bermasligi uchun o'chiriladi.
    """
    # `disable_cleanup_task` fixture'i `_ensure_cleanup_task` metodini patch qiladi.
    app_state = AppState(state_file=tmp_path / "app.json")
    yield app_state



    # --- OLDINGI O'ZGARISH: Fon vazifasini tozalash (Endi bu kamroq zarur, ammo xavfsizlik uchun qoldiramiz) ---
    if app_state._cleanup_task and not app_state._cleanup_task.done():
        print(f"--- [DEBUG] Fixture: _cleanup_task ni bekor qilish (ID: {id(app_state._cleanup_task)}) ---")
        app_state._cleanup_task.cancel()
        with suppress(asyncio.CancelledError):
            await app_state._cleanup_task
        print(f"--- [DEBUG] Fixture: _cleanup_task bekor qilindi ---")
    # --- OLDINGI O'ZGARISH YAKUNLANGAN JOYI ---
    print(f"--- [DEBUG] Fixture: Test tugadi (ID: {id(app_state)}) ---")


class TestBasicOperations:
    async def test_set_and_get_simple(self, state: AppState):
        await state.set("user.name", "John")
        assert state.get("user.name") == "John"

    async def test_get_non_existent_returns_default(self, state: AppState):
        assert state.get("user.age") is None
        assert state.get("user.age", 99) == 99

    async def test_get_invalid_path_returns_default(self, state: AppState):
        await state.set("user", "not_a_dict")
        assert state.get("user.name", "default") == "default"

    async def test_set_with_validator(self, state: AppState):
        validator = lambda x: isinstance(x, int) and x > 0
        await state.set("count", 10, validator=validator)
        assert await state.set("count", -5, validator=validator) is False

    async def test_set_same_value_is_noop(self, state: AppState):
        await state.set("key", "value")
        with patch.object(state, '_internal_set') as mock_internal_set:
            await state.set("key", "value")
            mock_internal_set.assert_not_called()

    async def test_update_operation(self, state: AppState):
        await state.set("counter", 5)
        await state.update("counter", lambda v: (v or 0) + 1)
        assert state.get("counter") == 6
        assert await state.update("counter", lambda v: "str", validator=lambda x: isinstance(x, int)) is False

    async def test_delete_and_cleanup_parents(self, state: AppState):
        await state.set("a.b.c.d", 1)
        await state.delete("a.b.c.d")
        assert state.get("a") is None

    async def test_toggle_operation(self, state: AppState):
        await state.set("feature.enabled", False)
        await state.toggle("feature.enabled")
        assert state.get("feature.enabled") is True
        await state.toggle("feature.enabled")
        assert state.get("feature.enabled") is False

    async def test_dump_returns_copy(self, state: AppState):
        await state.set("key1", "value1")
        await state.set("nested.key2", 123)
        dumped_state = state.dump()
        assert dumped_state == {"key1": "value1", "nested": {"key2": 123}}
        # Ensure it's a copy, not a reference
        dumped_state["key1"] = "changed"
        assert state.get("key1") == "value1"

    async def test_clear_state(self, state: AppState):
        await state.set("user.name", "Alice")
        await state.set("system.status", "active")
        await state.clear()
        assert state.get("user.name") is None
        assert state.get("system.status") is None

    async def test_clear_with_protected_keys(self, state: AppState):
        await state.set("user.name", "Bob")
        await state.set("system.version", "1.0")
        await state.set("temp.data", "abc")
        await state.clear(protected_keys={"system"})
        assert state.get("user.name") is None
        assert state.get("system.version") == "1.0"
        assert state.get("temp.data") is None

    async def test_delete_non_existent_key_path(self, state: AppState):
        await state.set("a.b.c", 1)
        assert await state.delete("a.b.d") is False  # Missing key in path
        assert state.get("a.b.c") == 1

        await state.set("x.y", {})  # x.y is dict but y.z.a is not
        assert await state.delete("x.y.z.a") is False
        assert state.get("x.y") == {}


    async def test_delete_with_non_dict_intermediate_node(self, state: AppState):
        """Yo'lning oraliq elementi dict bo'lmaganda delete to'g'ri ishlashini tekshiradi (to'g'ridan-to'g'ri ichki holatni buzish orqali)."""
        # Holatni testlash uchun ataylab "buzamiz": 'top_level' ostiga dict emas, string qo'yamiz
        state._state["top_level"] = "not_a_dictionary"

        # 'top_level.sub_key' ni o'chirishga urinish
        # Bu yerda `d` 'not_a_dictionary' bo'ladi va `isinstance(d, dict)` False bo'ladi.
        result = await state.delete("top_level.sub_key")

        assert result is False  # O'chirish muvaffaqiyatsiz bo'lishi kerak
        assert state.get("top_level") == "not_a_dictionary"  # Asl qiymat o'zgarmasligi kerak

        # Endi to'g'ridan-to'g'ri "buzilgan" tugunni o'chiramiz
        result = await state.delete("top_level")
        assert result is True
        assert state.get("top_level") is None


class TestHelperMethods:
    @pytest.mark.parametrize("initial, amount, expected_inc, expected_dec", [(5, 1, 6, 5), (None, 5, 5, 0), (10, -2, 8, 10)])
    async def test_increment_decrement(self, state: AppState, initial, amount, expected_inc, expected_dec):
        await state.set("counter", initial)
        await state.increment("counter", amount)
        assert state.get("counter") == expected_inc
        await state.decrement("counter", amount)
        assert state.get("counter") == expected_dec


class TestPersistenceAndTTL:
    async def test_save_and_load_persistent_state(self, state: AppState):
        await state.set("user.id", 123, persistent=True)
        await state.set("session.token", "xyz")
        await state.save_to_disk()
        new_state = AppState(state_file=state._state_file, _test_mode=True)
        await new_state.load_from_disk()
        assert new_state.get("user.id") == 123
        assert new_state.get("session.token") is None

    async def test_load_from_backup(self, state: AppState):
        await state.set("key", "value", persistent=True)
        await state.save_to_disk()
        state._state_file.rename(state._backup_file)
        new_state = AppState(state_file=state._state_file, _test_mode=True)
        await new_state.load_from_disk()
        assert new_state.get("key") == "value"

    async def test_load_from_corrupted_json(self, state: AppState):
        state._state_file.write_text("{'invalid_json':}")
        with patch("core.state.logger.exception") as mock_log:
            await state.load_from_disk()
            mock_log.assert_called_once()

    async def test_save_io_error(self, state: AppState):
        await state.set("key", "value", persistent=True)
        with patch("aiofiles.open", side_effect=IOError("Disk to'la")):
            with patch("core.state.logger.exception") as mock_log:
                await state.save_to_disk()
                mock_log.assert_called_once()

    async def test_ttl_expiration_logic(self, state: AppState):
        """Vaqti tugagan (TTL) kalit o'chirilishini tekshiradi (deadlock'siz)."""
        print("\n[DEBUG] test_ttl_expiration_logic: Boshlandi")
        await state.set("session", "token", ttl_seconds=10)
        print("[DEBUG] test_ttl_expiration_logic: TTL qiymat o'rnatildi")

        with patch("time.monotonic", return_value=time.monotonic() + 15):
            now = time.monotonic()
            keys_to_delete = [k for k, exp in state._ttl_entries.items() if now >= exp]
            print(f"[DEBUG] test_ttl_expiration_logic: O'chiriladigan kalitlar: {keys_to_delete}")

            for key in keys_to_delete:
                await state.delete(key)

        assert state.get("session") is None
        print("[DEBUG] test_ttl_expiration_logic: Tugadi")

    async def test_set_removes_ttl(self, state: AppState):
        await state.set("temp_key", "value", ttl_seconds=5)
        assert "temp_key" in state._ttl_entries
        await state.set("temp_key", "new_value", ttl_seconds=None)
        assert "temp_key" not in state._ttl_entries
        assert state.get("temp_key") == "new_value"

    async def test_load_from_disk_no_file_exists(self, tmp_path: Path):
        non_existent_state_file = tmp_path / "non_existent.json"
        state = AppState(state_file=non_existent_state_file, _test_mode=True)
        await state.load_from_disk()  # Should not raise error, just return
        assert state.get("any_key") is None
        
    async def test_save_creates_backup(self, state: AppState):
        """Asosiy state fayli mavjud bo'lganda zaxira nusxasi yaratilishini tekshirish."""
        # Birinchi marta saqlaymiz, .bak fayl hali yo'q
        await state.set("key", "value1", persistent=True)
        await state.save_to_disk()
        assert state._state_file.exists()
        assert not state._backup_file.exists()

        # Ikkinchi marta saqlaymiz, endi .bak fayli paydo bo'lishi kerak
        await state.set("key", "value2", persistent=True)
        await state.save_to_disk()
        assert state._backup_file.exists()

        # Zaxira faylida eski ma'lumot (value1) bo'lishi kerak
        with open(state._backup_file, "r") as f:
            backup_data = json.load(f)
            assert backup_data["key"] == "value1"



class TestListenersAndBatching:
    async def test_listeners_notified_on_change(self, state: AppState):
        listener = AsyncMock()
        state.on_change("system.status", listener)
        await state.set("system.status", "restarting")
        await asyncio.sleep(0.01)
        listener.assert_awaited_once_with("system.status", "restarting")

    async def test_wildcard_listener(self, state: AppState):
        listener = AsyncMock()
        state.on_change("user.*", listener)
        await state.set("user.name", "Alice")
        await asyncio.sleep(0.01)
        listener.assert_awaited_once_with("user.name", "Alice")

    async def test_batch_update_notifies_after(self, state: AppState):
        print("\n[DEBUG] test_batch_update: Boshlandi")
        listener = AsyncMock()
        state.on_change("key", listener)
        print("[DEBUG] test_batch_update: `async with` bloki boshlanmoqda")
        async with state.batch_update(): # type: ignore
            print("[DEBUG] test_batch_update: `async with` bloki ichida")
            await state.set("key", "value")
            listener.assert_not_awaited()
        print("[DEBUG] test_batch_update: `async with` bloki tugadi, xabarlar yuborilishi kerak")
        await asyncio.sleep(0.01)
        listener.assert_awaited_once_with("key", "value")
        print("[DEBUG] test_batch_update: Tugadi")

    async def test_remove_listener(self, state: AppState):
        listener1 = AsyncMock()
        listener2 = AsyncMock()
        state.on_change("test_key", listener1)
        state.on_change("test_key", listener2)
        assert len(state._listeners["test_key"]) == 2
        state.remove_listener("test_key", listener1)
        assert len(state._listeners["test_key"]) == 1
        assert state._listeners["test_key"][0] == listener2
        state.remove_listener("test_key", listener1)  # Trying to remove non-existent
        assert len(state._listeners["test_key"]) == 1

    async def test_notify_listeners_non_async_callback(self, state: AppState):
        # Sinxron tinglovchi uchun standart Mock ob'ektidan foydalanamiz
        sync_listener = Mock()  # BU QATOR O'ZGARTIRILGAN / QO'SHILGAN

        state.on_change("non_async_key", sync_listener)
        await state.set("non_async_key", "sync_value")
        await asyncio.sleep(0.01)  # to_thread bajarilishiga imkon berish uchun

        sync_listener.assert_called_once_with("non_async_key", "sync_value")

    async def test_nested_batch_update(self, state: AppState):
        listener = AsyncMock()
        state.on_change("nested_key", listener)

        async with state.batch_update():
            await state.set("nested_key", "value1")
            listener.assert_not_awaited()

            async with state.batch_update():  # Nested batch
                await state.set("nested_key", "value2")
                listener.assert_not_awaited()  # Still not awaited

            listener.assert_not_awaited()  # Still not awaited after inner batch exits

        await asyncio.sleep(0.01)
        listener.assert_awaited_once_with("nested_key", "value2")

    async def test_listener_exception_is_logged(self, state: AppState):
        """Tinglovchi xato bersa, logger.exception chaqirilishini tekshiradi."""
        print("\n[DEBUG] test_listener_exception_is_logged: Boshlandi")
        bad_listener = AsyncMock(side_effect=ValueError("Test xatosi"))
        state.on_change("key", bad_listener)

        with patch("core.state.logger.exception") as mock_log_exception:
            await state.set("key", "value")

            await asyncio.sleep(0.01)

            mock_log_exception.assert_called_once()

            assert "Listener xatosi" in mock_log_exception.call_args[0][0]

        print("[DEBUG] test_listener_exception_is_logged: Tugadi")


class TestCollectionOperations:
    async def test_list_append_basic(self, state: AppState):
        await state.list_append("my_list", 1)
        assert state.get("my_list") == [1]
        await state.list_append("my_list", 2)
        assert state.get("my_list") == [1, 2]

    async def test_list_append_unique(self, state: AppState):
        await state.list_append("unique_list", "a", unique=True)
        assert state.get("unique_list") == ["a"]
        await state.list_append("unique_list", "a", unique=True)
        assert state.get("unique_list") == ["a"]
        await state.list_append("unique_list", "b", unique=True)
        assert state.get("unique_list") == ["a", "b"]

    async def test_list_append_non_list_initial(self, state: AppState):
        await state.set("not_a_list", "some_string")
        await state.list_append("not_a_list", 10)
        assert state.get("not_a_list") == [10]

    async def test_list_remove_basic(self, state: AppState):
        await state.list_append("removable_list", "x")
        await state.list_append("removable_list", "y")
        await state.list_remove("removable_list", "x")
        assert state.get("removable_list") == ["y"]
        await state.list_remove("removable_list", "z")  # Non-existent
        assert state.get("removable_list") == ["y"]

    async def test_list_remove_non_list_initial(self, state: AppState):
        await state.set("another_not_list", "test_string")
        await state.list_remove("another_not_list", "test_string")
        assert state.get("another_not_list") == []  # Should initialize as empty list and then remove



class TestCleanupTask:
    """Tozalash vazifasini (_run_state_cleanup_task) alohida test qilish uchun sinf."""

    @pytest_asyncio.fixture
    async def state_with_cleanup(self, tmp_path: Path) -> AsyncGenerator[AppState, None]:
        """Tozalash vazifasi YOQILGAN holda AppState yaratadi."""
        # Bu fixture hech qanday patch'siz ishlaydi, shuning uchun asl _ensure_cleanup_task chaqiriladi
        state = AppState(state_file=tmp_path / "cleanup_test.json", _cleanup_sleep_duration=0.05)
        yield state
        # Testdan keyin vazifani to'xtatish
        if state._cleanup_task and not state._cleanup_task.done():
            state._cleanup_task.cancel()
            with suppress(asyncio.CancelledError):
                await state._cleanup_task


    async def test_cleanup_task_removes_expired_key(self, state_with_cleanup: AppState):
        """Fon vazifasi vaqti o'tgan kalitni o'chirishini tekshirish."""
        state = state_with_cleanup
        await state.set("temp", "data", ttl_seconds=0.1)
        assert state.get("temp") == "data"
        await asyncio.sleep(0.2)
        assert state.get("temp") is None

    async def test_cleanup_task_handles_cancelled_error(self, state_with_cleanup: AppState):
        """Fon vazifasi bekor qilinganda to'g'ri yakunlanishini tekshirish."""
        state = state_with_cleanup
        await state.set("dummy", "value", ttl_seconds=10)
        await asyncio.sleep(0.01)
        assert state._cleanup_task is not None
        assert not state._cleanup_task.done()

        state._cleanup_task.cancel()
        await asyncio.sleep(0.01)
        assert state._cleanup_task.done()

    async def test_cleanup_task_handles_exception(self, state_with_cleanup: AppState):
        """Fon vazifasi ichida kutilmagan xato yuz berganda log yozilishini tekshiradi."""
        state = state_with_cleanup
        # Tozalash vazifasining tezroq ishlashi uchun sleep vaqtini nolga tenglashtiramiz.
        # Bu, patched xatoning darhol ko'tarilishini ta'minlaydi va CancelledError dan oldin ishlov berish imkonini oshiradi.
        state._cleanup_sleep_duration = 0.000001 # Yoki hatto 0 ni ishlatish mumkin
        logger.debug(f"[Test] state._cleanup_sleep_duration '{state._cleanup_sleep_duration}' ga o'rnatildi.")

        await state.set("dummy", "value", ttl_seconds=10)
        logger.debug("[Test] 'dummy' kalit o'rnatildi, TTL bilan. Cleanup task ishga tushishi kerak.")
        await asyncio.sleep(0.001) # Vazifaning ishga tushishini kutish uchun juda qisqa kutish
        logger.debug("[Test] Initial sleep yakunlandi. Patch va kutish boshlanmoqda.")


        _error_triggered = False # Xato bir marta chaqirilganini kuzatish uchun bayroq

        def _one_time_error_side_effect(*args, **kwargs):
            nonlocal _error_triggered
            if not _error_triggered:
                _error_triggered = True
                raise ValueError("Test Exception")
            # Birinchi chaqiruvdan keyin hech qanday xato chiqarmaydi (implicit None return)

        with patch.object(state, "_test_raise_exception_in_cleanup", side_effect=_one_time_error_side_effect), \
             patch("core.state.logger.exception") as mock_log:

            logger.debug("[Test] '_test_raise_exception_in_cleanup' va 'logger.exception' patchlari faollashtirildi.")
            # Endi testning o'zining asyncio.sleep chaqiruvlari patchdan xato chiqarmaydi,
            # shuning uchun try-except bloklari kerak emas.
            logger.debug("[Test] Patch ichida birinchi 'asyncio.sleep(0.1)' chaqirilmoqda.")
            await asyncio.sleep(0.1) # Bu endi xato chiqarmaydi
            logger.debug("[Test] Birinchi 'asyncio.sleep' xatosiz yakunlandi.")

            # Fon vazifasi ichidagi patched metod ishga tushib, xatoni loglayotganini tekshiramiz.
            timeout = 1.0 # Maksimal kutish vaqti - biroz ko'proq vaqt beramiz
            start_time = time.time()
            logger.debug(f"[Test] 'mock_log.called' kutish tsikli boshlanmoqda, timeout={timeout}.")
            while not mock_log.called and (time.time() - start_time) < timeout:
                logger.debug("[Test] Polling tsikli ichida 'asyncio.sleep(0.005)' chaqirilmoqda.")
                await asyncio.sleep(0.005) # Bu endi xato chiqarmaydi
                logger.debug("[Test] Polling tsikli ichida 'asyncio.sleep(0)' chaqirilmoqda.")
                await asyncio.sleep(0) # Bu endi xato chiqarmaydi
            
            logger.debug(f"[Test] Polling tsikli yakunlandi. mock_log.called: {mock_log.called}.")
            mock_log.assert_called_once()
            assert "Kutilmagan xato" in mock_log.call_args[0][0]


            logger.debug(f"[Test] Polling tsikli yakunlandi. mock_log.called: {mock_log.called}.")
            mock_log.assert_called_once()
            assert "Kutilmagan xato" in mock_log.call_args[0][0]
            logger.debug("[Test] Test muvaffaqiyatli yakunlandi.")

