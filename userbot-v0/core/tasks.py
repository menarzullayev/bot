import asyncio
import inspect
import random
import time
import traceback
from dataclasses import dataclass, field
from typing import Callable, Dict, Set, Any, Optional, List, TYPE_CHECKING, Coroutine, Hashable

from loguru import logger


from .exceptions import DatabaseError, QueryError


if TYPE_CHECKING:
    from .client_manager import ClientManager
    from .database import AsyncDatabase
    from .state import AppState
    from .config_manager import ConfigManager
    from .app_context import AppContext

@dataclass
class FailureContext:
    task: 'Task'
    exception: Exception
    traceback_str: Optional[str]
    attempt: int
    kwargs: Dict[str, Any]


@dataclass
class Task:
    key: str
    func: Callable[..., Any]
    description: str = "Tavsif berilmagan"
    timeout: Optional[int] = None
    retries: int = 0
    retry_delay: int = 5
    retry_backoff_factor: float = 2.0
    on_failure: Optional[Callable[[FailureContext], Coroutine[Any, Any, None]]] = None
    max_concurrent_runs: int = 1
    semaphore: asyncio.Semaphore = field(init=False, repr=False)
    status: str = "pending"
    last_run_time: Optional[float] = None
    last_run_duration: Optional[float] = None
    last_error: Optional[Exception] = None
    run_count: int = 0
    success_count: int = 0
    failure_count: int = 0

    def __post_init__(self):
        self.semaphore = asyncio.Semaphore(self.max_concurrent_runs)

    @property
    def current_active_runs(self) -> int:
        return self.max_concurrent_runs - self.semaphore._value


