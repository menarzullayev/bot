import pytest
import asyncio
from typing import AsyncGenerator
from unittest.mock import MagicMock, AsyncMock

import pytest_asyncio
from apscheduler.triggers.cron import CronTrigger
from apscheduler.schedulers.base import STATE_STOPPED, STATE_RUNNING

# Test qilinadigan klasslar va obyektlar
from core.scheduler import SchedulerManager
from core.database import AsyncDatabase
from core.tasks import TaskRegistry
from core.exceptions import QueryError

pytestmark = pytest.mark.asyncio

# --- Fixtures (Test uchun tayyorgarlik) ---


@pytest.fixture
def mock_db() -> AsyncMock:
    """Soxta (mock) AsyncDatabase obyektini yaratadi."""
    db = AsyncMock(spec=AsyncDatabase)
    db.fetchall.return_value = []
    db.execute.return_value = 1
    return db


@pytest.fixture
def mock_task_registry(monkeypatch) -> MagicMock:
    """Global `tasks` obyektini soxtalashtiradi."""
    mock_registry = MagicMock(spec=TaskRegistry)
    mock_registry.get_task_runner.return_value = AsyncMock()
    monkeypatch.setattr("core.scheduler.tasks", mock_registry)
    return mock_registry


@pytest_asyncio.fixture
async def scheduler(mock_db: AsyncMock, mock_task_registry: MagicMock) -> AsyncGenerator[SchedulerManager, None]:
    """Har bir test uchun yangi SchedulerManager obyektini yaratadi."""
    manager = SchedulerManager(database=mock_db)
    yield manager
    if manager.scheduler.running:
        manager.scheduler.shutdown(wait=False)


# --- Test Klasslari ---


class TestSchedulerManager:
    """SchedulerManager klassining funksionalligini test qilish."""

    async def test_initialization_and_start(self, scheduler: SchedulerManager):
        """1. SchedulerManager to'g'ri yaratilishi va ishga tushishini tekshirish."""
        assert not scheduler.scheduler.running
        scheduler.start()
        await asyncio.sleep(0.01)  # Event loopga ishlash uchun vaqt beramiz
        assert scheduler.scheduler.running is True
        assert len(scheduler.scheduler._listeners) > 0

    async def test_shutdown(self, scheduler: SchedulerManager):
        """2. Rejalashtiruvchini to'xtatish."""
        scheduler.start()
        await asyncio.sleep(0.01)
        assert scheduler.scheduler.running is True

        scheduler.shutdown()
        # XATOLIK TUZATILDI: shutdown sinxron bo'lsa ham, holat o'zgarishi uchun kutamiz
        await asyncio.sleep(0.01)
        assert scheduler.scheduler.state == STATE_STOPPED

    async def test_add_job_success(self, scheduler: SchedulerManager, mock_db: AsyncMock):
        """3. Yangi vazifani muvaffaqiyatli qo'shish."""
        scheduler.start()
        job_id = await scheduler.add_job("test.task", 123, "cron", {"hour": 5})
        assert job_id is not None
        assert scheduler.get_job(job_id) is not None
        mock_db.execute.assert_called_once()

    async def test_add_job_fails_if_task_not_found(self, scheduler: SchedulerManager, mock_task_registry: MagicMock):
        """4. Mavjud bo'lmagan vazifani qo'shishda xatolik."""
        mock_task_registry.get_task_runner.return_value = None
        job_id = await scheduler.add_job("nonexistent.task", 123, "cron", {})
        assert job_id is None

    async def test_create_trigger_logic(self, scheduler: SchedulerManager):
        """5. Turli trigger turlarini yaratishni tekshirish."""
        cron = scheduler._create_trigger("cron", {"minute": "*/10"})
        assert isinstance(cron, CronTrigger)
        with pytest.raises(QueryError):
            scheduler._create_trigger("unknown", {})

    async def test_remove_job(self, scheduler: SchedulerManager, mock_db: AsyncMock):
        """6. Mavjud vazifani o'chirish."""
        scheduler.start()
        job_id = "job_to_remove"
        scheduler.scheduler.add_job(AsyncMock(), "interval", id=job_id)

        result = await scheduler.remove_job(job_id)
        assert result is True
        mock_db.execute.assert_called_with("DELETE FROM scheduled_jobs WHERE job_id = ?", (job_id,))

    async def test_toggle_job_to_pause(self, scheduler: SchedulerManager, mock_db: AsyncMock):
        """7. Aktiv vazifani pauza qilish."""
        scheduler.start()
        job_id = "job_to_pause"
        job = scheduler.scheduler.add_job(AsyncMock(), "interval", id=job_id)

        await scheduler.toggle_job_pause(job_id)
        assert job.next_run_time is None

    async def test_toggle_job_to_resume(self, scheduler: SchedulerManager, mock_db: AsyncMock):
        """8. Pauzadagi vazifani aktivlashtirish."""
        scheduler.start()
        job_id = "job_to_resume"
        scheduler.scheduler.add_job(AsyncMock(), "interval", id=job_id, next_run_time=None)

        await scheduler.toggle_job_pause(job_id)
        job = scheduler.get_job(job_id)
        assert job is not None
        assert job.next_run_time is not None

    async def test_load_jobs_from_db(self, scheduler: SchedulerManager, mock_db: AsyncMock):
        """9. Ma'lumotlar bazasidan vazifalarni yuklash."""
        mock_db.fetchall.return_value = [{"job_id": "db_job_1", "task_key": "task.db", "trigger_type": "cron", "trigger_args": '{"hour": 8}', "job_kwargs": '{}', "status": "active"}]

        await scheduler.load_jobs_from_db()
        assert scheduler.get_job("db_job_1") is not None

    async def test_run_job_now(self, scheduler: SchedulerManager, mock_db: AsyncMock):
        """10. Rejalashtirilgan vazifani darhol ishga tushirish."""
        scheduler.start()
        job_id = "my_job"
        mock_db.fetchone.return_value = {"job_id": job_id, "task_key": "some.task", "job_kwargs": '{}'}

        assert await scheduler.run_job_now(job_id) is True
        assert any(j.id.startswith(f"run_now_{job_id}") for j in scheduler.get_jobs())
