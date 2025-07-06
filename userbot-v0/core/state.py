import asyncio
import json
import shutil
import time
from collections import defaultdict
from contextlib import asynccontextmanager, suppress
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Set, Tuple, Union

from loguru import logger
import aiofiles
from .config import BASE_DIR
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from core.app_context import AppContext


class AppState:
    """
    Ilovaning holatini boshqarish uchun modernizatsiya qilingan klass.
    "Deadlock" xavfisiz, barqaror va testlash uchun qulay.

    **MAQSAD:** Bu klass dasturning uzluksiz ishlashi uchun muhim bo'lgan holat ma'lumotlarini
    (masalan, restart bayroqlari, aktiv akkauntlarning joriy holati, dinamik sozlamalar,
    o'chirilgan buyruqlar holati, vaqtinchalik sudo rejimi) saqlash va boshqarishga mo'ljallangan.
    Bu ma'lumotlar odatda diskda saqlanadi va dastur qayta ishga tushganda tiklanadi.
    Agar bu ma'lumotlar yo'qolsa, dasturning ishlashida jiddiy muammolar yuzaga kelishi mumkin.
    TTL mexanizmi ushbu holatdagi ba'zi vaqtincha yashash muddatiga ega bo'lgan
    elementlar uchun qo'llaniladi, lekin asosiy e'tibor barqarorlik va tiklanishga qaratilgan.
    """

    def __init__(self, state_file: Optional[Path] = None, _test_mode: bool = False, _cleanup_sleep_duration: float = 30.0):
        self._state: Dict[str, Any] = {}
        self._cleanup_sleep_duration = _cleanup_sleep_duration

        self.app_context: Optional["AppContext"] = None

        self._listeners: Dict[str, List[Callable]] = defaultdict(list)
        self._persistent_keys: Set[str] = set()
        self._lock = asyncio.Lock()
        self._state_file = state_file or (BASE_DIR / "data" / "app_state.json")
        self._backup_file = self._state_file.with_suffix(".json.bak")
        self._ttl_entries: Dict[str, float] = {}
        self._cleanup_task: Optional[asyncio.Task] = None
        self._history: Dict[str, List[Tuple[float, Any]]] = defaultdict(list)
        self._in_batch_update: bool = False
        self._changed_keys_in_batch: Set[str] = set()
        self._state_file.parent.mkdir(parents=True, exist_ok=True)
        logger.debug(f"AppState yaratildi, _cleanup_sleep_duration={self._cleanup_sleep_duration}")

    def get(self, key: str, default: Optional[Any] = None) -> Any:
        """Holatdan kalit bo'yicha qiymatni oladi (qulfsiz, tez)."""
        logger.debug(f"GET: {key}")
        keys = key.split('.')
        val = self._state
        try:
            for k in keys:
                val = val[k]
            return val
        except (KeyError, TypeError):
            logger.debug(f"GET: '{key}' topilmadi, standart qiymat qaytarildi.")
            return default
        
        
    def get_remaining_ttl(self, key: str) -> Optional[float]:
        """
        Berilgan kalit uchun qolgan yashash vaqtini (TTL) soniyalarda qaytaradi.
        Agar kalit mavjud bo'lmasa yoki uning TTL'i bo'lmasa, None qaytaradi.
        """
        expiration_time = self._ttl_entries.get(key)
        if expiration_time is None:
            return None
        
        remaining = expiration_time - time.monotonic()
        return remaining if remaining > 0 else 0.0


    async def set(self, key: str, value: Any, *, persistent: bool = False, ttl_seconds: Optional[Union[int, float]] = None, validator: Optional[Callable[[Any], bool]] = None):
        """Holatda kalit bo'yicha qiymatni o'rnatadi."""
        logger.debug(f"SET: '{key}'='{value}' boshlandi. Persistent: {persistent}, TTL: {ttl_seconds}")
        if validator and not validator(value):
            logger.error(f"Qiymat validatsiyadan o'tmadi: '{key}'")
            return False

        if self.get(key) == value:
            logger.debug(f"SET: '{key}' uchun qiymat o'zgarmadi, NO-OP.")
            return True

        if self._in_batch_update:
            logger.debug(f"SET: '{key}' batch ichida. Internal set chaqirilmoqda.")
            self._internal_set(key, value, persistent, ttl_seconds)
        else:
            logger.debug(f"SET: '{key}' batchda emas. Qulf olinmoqda.")
            async with self._lock:
                logger.debug(f"SET: '{key}' qulf olindi. Internal set chaqirilmoqda.")
                self._internal_set(key, value, persistent, ttl_seconds)
            logger.debug(f"SET: '{key}' qulf bo'shatildi.")

        await self._notify_listeners(key, value)
        logger.debug(f"SET: '{key}' yakunlandi.")
        return True

    async def update(self, key: str, update_func: Callable[[Any], Any], *, persistent: bool = False, ttl_seconds: Optional[Union[int, float]] = None, validator: Optional[Callable[[Any], bool]] = None):
        """Holatdagi kalit qiymatini berilgan funksiya yordamida yangilaydi."""
        logger.debug(f"UPDATE: '{key}' boshlandi.")
        async with self._lock:
            logger.debug(f"UPDATE: '{key}' uchun qulf olindi.")
            new_value = update_func(self.get(key))
            if validator and not validator(new_value):
                logger.error(f"Yangilangan qiymat validatsiyadan o'tmadi: '{key}'")
                return False

            self._internal_set(key, new_value, persistent, ttl_seconds)
            logger.debug(f"UPDATE: '{key}' internal set chaqirildi, qulf bo'shatildi.")

        await self._notify_listeners(key, new_value)
        logger.debug(f"UPDATE: '{key}' yakunlandi.")
        return True

    async def delete(self, key: str):
        """Holatdan kalitni va uning bo'sh ota-onalarini o'chiradi."""
        logger.debug(f"DELETE: '{key}' boshlandi.")
        async with self._lock:
            logger.debug(f"DELETE: '{key}' uchun qulf olindi.")
            keys = key.split('.')
            d = self._state
            try:
                for k in keys[:-1]:

                    if not isinstance(d, dict):
                        logger.debug(f"DELETE: '{key}' o'rta yo'l ({k}) dict emas. O'chirilmadi.")
                        return False
                    d = d[k]
                if keys[-1] not in d:
                    logger.debug(f"DELETE: '{key}' kalit topilmadi. O'chirilmadi.")
                    return False
                del d[keys[-1]]
                logger.debug(f"DELETE: '{key}' kalit o'chirildi.")
            except (KeyError, TypeError):
                logger.debug(f"DELETE: '{key}' ni o'chirishda xato (KeyError/TypeError). O'chirilmadi.")
                return False

            self._cleanup_metadata(key)
            logger.debug(f"DELETE: '{key}' metadata tozalandi.")

            for i in range(len(keys) - 2, -1, -1):
                parent_path = ".".join(keys[: i + 1])
                parent_dict = self.get(parent_path)
                if not isinstance(parent_dict, dict) or parent_dict:
                    logger.debug(f"DELETE: '{parent_path}' ota-ona bo'sh emas yoki dict emas, tozalash to'xtatildi.")
                    break

                grandparent_path = ".".join(keys[:i])
                if not grandparent_path:
                    logger.debug(f"DELETE: Eng yuqori darajadagi '{keys[0]}' kalit o'chirilmoqda.")
                    del self._state[keys[0]]
                else:
                    grandparent_dict = self.get(grandparent_path)
                    if isinstance(grandparent_dict, dict):
                        logger.debug(f"DELETE: '{parent_path}' ota-ona kaliti '{keys[i]}' bobo-ota dictdan o'chirilmoqda.")
                        del grandparent_dict[keys[i]]
                self._cleanup_metadata(parent_path)
                logger.debug(f"DELETE: '{parent_path}' ota-ona metadata tozalandi.")
            logger.debug(f"DELETE: '{key}' qulf bo'shatildi.")

        await self._notify_listeners(key, None)
        logger.debug(f"DELETE: '{key}' yakunlandi.")
        return True

    @asynccontextmanager
    async def batch_update(self):
        """
        Guruhli yangilanish uchun xavfsiz va deadlock'dan himoyalangan kontekst menejeri.
        """
        logger.debug("BATCH_UPDATE: kontekst menejeri boshlandi.")
        if self._in_batch_update:
            logger.debug("BATCH_UPDATE: Allaqachon batch ichida, to'g'ridan-to'g'ri yield.")
            yield
            return

        logger.debug("BATCH_UPDATE: Top-level batch, qulf olinmoqda.")
        await self._lock.acquire()
        self._in_batch_update = True
        self._changed_keys_in_batch.clear()

        try:
            yield
        finally:
            logger.debug("BATCH_UPDATE: kontekst menejeri yakunlanmoqda.")
            keys_to_notify = list(self._changed_keys_in_batch)
            notifications_to_send = {k: self.get(k) for k in keys_to_notify}

            self._changed_keys_in_batch.clear()
            self._in_batch_update = False
            self._lock.release()
            logger.debug("BATCH_UPDATE: qulf bo'shatildi, notifikatsiyalar yuborilmoqda.")

        if notifications_to_send:
            tasks = [self._notify_listeners(key, value) for key, value in notifications_to_send.items()]
            await asyncio.gather(*tasks)
            logger.debug(f"BATCH_UPDATE: {len(tasks)} ta notifikatsiya yuborildi.")
        logger.debug("BATCH_UPDATE: kontekst menejeri to'liq yakunlandi.")

    async def toggle(self, key: str, *, persistent: bool = False) -> bool:
        logger.debug(f"TOGGLE: '{key}' boshlandi.")
        result = await self.update(key, lambda v: not bool(v), persistent=persistent, validator=lambda x: isinstance(x, bool))
        logger.debug(f"TOGGLE: '{key}' yakunlandi, natija: {result}.")
        return result

    async def increment(self, key: str, amount: Union[int, float] = 1, *, persistent: bool = False) -> bool:
        logger.debug(f"INCREMENT: '{key}' boshlandi, miqdor: {amount}.")
        result = await self.update(key, lambda v: (v if isinstance(v, (int, float)) else 0) + amount, persistent=persistent, validator=lambda x: isinstance(x, (int, float)))
        logger.debug(f"INCREMENT: '{key}' yakunlandi, natija: {result}.")
        return result

    async def decrement(self, key: str, amount: Union[int, float] = 1, *, persistent: bool = False) -> bool:
        logger.debug(f"DECREMENT: '{key}' boshlandi, miqdor: {amount}.")
        result = await self.update(key, lambda v: (v if isinstance(v, (int, float)) else 0) - amount, persistent=persistent, validator=lambda x: isinstance(x, (int, float)))
        logger.debug(f"DECREMENT: '{key}' yakunlandi, natija: {result}.")
        return result

    async def list_append(self, key: str, value: Any, *, unique: bool = False, persistent: bool = False) -> bool:
        logger.debug(f"LIST_APPEND: '{key}' boshlandi, qiymat: '{value}', unique: {unique}.")

        def _append(current_list):
            current_list = current_list if isinstance(current_list, list) else []
            if not unique or value not in current_list:
                current_list.append(value)
            return current_list

        result = await self.update(key, _append, persistent=persistent, validator=lambda x: isinstance(x, list))
        logger.debug(f"LIST_APPEND: '{key}' yakunlandi, natija: {result}.")
        return result

    async def list_remove(self, key: str, value: Any, *, persistent: bool = False) -> bool:
        logger.debug(f"LIST_REMOVE: '{key}' boshlandi, qiymat: '{value}'.")

        def _remove(current_list):
            current_list = current_list if isinstance(current_list, list) else []
            if value in current_list:
                current_list.remove(value)
            return current_list

        result = await self.update(key, _remove, persistent=persistent, validator=lambda x: isinstance(x, list))
        logger.debug(f"LIST_REMOVE: '{key}' yakunlandi, natija: {result}.")
        return result

    def _internal_set(self, key: str, value: Any, persistent: bool, ttl_seconds: Optional[Union[int, float]]):
        """Qulfsiz ishlaydigan ichki `set` metodi."""
        logger.debug(f"INTERNAL_SET: '{key}'='{value}' chaqirildi.")
        keys = key.split('.')
        d = self._state
        for k in keys[:-1]:
            d = d.setdefault(k, {})
        d[keys[-1]] = value

        if persistent:
            self._persistent_keys.add(key)
        else:
            self._persistent_keys.discard(key)

        if ttl_seconds is not None:
            self._ttl_entries[key] = time.monotonic() + ttl_seconds
            self._ensure_cleanup_task()
        else:
            self._ttl_entries.pop(key, None)
            logger.debug(f"INTERNAL_SET: '{key}' uchun TTL yozuvi o'chirildi.")

        self._history[key].append((time.time(), value))
        logger.debug(f"INTERNAL_SET: '{key}' tarixga qo'shildi.")

    def _cleanup_metadata(self, key: str):
        """Kalit o'chirilganda uning metama'lumotlarini tozalaydi."""
        logger.debug(f"CLEANUP_METADATA: '{key}' uchun metadata tozalash.")
        self._persistent_keys.discard(key)
        self._ttl_entries.pop(key, None)
        self._history.pop(key, None)
        
    def _test_raise_exception_in_cleanup(self):
        """Bu metod faqat testlar uchun. Uni patchlab, xato chaqirish mumkin."""
        pass # Productionda hech narsa qilmaydi

    def on_change(self, key: str, callback: Callable):
        logger.debug(f"ON_CHANGE: '{key}' uchun tinglovchi qo'shildi.")
        self._listeners[key].append(callback)

    def remove_listener(self, key: str, callback: Callable):
        logger.debug(f"REMOVE_LISTENER: '{key}' uchun tinglovchi o'chirilmoqda.")
        if key in self._listeners:
            try:
                self._listeners[key].remove(callback)
                logger.debug(f"REMOVE_LISTENER: '{key}' dan tinglovchi muvaffaqiyatli o'chirildi.")
            except ValueError:
                logger.debug(f"REMOVE_LISTENER: '{key}' dan tinglovchi topilmadi.")
                pass

    async def _notify_listeners(self, key: str, value: Any):
        logger.debug(f"NOTIFY_LISTENERS: '{key}'='{value}' uchun notifikatsiya boshlandi.")
        if self._in_batch_update:
            self._changed_keys_in_batch.add(key)
            logger.debug(f"NOTIFY_LISTENERS: '{key}' batch ichida, notifikatsiya buferga olindi.")
            return

        async def _exec(cb):
            try:
                if asyncio.iscoroutinefunction(cb):
                    await cb(key, value)
                else:
                    await asyncio.to_thread(cb, key, value)
            except Exception:
                logger.exception(f"Listener xatosi: '{key}'")

        all_callbacks = self._listeners.get(key, [])
        for wild_key, callbacks in self._listeners.items():
            if wild_key.endswith('*') and key.startswith(wild_key[:-1]):
                all_callbacks.extend(callbacks)

        logger.debug(f"NOTIFY_LISTENERS: '{key}' uchun {len(all_callbacks)} ta tinglovchi topildi.")
        if all_callbacks:
            tasks = [asyncio.create_task(_exec(cb)) for cb in all_callbacks]
            await asyncio.gather(*tasks, return_exceptions=True)
            logger.debug(f"NOTIFY_LISTENERS: '{key}' tinglovchilariga xabar yuborildi.")
        logger.debug(f"NOTIFY_LISTENERS: '{key}' uchun notifikatsiya yakunlandi.")
        
    async def save_to_disk(self):
        logger.debug("SAVE_TO_DISK: boshlandi.")
        persistent_state = {}
        async with self._lock:
            logger.debug("SAVE_TO_DISK: qulf olindi.")
            persistent_state = {key: self.get(key) for key in self._persistent_keys}
        try:
            # Mavjud faylni zaxiraga o'tkazish (bloklanmaydigan usulda)
            if await asyncio.to_thread(self._state_file.exists):
                # .bak fayli allaqachon mavjud bo'lsa, avval uni o'chiramiz
                if await asyncio.to_thread(self._backup_file.exists):
                    await asyncio.to_thread(self._backup_file.unlink)
                await asyncio.to_thread(self._state_file.replace, self._backup_file)
                logger.debug(f"SAVE_TO_DISK: Mavjud holat '{self._backup_file}' ga zaxirlandi.")

            async with aiofiles.open(self._state_file, "w", encoding="utf-8") as f:
                await f.write(json.dumps(persistent_state, indent=2, ensure_ascii=False))
            logger.debug(f"SAVE_TO_DISK: holat '{self._state_file}' ga muvaffaqiyatli saqlandi.")
        except Exception:
            logger.exception("Holatni saqlashda xato")
        finally:
            logger.debug("SAVE_TO_DISK: yakunlandi.")





    async def load_from_disk(self):
        logger.debug("LOAD_FROM_DISK: boshlandi.")
        file_to_try = self._state_file if self._state_file.exists() else self._backup_file
        if not file_to_try.exists():
            logger.debug(f"LOAD_FROM_DISK: '{file_to_try}' va zaxira fayl topilmadi. Yuklash o'tkazib yuborildi.")
            return
        try:
            async with aiofiles.open(file_to_try, "r", encoding="utf-8") as f:
                data = json.loads(await f.read())
            async with self._lock:
                for key, value in data.items():
                    self._internal_set(key, value, persistent=True, ttl_seconds=None)
            logger.debug(f"LOAD_FROM_DISK: Holat '{file_to_try}' dan muvaffaqiyatli yuklandi.")
        except Exception:
            logger.exception("Holatni yuklashda xato")
        finally:
            logger.debug("LOAD_FROM_DISK: yakunlandi.")

    def _ensure_cleanup_task(self):
        logger.debug(f"_ENSURE_CLEANUP_TASK: Vazifa holati tekshirilmoqda.")
        if not self._cleanup_task or self._cleanup_task.done():
            self._cleanup_task = asyncio.create_task(self._run_state_cleanup_task())
            logger.debug("_ENSURE_CLEANUP_TASK: Yangi tozalash vazifasi yaratildi.")

    async def _run_state_cleanup_task(self):
        logger.debug("_RUN_STATE_CLEANUP_TASK: Fon vazifasi boshlandi.")
        while True:
            try:
                logger.debug(f"_RUN_STATE_CLEANUP_TASK: Keyingi uyquga tayyorlanmoqda, duration={self._cleanup_sleep_duration}.")
                await asyncio.sleep(self._cleanup_sleep_duration)
                logger.debug("_RUN_STATE_CLEANUP_TASK: Uyqu yakunlandi. Tozalashni boshlash.")
                self._test_raise_exception_in_cleanup() # <-- Bu yerda xato keltirib chiqarish uchun chaqiramiz

                now = time.monotonic()
                keys_to_delete = [k for k, exp in self._ttl_entries.items() if now >= exp]

                if keys_to_delete:
                    logger.debug(f"_RUN_STATE_CLEANUP_TASK: {len(keys_to_delete)} ta TTL eskirgan kalitlar topildi: {keys_to_delete}.")
                    for key in keys_to_delete:
                        # delete ichida qulf bor, shuning uchun bu yerda qo'shimcha qulf kerak emas
                        logger.debug(f"_RUN_STATE_CLEANUP_TASK: '{key}' kalitini o'chirishga harakat qilinmoqda.")
                        await self.delete(key)
                    logger.debug("_RUN_STATE_CLEANUP_TASK: TTL eskirgan kalitlar o'chirildi.")
                else:
                    logger.debug("_RUN_STATE_CLEANUP_TASK: TTL eskirgan kalitlar topilmadi.")
            except asyncio.CancelledError:
                logger.debug("_RUN_STATE_CLEANUP_TASK: Vazifa bekor qilindi (asyncio.CancelledError ushlandi). Tozalash vazifasi tugamoqda.")
                break # Vazifani to'xtatamiz
            except Exception as e:
                logger.exception(f"_RUN_STATE_CLEANUP_TASK: Kutilmagan xato ushlandi: {type(e).__name__}: {e}. logger.exception chaqirilmoqda.")
                # Kutilmagan xatodan keyin tiklanish uchun biroz kutish
                await asyncio.sleep(self._cleanup_sleep_duration * 5) # Bu yerda ham xato bo'lsa, try-except uni ushlaydi
            logger.debug("_RUN_STATE_CLEANUP_TASK: Tsikl yakunlandi, keyingi iteratsiyaga o'tish.")




    def dump(self) -> Dict[str, Any]:
        logger.debug("DUMP: Holat nusxasi qaytarilmoqda.")
        return self._state.copy()

    async def clear(self, protected_keys: Optional[Set[str]] = None):
        logger.debug(f"CLEAR: Holatni tozalash boshlandi. Himoyalangan kalitlar: {protected_keys}.")
        protected_keys = protected_keys or set()

        keys_to_delete_top_level = []

        async with self._lock:
            logger.debug("CLEAR: Qulf olindi.")

            current_top_level_keys = list(self._state.keys())

            for key in current_top_level_keys:
                if key not in protected_keys:
                    keys_to_delete_top_level.append(key)
                else:
                    logger.debug(f"CLEAR: '{key}' himoyalanganligi sababli o'chirilmadi.")
            logger.debug("CLEAR: Qulf bo'shatildi.")

        for key_to_delete in keys_to_delete_top_level:
            await self.delete(key_to_delete)

        logger.debug("CLEAR: Holat tozalash yakunlandi.")