class TaskRegistry:
    def __init__(self):
        self._tasks: Dict[str, Task] = {}
        self._running_task_keys: Set[str] = set()
        self._background_tasks: Set[asyncio.Task] = set()
        self._client_manager: Optional['ClientManager'] = None
        self._db: Optional['AsyncDatabase'] = None
        self._state: Optional['AppState'] = None
        self._config: Optional['ConfigManager'] = None
        self.app_context: Optional['AppContext'] = None  # <-- YANGI QATOR

        logger.info("TaskRegistry (Modernized) ishga tushirildi.")


    def get_running_tasks(self) -> Set[str]:
        return self._running_task_keys

    def get_task_status(self, key: str) -> Optional[Dict[str, Any]]:
        task = self._tasks.get(key)
        if task:
            return {
                "key": task.key,
                "description": task.description,
                "status": task.status,
                "is_running": task.key in self._running_task_keys,
                "max_concurrent_runs": task.max_concurrent_runs,
                "active_runs": task.current_active_runs,
                "last_run_time": task.last_run_time,
                "last_run_duration": task.last_run_duration,
                "last_error": task.last_error,
                "run_count": task.run_count,
                "success_count": task.success_count,
                "failure_count": task.failure_count,
            }
        return None

    def get_all_task_statuses(self) -> List[Dict[str, Any]]:
        return [status for key in self._tasks.keys() if (status := self.get_task_status(key)) is not None]

    def set_app_context(self, context: 'AppContext'):  # <-- YANGI METOD
        """TaskRegistry uchun to'liq AppContext'ni o'rnatadi."""
        self.app_context = context
        logger.debug("TaskRegistry AppContext bilan sozlandi.")
        
    def set_client_manager(self, client_manager: 'ClientManager'):
        self._client_manager = client_manager
        logger.debug("TaskRegistry ClientManager bilan sozlandi.")

    def set_db_instance(self, db_instance: 'AsyncDatabase'):
        self._db = db_instance
        logger.debug("TaskRegistry Database instance bilan sozlandi.")

    def set_state_instance(self, state_instance: 'AppState'):
        self._state = state_instance
        logger.debug("TaskRegistry AppState instance bilan sozlandi.")

    def set_config_instance(self, config_instance: 'ConfigManager'):
        self._config = config_instance
        logger.debug("TaskRegistry ConfigManager instance bilan sozlandi.")

    def register(
        self,
        key: Optional[str] = None,
        *,
        description: str = "Tavsif berilmagan",
        timeout: Optional[int] = None,
        retries: int = 0,
        retry_delay: int = 5,
        retry_backoff_factor: float = 2.0,
        singleton: bool = False,
        max_concurrent_runs: int = 1,
        on_failure: Optional[Callable[[FailureContext], Coroutine[Any, Any, None]]] = None,
    ) -> Callable[[Callable[..., Any]], Callable[..., Any]]:
        if singleton:
            if max_concurrent_runs > 1:
                logger.warning(f"Singleton vazifa '{key or 'noma`lum'}' uchun max_concurrent_runs {max_concurrent_runs} sifatida berildi, lekin u 1 ga o'rnatiladi.")
            max_concurrent_runs = 1

        def decorator(func: Callable[..., Any]) -> Callable[..., Any]:
            if not inspect.iscoroutinefunction(func):
                raise TypeError("Vazifa asinxron (`async def`) bo'lishi kerak.")

            task_key = key or f"{func.__module__}.{func.__name__}"

            if task_key in self._tasks:
                logger.warning(f"Vazifa kaliti '{task_key}' qayta ro'yxatdan o'tkazilmoqda.")

            task_obj = Task(
                key=task_key,
                func=func,
                description=description,
                timeout=timeout,
                retries=retries,
                retry_delay=retry_delay,
                retry_backoff_factor=retry_backoff_factor,
                on_failure=on_failure,
                max_concurrent_runs=max_concurrent_runs,
            )
            self._tasks[task_key] = task_obj
            logger.trace(f"Vazifa '{task_key}' ro'yxatdan o'tkazildi.")
            return func

        return decorator

    def add_task(self, task: Task):
        if not isinstance(task, Task):
            raise TypeError("add_task metodi faqat Task obyekti qabul qiladi.")
        if task.key in self._tasks:
            logger.warning(f"Vazifa '{task.key}' allaqachon ro'yxatdan o'tgan. Qayta yozilmoqda.")
        self._tasks[task.key] = task
        logger.info(f"Vazifa '{task.key}' dinamik ravishda qo'shildi.")

    def remove_task(self, key: str):
        if key in self._tasks:
            del self._tasks[key]
            logger.info(f"Vazifa '{key}' ro'yxatdan o'chirildi.")
            return True
        logger.warning(f"Vazifa '{key}' topilmadi, o'chirilmadi.")
        return False

    def get_task(self, key: str) -> Optional[Task]:
        return self._tasks.get(key)

    def list_tasks(self) -> List[Task]:
        return list(self._tasks.values())

    def clear(self):
        # Fondagi barcha vazifalarni bekor qilish
        for task in self._background_tasks:
            if not task.done():
                task.cancel()
        self._background_tasks.clear()

        self._tasks.clear()
        self._running_task_keys.clear()
        logger.debug("TaskRegistry to'liq tozalandi, fon vazifalari bekor qilindi.")

    async def _execute_task_with_retries(self, task: Task, actual_kwargs: Dict[str, Any]) -> None:
        start_time = time.monotonic()
        start_time_utc = time.time() # Log uchun UTC vaqt
        last_exception: Optional[Exception] = None
        last_traceback_str: Optional[str] = None
        current_delay = task.retry_delay

        task.run_count += 1
        task.status = "running"
        final_attempt_num = 0

        for attempt in range(task.retries + 1):
            final_attempt_num = attempt + 1
            try:
                # `asyncio.timeout(None)` `async with` bilan ishlamaydi, shuning uchun shart qo'yamiz
                if task.timeout:
                    async with asyncio.timeout(task.timeout):
                        await task.func(**actual_kwargs)
                else:
                    await task.func(**actual_kwargs)

                duration = (time.monotonic() - start_time) * 1000
                logger.success(f"Vazifa '{task.key}' muvaffaqiyatli yakunlandi ({duration:.2f} ms).")

                if self._db:
                    log_details = last_traceback_str if last_traceback_str else (str(last_exception) if last_exception else None)
                    # YECHIM: run_at parametrini qo'shamiz
                    await self._db.log_task_execution(task.key, duration, "SUCCESS", log_details, run_at=start_time_utc)
                task.status = "success"
                task.last_run_time = time.time()
                task.last_run_duration = duration
                task.last_error = None
                task.success_count += 1
                return

            except asyncio.TimeoutError as e:
                last_exception = e
                last_traceback_str = traceback.format_exc()
                logger.error(f"Vazifa '{task.key}' belgilangan {task.timeout} soniyada yakunlanmadi. (Urinish {final_attempt_num}/{task.retries + 1})")
                break

            except Exception as e:
                last_exception = e
                last_traceback_str = traceback.format_exc()
                logger.warning(f"Vazifa '{task.key}' (urinish {final_attempt_num}/{task.retries + 1}) xatolik bilan yakunlandi: {e!r}")
                if attempt < task.retries:
                    jitter = random.uniform(-current_delay * 0.1, current_delay * 0.1)
                    wait_time = current_delay + jitter
                    logger.info(f"{wait_time:.2f} soniyadan so'ng qayta urinish...")
                    await asyncio.sleep(wait_time)
                    current_delay *= task.retry_backoff_factor
                else:
                    logger.error(f"Vazifa '{task.key}' barcha urinishlardan so'ng ham muvaffaqiyatsiz yakunlandi: {e!r}")

        duration = (time.monotonic() - start_time) * 1000
        task.status = "failed"
        task.last_run_time = time.time()
        task.last_run_duration = duration
        task.last_error = last_exception
        task.failure_count += 1

        log_status = "TIMEOUT" if isinstance(last_exception, asyncio.TimeoutError) else "FAILURE"
        log_details = last_traceback_str or str(last_exception)

        if self._db:
             # YECHIM: run_at parametrini qo'shamiz
            await self._db.log_task_execution(task.key, duration, log_status, log_details, run_at=start_time_utc)

        if task.on_failure and last_exception:
            try:
                fail_context = FailureContext(
                    task=task,
                    exception=last_exception,
                    traceback_str=last_traceback_str,
                    attempt=final_attempt_num,
                    kwargs=actual_kwargs,
                )
                await task.on_failure(fail_context)
            except Exception as cb_exc:
                logger.error(f"Vazifa '{task.key}' uchun 'on_failure' callback'ini bajarishda xato: {cb_exc!r}", exc_info=True)


    async def _prepare_and_run(self, task: Task, kwargs: Dict[str, Any]):
        if task.max_concurrent_runs == 1 and task.key in self._running_task_keys:
            logger.warning(f"Vazifa '{task.key}' o'tkazib yuborildi, chunki uning yagona nusxasi ishlamoqda.")
            task.status = "skipped"

            task.status = "skipped"
            if self._db:
                await self._db.log_task_execution(task.key, 0, "SKIPPED", "Singleton vazifa allaqachon ishlamoqda.")
            return


        self._running_task_keys.add(task.key)
        try:
            async with task.semaphore:
                await self._execute_task_with_retries(task, kwargs)
        finally:
            self._running_task_keys.discard(task.key)
            
    async def _prepare_dependencies(self, task: Task, kwargs: Dict[str, Any]) -> bool:
        """
        Vazifa funksiyasi talab qiladigan bog'liqliklarni (context, client, db, va hokazo) kwargs ga qo'shadi.
        """
        func_params = inspect.signature(task.func).parameters

        if 'context' in func_params:
            if self.app_context is None:
                logger.error(f"TaskRegistry uchun AppContext o'rnatilmagan. Vazifa '{task.key}' to'xtatildi.")
                return False
            kwargs['context'] = self.app_context

        if 'client' in func_params:
            if 'account_id' not in kwargs:
                logger.error(f"Vazifa '{task.key}' uchun 'account_id' topilmadi. Vazifa to'xtatildi.")
                return False
            if self._client_manager is None:
                logger.error("TaskRegistry uchun ClientManager o'rnatilmagan. Vazifa to'xtatildi.")
                return False

            client = self._client_manager.get_client(kwargs['account_id'])
            if not client or not client.is_connected():
                logger.warning(f"Vazifa '{task.key}' uchun klient (ID: {kwargs['account_id']}) topilmadi yoki ulanmagan.")
                return False
            
            # YECHIM: account_id ni faqat funksiya **kwargs qabul qilmasa va
            # 'account_id' nomli argumenti bo'lmasa o'chiramiz.
            has_var_keyword = any(p.kind == p.VAR_KEYWORD for p in func_params.values())
            if 'account_id' in kwargs and 'account_id' not in func_params and not has_var_keyword:
                kwargs.pop('account_id')

            kwargs['client'] = client
        
        # ... (qolgan qismi o'zgarishsiz) ...
        if 'db' in func_params:
            if self._db is None: return False
            kwargs['db'] = self._db
        if 'state' in func_params:
            if self._state is None: return False
            kwargs['state'] = self._state
        if 'config' in func_params:
            if self._config is None: return False
            kwargs['config'] = self._config

        return True



    def get_task_runner(self, key: str, job_kwargs: Optional[Dict[str, Any]] = None) -> Optional[Callable[[], Coroutine[Any, Any, None]]]:
            task = self.get_task(key)
            if not task:
                logger.error(f"Scheduler uchun vazifa topilmadi: '{key}'")
                return None

            actual_kwargs = job_kwargs or {}
            # QO'SHIMCHA LOG 3: Runner yaratilayotgandagi argumentlarni tekshirish
            logger.debug(f"[TASK_RUNNER_CREATE] '{key}' uchun runner yaratilmoqda. actual_kwargs: {actual_kwargs}")

            async def runner():
                # QO'SHIMCHA LOG 4: Runner ishga tushgandagi argumentlarni tekshirish
                logger.debug(f"[TASK_RUNNER_EXEC] '{task.key}' runneri ishga tushdi. actual_kwargs: {actual_kwargs}")
                
                if await self._prepare_dependencies(task, actual_kwargs):
                    await self._prepare_and_run(task, actual_kwargs)

            return runner
        
    
    async def run_task_manually(self, key: str, **kwargs) -> bool:
        task = self.get_task(key)
        if not task:
            logger.error(f"Qo'lda ishga tushirish uchun vazifa topilmadi: '{key}'")
            return False
        
        if task.max_concurrent_runs == 1 and task.key in self._running_task_keys:
            logger.warning(f"Vazifa '{key}' ishga tushirilmadi, chunki uning yagona nusxasi allaqachon ishlamoqda.")
            task.status = "skipped"
            if self._db:
                asyncio.create_task(self._db.log_task_execution(key, 0, "SKIPPED", "Singleton vazifa allaqachon ishlamoqda."))
            return False

        logger.info(f"Vazifa '{task.key}' qo'lda ishga tushirilmoqda...")
        if await self._prepare_dependencies(task, kwargs):
            # Vazifani yaratib, uni kuzatuv ostidagi ro'yxatga qo'shamiz
            bg_task = asyncio.create_task(self._prepare_and_run(task, kwargs))
            
            # Vazifa tugagach, avtomatik ravishda ro'yxatdan o'chirilishi uchun callback qo'shamiz
            self._background_tasks.add(bg_task)
            bg_task.add_done_callback(self._background_tasks.discard)
            
            return True
        return False



