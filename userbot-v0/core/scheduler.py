import json
import uuid
from datetime import datetime
from typing import Optional, List, Dict, Any, TYPE_CHECKING

from apscheduler.events import JobExecutionEvent, EVENT_JOB_EXECUTED, EVENT_JOB_ERROR
from loguru import logger
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.interval import IntervalTrigger
from apscheduler.triggers.date import DateTrigger
from apscheduler.job import Job


from core.exceptions import QueryError

if TYPE_CHECKING:
    from core.database import AsyncDatabase
    from core.app_context import AppContext


class SchedulerManager:
    def __init__(self, database: 'AsyncDatabase'):
        self._db = database
        self.app_context: Optional["AppContext"] = None
        self.scheduler = AsyncIOScheduler(timezone="Asia/Tashkent")
        self.scheduler.add_listener(self._job_listener, EVENT_JOB_EXECUTED | EVENT_JOB_ERROR)
        logger.info("SchedulerManager (Modernized) ishga tayyor.")

    def set_app_context(self, context: "AppContext"):
        """Schedulerga asosiy ilova kontekstini o'rnatadi."""
        self.app_context = context

    def _job_listener(self, event: JobExecutionEvent):
        """
        APScheduler hodisalarini tinglaydigan va loglaydigan funksiya.
        """
        if event.exception:
            logger.error(f"Job '{event.job_id}' (vazifa: {event.job_id}) xatolik bilan yakunlandi: {event.exception!r}", exc_info=True)
        else:
            logger.info(f"Job '{event.job_id}' (vazifa: {event.job_id}) muvaffaqiyatli bajarildi.")

    async def schedule_system_tasks(self):
        if not self.app_context:
            return
        task_key_cleanup = "system.cleanup_db"
        job_id_cleanup = "system_daily_cleanup"

        if not self.scheduler.get_job(job_id_cleanup):

            if runner := self.app_context.tasks.get_task_runner(key=task_key_cleanup):

                try:
                    self.scheduler.add_job(runner, trigger=CronTrigger(hour=3, minute=5, timezone="Asia/Tashkent"), id=job_id_cleanup, replace_existing=True)
                    logger.info(f"✅ Tizim vazifasi '{task_key_cleanup}' har kuni 03:05 da ishlashga rejalashtirildi.")
                except Exception:
                    logger.exception(f"Tizim vazifasi '{task_key_cleanup}'ni rejalashtirib bo'lmadi.")
            else:
                logger.error(f"Rejalashtirish uchun '{task_key_cleanup}' kalitli tizim vazifasi topilmadi. Vazifa ro'yxatdan o'tganligini tekshiring.")
        else:
            logger.info(f"Tizim vazifasi '{job_id_cleanup}' allaqachon rejalashtirilgan.")

        task_key_vacuum = "system.vacuum_db"
        job_id_vacuum = "system_weekly_vacuum"

        if not self.scheduler.get_job(job_id_vacuum):
            if runner := self.app_context.tasks.get_task_runner(key=task_key_vacuum):
                try:

                    self.scheduler.add_job(runner, trigger=CronTrigger(day_of_week='sun', hour=2, minute=0, timezone="Asia/Tashkent"), id=job_id_vacuum, replace_existing=True)
                    logger.info(f"✅ Tizim vazifasi '{task_key_vacuum}' har yakshanba 02:00 da ishlashga rejalashtirildi.")
                except Exception:
                    logger.exception(f"Tizim vazifasi '{task_key_vacuum}'ni rejalashtirib bo'lmadi.")
            else:
                logger.error(f"Rejalashtirish uchun '{task_key_vacuum}' kalitli tizim vazifasi topilmadi. Vazifa ro'yxatdan o'tganligini tekshiring.")
        else:
            logger.info(f"Tizim vazifasi '{job_id_vacuum}' allaqachon rejalashtirilgan.")

    def _create_trigger(self, trigger_type: str, trigger_args: Dict[str, Any]):
        """
        Trigger ob'ektini yaratadi. Noma'lum trigger turi yoki xato yuz bersa, QueryError tashlaydi.
        """
        try:
            if trigger_type == 'cron':
                return CronTrigger(**trigger_args)
            elif trigger_type == 'interval':
                return IntervalTrigger(**trigger_args)
            elif trigger_type == 'date':

                if 'run_date' in trigger_args and isinstance(trigger_args['run_date'], str):
                    trigger_args['run_date'] = datetime.fromisoformat(trigger_args['run_date'])
                return DateTrigger(**trigger_args)
            else:
                raise QueryError(f"Noma'lum trigger turi: '{trigger_type}'")
        except Exception as e:
            logger.exception(f"'{trigger_type}' triggerini yaratib bo'lmadi. Argumentlar: {trigger_args}")
            raise QueryError(f"Trigger yaratishda xato: {e}") from e

    def start(self):
        """
        Rejalashtiruvchini ishga tushiradi.
        """
        try:
            if not self.scheduler.running:
                self.scheduler.start()
                logger.info("🕒 Rejalashtiruvchi (scheduler) ishga tushirildi.")
            else:
                logger.info("Rejalashtiruvchi allaqachon ishlamoqda.")
        except Exception:
            logger.critical("Rejalashtiruvchini ishga tushirishda xatolik", exc_info=True)

    def shutdown(self):
        """
        Rejalashtiruvchini to'xtatadi.
        """
        if self.scheduler.running:
            self.scheduler.shutdown()
            logger.info("🕒 Rejalashtiruvchi to'xtatildi.")
        else:
            logger.info("Rejalashtiruvchi allaqachon to'xtatilgan.")
            
    async def load_jobs_from_db(self):
        """
        Ma'lumotlar bazasidan rejalashtirilgan vazifalarni yuklaydi.
        """
        logger.info("Ma'lumotlar bazasidan rejalashtirilgan vazifalar yuklanmoqda...")
        if not self.app_context or not self.app_context.tasks:
            logger.error("Scheduler.load_jobs_from_db: AppContext yoki TaskRegistry topilmadi.")
            return

        await self._db.execute(
            """
            CREATE TABLE IF NOT EXISTS scheduled_jobs (
                job_id TEXT PRIMARY KEY UNIQUE NOT NULL,
                account_id INTEGER,
                task_key TEXT NOT NULL,
                trigger_type TEXT NOT NULL,
                trigger_args TEXT NOT NULL,
                job_kwargs TEXT NOT NULL,
                status TEXT NOT NULL DEFAULT 'active',
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                last_run TIMESTAMP
            );
        """
        )

        jobs_from_db = await self._db.fetchall("SELECT * FROM scheduled_jobs")
        loaded_count = 0
        for job_data in jobs_from_db:
            try:
                # QO'SHIMCHA LOG 1: Bazadan olingan xom ma'lumotni ko'ramiz
                logger.debug(f"[SCHED_LOAD] DB'dan o'qilgan job_data: {job_data}")
                
                task_key = job_data['task_key']
                job_kwargs = json.loads(job_data['job_kwargs'] or '{}')
                
                if job_data.get('account_id'):
                    job_kwargs['account_id'] = job_data['account_id']

                # QO'SHIMCHA LOG 2: TaskRegistry'ga yuborishdan oldingi holatini tekshiramiz
                logger.debug(f"[SCHED_LOAD] get_task_runner uchun tayyorlangan job_kwargs: {job_kwargs}")

                runner = self.app_context.tasks.get_task_runner(key=task_key, job_kwargs=job_kwargs)
                if not runner:
                    logger.error(f"Vazifa kaliti '{task_key}' uchun funksiya topilmadi. '{job_data['job_id']}' o'tkazib yuborildi.")
                    continue

                trigger_args = json.loads(job_data['trigger_args'])
                trigger = self._create_trigger(job_data['trigger_type'], trigger_args)
                self.scheduler.add_job(runner, trigger, id=job_data['job_id'], replace_existing=True)

                if job_data['status'] == 'paused':
                    self.scheduler.pause_job(job_data['job_id'])
                loaded_count += 1
            except QueryError:
                logger.error(f"'{job_data['job_id']}' vazifasi uchun trigger yaratishda xatolik. Vazifa yuklanmadi.", exc_info=True)
            except Exception:
                logger.error(f"'{job_data['job_id']}' vazifasini DBdan yuklashda kutilmagan xatolik", exc_info=True)

        if loaded_count > 0:
            logger.success(f"{loaded_count} ta vazifa ma'lumotlar bazasidan muvaffaqiyatli tiklandi.")
        else:
            logger.info("Ma'lumotlar bazasida rejalashtirilgan vazifalar topilmadi.")

        """
        Ma'lumotlar bazasidan rejalashtirilgan vazifalarni yuklaydi.
        """
        logger.info("Ma'lumotlar bazasidan rejalashtirilgan vazifalar yuklanmoqda...")
        if not self.app_context or not self.app_context.tasks:
            logger.error("Scheduler.load_jobs_from_db: AppContext yoki TaskRegistry topilmadi.")
            return

        await self._db.execute(
            """
            CREATE TABLE IF NOT EXISTS scheduled_jobs (
                job_id TEXT PRIMARY KEY UNIQUE NOT NULL,
                account_id INTEGER,
                task_key TEXT NOT NULL,
                trigger_type TEXT NOT NULL,
                trigger_args TEXT NOT NULL,
                job_kwargs TEXT NOT NULL,
                status TEXT NOT NULL DEFAULT 'active',
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                last_run TIMESTAMP
            );
        """
        )

        jobs_from_db = await self._db.fetchall("SELECT * FROM scheduled_jobs")
        loaded_count = 0
        for job_data in jobs_from_db:
            try:
                task_key = job_data['task_key']
                job_kwargs = json.loads(job_data['job_kwargs'] or '{}')
                
                # YECHIM: Bazadan olingan account_id ni kwargs ga qo'shamiz
                if job_data.get('account_id'):
                    job_kwargs['account_id'] = job_data['account_id']

                runner = self.app_context.tasks.get_task_runner(key=task_key, job_kwargs=job_kwargs)
                if not runner:
                    logger.error(f"Vazifa kaliti '{task_key}' uchun funksiya topilmadi. '{job_data['job_id']}' o'tkazib yuborildi.")
                    continue

                trigger_args = json.loads(job_data['trigger_args'])
                trigger = self._create_trigger(job_data['trigger_type'], trigger_args)

                self.scheduler.add_job(runner, trigger, id=job_data['job_id'], replace_existing=True)

                if job_data['status'] == 'paused':
                    self.scheduler.pause_job(job_data['job_id'])
                loaded_count += 1
            except QueryError:
                logger.error(f"'{job_data['job_id']}' vazifasi uchun trigger yaratishda xatolik. Vazifa yuklanmadi.", exc_info=True)
            except Exception:
                logger.error(f"'{job_data['job_id']}' vazifasini DBdan yuklashda kutilmagan xatolik", exc_info=True)

        if loaded_count > 0:
            logger.success(f"{loaded_count} ta vazifa ma'lumotlar bazasidan muvaffaqiyatli tiklandi.")
        else:
            logger.info("Ma'lumotlar bazasida rejalashtirilgan vazifalar topilmadi.")

        """
        Ma'lumotlar bazasidan rejalashtirilgan vazifalarni yuklaydi.
        """
        logger.info("Ma'lumotlar bazasidan rejalashtirilgan vazifalar yuklanmoqda...")
        if not self.app_context or not self.app_context.tasks:
            logger.error("Scheduler.load_jobs_from_db: AppContext yoki TaskRegistry topilmadi.")
            return

        # ... (jadval yaratish kodi o'zgarishsiz) ...
        await self._db.execute(
            """
            CREATE TABLE IF NOT EXISTS scheduled_jobs (
                job_id TEXT PRIMARY KEY UNIQUE NOT NULL,
                account_id INTEGER,
                task_key TEXT NOT NULL,
                trigger_type TEXT NOT NULL,
                trigger_args TEXT NOT NULL,
                job_kwargs TEXT NOT NULL,
                status TEXT NOT NULL DEFAULT 'active',
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                last_run TIMESTAMP
            );
        """
        )

        jobs_from_db = await self._db.fetchall("SELECT * FROM scheduled_jobs")
        loaded_count = 0
        for job_data in jobs_from_db:
            try:
                task_key = job_data['task_key']
                job_kwargs = json.loads(job_data['job_kwargs'] or '{}')
                
                # YECHIM: Bazadan olingan account_id ni kwargs ga qo'shamiz
                if job_data.get('account_id'):
                    job_kwargs['account_id'] = job_data['account_id']

                runner = self.app_context.tasks.get_task_runner(key=task_key, job_kwargs=job_kwargs)
                if not runner:
                    logger.error(f"Vazifa kaliti '{task_key}' uchun funksiya topilmadi. '{job_data['job_id']}' o'tkazib yuborildi.")
                    continue

                trigger_args = json.loads(job_data['trigger_args'])
                trigger = self._create_trigger(job_data['trigger_type'], trigger_args)

                self.scheduler.add_job(runner, trigger, id=job_data['job_id'], replace_existing=True)

                if job_data['status'] == 'paused':
                    self.scheduler.pause_job(job_data['job_id'])
                loaded_count += 1
            except QueryError:
                logger.error(f"'{job_data['job_id']}' vazifasi uchun trigger yaratishda xatolik. Vazifa yuklanmadi.", exc_info=True)
            except Exception:
                logger.error(f"'{job_data['job_id']}' vazifasini DBdan yuklashda kutilmagan xatolik", exc_info=True)

        if loaded_count > 0:
            logger.success(f"{loaded_count} ta vazifa ma'lumotlar bazasidan muvaffaqiyatli tiklandi.")
        else:
            logger.info("Ma'lumotlar bazasida rejalashtirilgan vazifalar topilmadi.")

        """
        Ma'lumotlar bazasidan rejalashtirilgan vazifalarni yuklaydi.
        """
        logger.info("Ma'lumotlar bazasidan rejalashtirilgan vazifalar yuklanmoqda...")
        if not self.app_context or not self.app_context.tasks:
            logger.error("Scheduler.load_jobs_from_db: AppContext yoki TaskRegistry topilmadi.")
            return

        # ... (jadval yaratish kodi o'zgarishsiz qoladi) ...
        await self._db.execute(
            """
            CREATE TABLE IF NOT EXISTS scheduled_jobs (
                job_id TEXT PRIMARY KEY UNIQUE NOT NULL,
                account_id INTEGER,
                task_key TEXT NOT NULL,
                trigger_type TEXT NOT NULL,
                trigger_args TEXT NOT NULL,
                job_kwargs TEXT NOT NULL,
                status TEXT NOT NULL DEFAULT 'active',
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                last_run TIMESTAMP
            );
        """
        )

        jobs_from_db = await self._db.fetchall("SELECT * FROM scheduled_jobs")
        loaded_count = 0
        for job_data in jobs_from_db:
            try:
                task_key = job_data['task_key']
                job_kwargs = json.loads(job_data['job_kwargs'] or '{}')
                
                # YECHIM: Bazadan olingan account_id ni kwargs ga qo'shamiz
                if job_data.get('account_id'):
                    job_kwargs['account_id'] = job_data['account_id']

                runner = self.app_context.tasks.get_task_runner(key=task_key, job_kwargs=job_kwargs)
                if not runner:
                    logger.error(f"Vazifa kaliti '{task_key}' uchun funksiya topilmadi. '{job_data['job_id']}' o'tkazib yuborildi.")
                    continue

                trigger_args = json.loads(job_data['trigger_args'])
                trigger = self._create_trigger(job_data['trigger_type'], trigger_args)

                self.scheduler.add_job(runner, trigger, id=job_data['job_id'], replace_existing=True)

                if job_data['status'] == 'paused':
                    self.scheduler.pause_job(job_data['job_id'])
                loaded_count += 1
            except QueryError:
                logger.error(f"'{job_data['job_id']}' vazifasi uchun trigger yaratishda xatolik. Vazifa yuklanmadi.", exc_info=True)
            except Exception:
                logger.error(f"'{job_data['job_id']}' vazifasini DBdan yuklashda kutilmagan xatolik", exc_info=True)

        if loaded_count > 0:
            logger.success(f"{loaded_count} ta vazifa ma'lumotlar bazasidan muvaffaqiyatli tiklandi.")
        else:
            logger.info("Ma'lumotlar bazasida rejalashtirilgan vazifalar topilmadi.")

    
    async def add_job(self, task_key: str, account_id: int, trigger_type: str, trigger_args: Dict[str, Any], job_id: Optional[str] = None, job_kwargs: Optional[Dict[str, Any]] = None) -> Optional[str]:
        """
        Yangi vazifani rejalashtiruvchiga qo'shadi va ma'lumotlar bazasiga saqlaydi.
        """
        if not self.app_context or not self.app_context.tasks:
            logger.error("Scheduler.add_job: AppContext yoki TaskRegistry topilmadi.")
            return None
            
        job_kwargs = job_kwargs or {}
        
        # YECHIM: Vazifani bajaruvchi (runner) va bazaga saqlash uchun yagona kwargs yaratamiz
        final_kwargs = job_kwargs.copy()
        final_kwargs['account_id'] = account_id
        
        runner = self.app_context.tasks.get_task_runner(key=task_key, job_kwargs=final_kwargs)
        if not runner:
            logger.error(f"Vazifa kaliti '{task_key}' ro'yxatdan o'tmagan.")
            return None

        try:
            trigger = self._create_trigger(trigger_type, trigger_args)
        except QueryError:
            return None

        job_id = job_id or uuid.uuid4().hex

        try:
            self.scheduler.add_job(runner, trigger, id=job_id, replace_existing=True)

            # TUZATISH: Bazaga original `job_kwargs` o'rniga `account_id` qo'shilmaganini emas,
            # balki faqat asosiy ma'lumotlarni saqlaymiz. account_id alohida saqlanadi.
            await self._db.execute(
                """REPLACE INTO scheduled_jobs (job_id, account_id, task_key, trigger_type, trigger_args, job_kwargs, status)
                   VALUES (?, ?, ?, ?, ?, ?, ?)""",
                (job_id, account_id, task_key, trigger_type, json.dumps(trigger_args), json.dumps(job_kwargs), 'active'),
            )
            logger.info(f"Vazifa '{job_id}' (kalit: '{task_key}') muvaffaqiyatli rejalashtirildi.")
            return job_id
        except Exception:
            logger.exception(f"Vazifa '{job_id}' ni qo'shishda xatolik")
            return None



    async def run_job_now(self, job_id: str) -> bool:
        """
        Mavjud rejalashtirilgan vazifani darhol ishga tushiradi.
        """
        if not self.app_context or not self.app_context.tasks:
            logger.error("Scheduler.run_job_now: AppContext yoki TaskRegistry topilmadi.")
            return False

        job_data = await self._db.fetchone("SELECT * FROM scheduled_jobs WHERE job_id = ?", (job_id,))
        if not job_data:
            logger.error(f"'{job_id}' ID'li vazifa DBda topilmadi.")
            return False

        task_key = job_data['task_key']
        job_kwargs = json.loads(job_data['job_kwargs'] or '{}')
        
        # YECHIM: account_id ni job_kwargs ga qo'shib yuborish
        if job_data.get('account_id'):
            job_kwargs['account_id'] = job_data['account_id']
        
        runner = self.app_context.tasks.get_task_runner(key=task_key, job_kwargs=job_kwargs)

        if runner:
            temp_job_id = f"run_now_{job_id}_{uuid.uuid4().hex[:4]}"
            self.scheduler.add_job(runner, trigger='date', run_date=datetime.now(), id=temp_job_id, replace_existing=True)
            logger.info(f"Vazifa '{job_id}' darhol bajarish uchun navbatga qo'yildi (Temp ID: {temp_job_id}).")
            return True
        else:
            logger.error(f"Vazifa kaliti '{task_key}' uchun funksiya topilmadi.")
            return False


    async def remove_job(self, job_id: str) -> bool:
        """
        Rejalashtirilgan vazifani scheduler va ma'lumotlar bazasidan o'chiradi.
        """
        try:
            if self.scheduler.get_job(job_id):
                self.scheduler.remove_job(job_id)
                logger.debug(f"Vazifa '{job_id}' schedulerdan o'chirildi.")
        except Exception:
            logger.warning(f"Vazifa '{job_id}' schedulerda topilmadi yoki o'chirishda xatolik yuz berdi. DBdan o'chiriladi.")

        deleted_rows = await self._db.execute("DELETE FROM scheduled_jobs WHERE job_id = ?", (job_id,))
        if deleted_rows > 0:
            logger.info(f"Vazifa '{job_id}' DBdan o'chirildi.")
            return True
        logger.warning(f"Vazifa '{job_id}' DBda topilmadi, o'chirilmadi.")
        return False

    async def toggle_job_pause(self, job_id: str) -> Optional[str]:
        """
        Vazifaning pauza holatini almashtiradi (aktiv/pauza).
        """
        job = self.scheduler.get_job(job_id)
        if not job:
            logger.error(f"Vazifa '{job_id}' schedulerda topilmadi.")
            return None

        new_status: str
        if job.next_run_time is None:
            self.scheduler.resume_job(job_id)
            new_status = 'active'
        else:
            self.scheduler.pause_job(job_id)
            new_status = 'paused'

        await self._db.execute("UPDATE scheduled_jobs SET status = ? WHERE job_id = ?", (new_status, job_id))
        logger.info(f"Vazifa '{job_id}' holati o'zgartirildi: {new_status}")
        return new_status

    def get_jobs_as_dict(self) -> List[Dict[str, Any]]:
        """
        Barcha rejalashtirilgan vazifalar haqida lug'atlar ro'yxatini qaytaradi.
        """
        jobs_list = []
        for job in self.scheduler.get_jobs():
            trigger_info = str(job.trigger)
            jobs_list.append({"id": job.id, "name": job.name, "next_run": job.next_run_time.isoformat() if job.next_run_time else None, "trigger": trigger_info, "is_paused": job.next_run_time is None, "task_key": job.id})
        return jobs_list

    def get_job(self, job_id: str) -> Optional[Job]:
        """
        Berilgan ID bo'yicha schedulerdan job ob'ektini qaytaradi.
        """
        return self.scheduler.get_job(job_id)

    def get_jobs(self) -> List[Job]:
        """
        Barcha scheduler job ob'ektlarini qaytaradi.
        """
        if self.scheduler.running:
            return self.scheduler.get_jobs()
        return []

    async def pause_job(self, job_id: str) -> bool:
        """
        Vazifani pauza qiladi.
        """
        job = self.scheduler.get_job(job_id)
        if not job or job.next_run_time is None:
            logger.warning(f"Vazifa '{job_id}' pauza qilinmadi: topilmadi yoki allaqachon pauzada.")
            return False

        self.scheduler.pause_job(job_id)
        await self._db.execute("UPDATE scheduled_jobs SET status = ? WHERE job_id = ?", ('paused', job_id))
        logger.info(f"Vazifa '{job_id}' pauza qilindi.")
        return True

    async def resume_job(self, job_id: str) -> bool:
        """
        Vazifani davom ettiradi.
        """
        job = self.scheduler.get_job(job_id)
        if not job or job.next_run_time is not None:
            logger.warning(f"Vazifa '{job_id}' davom ettirilmadi: topilmadi yoki allaqachon aktiv.")
            return False

        self.scheduler.resume_job(job_id)
        await self._db.execute("UPDATE scheduled_jobs SET status = ? WHERE job_id = ?", ('active', job_id))
        logger.info(f"Vazifa '{job_id}' davom ettirildi.")
        return True
