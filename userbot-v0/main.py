import asyncio
import html
import sys
from pathlib import Path

from loguru import logger
from pydantic import ValidationError


from bot.loader import PluginManager
from core.ai_service import AIService
from core.app_context import AppContext
from core.app_core import Application
from core.cache import CacheManager
from core.client_manager import ClientManager
from core.config import StaticSettings
from core.config_manager import ConfigManager
from core.database import AsyncDatabase
from core.scheduler import SchedulerManager
from core.state import AppState
from core.tasks import TaskRegistry

async def run_application_lifecycle(static_settings: StaticSettings):
    """Ilovaning asosiy hayot siklini boshqaradi."""
    logger.debug(">>>> Dasturning hayot sikli boshlandi.")

    config = ConfigManager(static_config=static_settings)
    cache = CacheManager(config_manager=config)
    db = AsyncDatabase(config_manager=config, cache_manager=cache)
    state = AppState()
    config.set_db_instance(db)
    
    db.register_cleanup_table("afk_mentions", "mention_time")
    db.register_cleanup_table("logged_media", "timestamp")
    
    await state.load_from_disk()
    await state.set('system.lifecycle_signal', 'restart', persistent=True)

    app_instance = None
    while state.get('system.lifecycle_signal') == 'restart':
        try:
            if not db.is_connected():
                await db.connect()

            logger.info("🚀 Userbotni sozlash va ishga tushirish jarayoni boshlandi...")
            
            tasks = TaskRegistry()
            from core.tasks import register_core_tasks
            register_core_tasks(tasks)

            scheduler = SchedulerManager(database=db)
            ai_service = AIService(config_manager=config, cache_manager=cache)
            client_manager = ClientManager(database=db, config=config, state=state)
            plugin_manager = PluginManager(client_manager=client_manager, state=state, config_manager=config)

            app_context = AppContext(
                db=db, config=config, state=state, cache=cache, tasks=tasks,
                scheduler=scheduler, ai_service=ai_service,
                client_manager=client_manager, plugin_manager=plugin_manager,
            )

            plugin_manager.set_app_context(app_context)
            scheduler.set_app_context(app_context)
            state.app_context = app_context

            app_instance = Application(context=app_context)
            await app_instance.run(force_menu="--menu" in sys.argv)

        except (KeyboardInterrupt, asyncio.CancelledError):
            logger.warning("\n⌨️ Dastur foydalanuvchi tomonidan to'xtatildi.")
            await state.set('system.lifecycle_signal', 'shutdown')
        except Exception:
            logger.exception("💥 Asosiy siklda kutilmagan KRITIK xatolik!")
            await state.set('system.lifecycle_signal', 'shutdown')
        
        if state.get('system.lifecycle_signal') == 'restart':
            logger.info("--- Qayta ishga tushirish uchun resurslar tozalanmoqda... ---")
            if app_instance:
                await app_instance.cleanup_for_restart()
            await asyncio.sleep(2)
        
    # --- YAKUNIY O'CHIRISH BLOKI ---
    logger.info("🔴 Yakuniy o'chirish bosqichi boshlandi.")
    
    if app_instance: # App_instance ning mavjudligini tekshirish
        notice = app_instance.context.state.get('system.shutdown_notice')
        if notice and isinstance(notice, dict):
            logger.debug(f"Yakuniy o'chirish xabarini tahrirlash: {notice}")
            try:
                # Klientlar ro'yxatidan faol klientni topish
                if main_client := next((c for c in app_instance.context.client_manager.get_all_clients() if c.is_connected()), None):
                    original_text = notice.get('original_text', "Userbot o'chirilmoqda...")
                    new_text = f"<s>{html.escape(original_text)}</s>\n\n✅ <b>Muvaffaqiyatli o'chirildi.</b>"
                    # Sababni faqat birinchi xabarda ko'rsatish uchun bu qator o'chirildi.
                    # if reason := notice.get('reason'): 
                    #     new_text += f"\nSabab: <i>{html.escape(reason)}</i>"
                    
                    await asyncio.wait_for(

                        main_client.edit_message(
                            entity=int(notice['chat_id']), message=int(notice['message_id']),
                            text=new_text, parse_mode='html'
                        ),
                        timeout=5.0 # Xabar tahrirlanishini kutish uchun timeout
                    )
                    logger.success("Yakuniy o'chirish xabari tahrirlandi.")
                else:
                    logger.warning("Yakuniy o'chirish xabarini tahrirlash uchun aktiv klient topilmadi.")
            except Exception as e:
                logger.error(f"Yakuniy o'chirish xabarini tahrirlashda xato: {e}")
            finally:
                # Xabar tahrirlanganidan yoki xato bo'lganidan so'ng notice o'chiriladi
                await app_instance.context.state.delete('system.shutdown_notice')

        await app_instance.full_shutdown() # full_shutdown chaqiruvi shu yerda qoladi
    
    if db.is_connected():
        await db.close()

    logger.debug(">>>> Dasturning hayot sikli to'liq yakunlandi.")


async def entrypoint(static_settings: StaticSettings):
    """
    Dasturning asosiy kirish nuqtasi.
    Faqat statik sozlamalarni yuklaydi va asosiy siklni ishga tushiradi.
    """

    await run_application_lifecycle(static_settings)
    logger.success("✅ Dastur to'liq va xavfsiz yakunlandi.")


if __name__ == "__main__":

    try:

        settings = StaticSettings()

        logger.remove()
        logger.add(sys.stderr, level="INFO")

        log_file_path = settings.LOG_FILE_PATH
        log_file_path.parent.mkdir(parents=True, exist_ok=True)
        logger.add(log_file_path, level=settings.LOG_LEVEL, rotation="10 MB", compression="zip", encoding="utf-8")

        asyncio.run(entrypoint(settings))

    except (ValidationError, ValueError) as e:

        logger.critical("❗️ .env faylida yoki muhit o'zgaruvchilarida xatolik topildi!")

        if isinstance(e, ValidationError):
            for error in e.errors():
                field = ".".join(map(str, error['loc']))
                message = error['msg']
                logger.error(f"  -> Maydon: '{field}', Xato: {message}")
        else:
            logger.error(f"  -> {e}")
        logger.critical("Iltimos, .env faylini tekshirib, dasturni qayta ishga tushiring.")
        sys.exit(1)

    except (KeyboardInterrupt, asyncio.CancelledError):
        logger.warning("\n⌨️ Dastur foydalanuvchi tomonidan majburan to'xtatildi.")
    except Exception as e:
        logger.critical(f"Dasturni ishga tushirishda kutilmagan KRITIK xatolik: {type(e).__name__}: {e}", exc_info=True)
        sys.exit(1)