async def cleanup_old_database_entries(db: "AsyncDatabase", config: "ConfigManager"):
    cleanup_days = config.get("DB_CLEANUP_DAYS", 7)
    logger.info(f"🧹 Ma'lumotlar bazasini tozalash vazifasi ishga tushdi. {cleanup_days} kundan eski yozuvlar o'chiriladi...")

    try:
        async with db.transaction():

            tables_to_clean = db.get_cleanup_configurations()

            total_deleted_count = 0
            for table_name, date_column in tables_to_clean.items():
                deleted_count = await db.execute(
                    f"DELETE FROM {table_name} WHERE {date_column} < date('now', '-{cleanup_days} days')",
                )
                if deleted_count > 0:
                    logger.info(f"🧹 '{table_name}' jadvalidan {deleted_count} ta eski yozuv o'chirildi.")
                    total_deleted_count += deleted_count

        logger.success(f"✅ Ma'lumotlar bazasini tozalash vazifasi muvaffaqiyatli yakunlandi. Jami {total_deleted_count} ta yozuv o'chirildi.")
    except Exception as e:
        logger.exception(f"💥 Ma'lumotlar bazasini tozalash vaqtida xatolik yuz berdi: {e}")


async def vacuum_database(db: "AsyncDatabase"):
    logger.info("⚙️ Ma'lumotlar bazasida VACUUM operatsiyasi boshlandi...")
    try:
        await db.vacuum()
        logger.success("✅ Ma'lumotlar bazasi muvaffaqiyatli VACUUM qilindi.")
    except Exception as e:
        logger.exception(f"💥 Ma'lumotlar bazasini VACUUM qilishda xatolik yuz berdi: {e}")


def register_core_tasks(registry: TaskRegistry):
    """
    Asosiy tizim vazifalarini markazlashgan holda ro'yxatdan o'tkazadi.
    Bu funksiya main.py da TaskRegistry yaratilgandan so'ng chaqiriladi.
    """
    if not isinstance(registry, TaskRegistry):
        raise TypeError("registry parametri TaskRegistry nusxasi bo'lishi kerak.")

    registry.register(
        key="system.cleanup_db",
        description="Ma'lumotlar bazasidan eski yozuvlarni vaqti-vaqti bilan tozalaydi.",
        singleton=True,
        retries=2,
        retry_delay=60
    )(cleanup_old_database_entries)

    registry.register(
        key="system.vacuum_db",
        description="Ma'lumotlar bazasida vaqti-vaqti bilan VACUUM operatsiyasini bajaradi.",
        singleton=True,
        retries=1,
        retry_delay=300,
        timeout=1800
    )(vacuum_database)
    
    logger.info("Core tizim vazifalari (cleanup, vacuum) muvaffaqiyatli ro'yxatdan o'tkazildi.")