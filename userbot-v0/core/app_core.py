import asyncio
from contextlib import suppress
import json
import time
import html
from pathlib import Path
from typing import Any, Optional

from loguru import logger
from pydantic import SecretStr

from core.app_context import AppContext

def load_credentials_from_file() -> list:
    """
    accounts.json faylidan akkaunt ma'lumotlarini yuklaydi.
    """
    file_path = Path("data/accounts.json")
    if not file_path.is_file() or file_path.stat().st_size == 0:
        return []
    try:
        with file_path.open('r', encoding='utf-8') as f:
            return json.load(f)
    except (json.JSONDecodeError, IOError) as e:
        logger.warning(f"accounts.json faylini o'qib bo'lmadi: {e}", exc_info=True)
        return []


async def cli_prompt(prompt_text: str) -> str:
    """
    CLI orqali foydalanuvchidan ma'lumot so'raydi.
    """
    return await asyncio.to_thread(input, prompt_text)


class Application:
    """
    Userbot ilovasining asosiy boshqaruvchi klassi.
    Barcha asosiy komponentlarni initsializatsiya qiladi va boshqaradi.
    """
    def __init__(self, context: AppContext):
        self.context = context
        self.client_manager = context.client_manager
        self.plugin_manager = context.plugin_manager
        self.config = context.config
        self.db = context.db
        self.state = context.state
        self.tasks = context.tasks
        self.scheduler = context.scheduler
        self.ai_service = context.ai_service
        self.cache = context.cache
        self.periodic_save_task: Optional[asyncio.Task] = None
        self.is_running = True

        self.tasks.set_client_manager(self.client_manager)
        self.tasks.set_db_instance(self.db)
        self.tasks.set_state_instance(self.state)
        self.tasks.set_app_context(self.context) # <-- YANGI QATOR

        logger.debug(f"[APP_INIT] 'system.restart_pending' uchun tinglovchi o'rnatilmoqda. State ID: {id(self.state)}")
       # self.state.on_change("system.restart_pending", self._handle_restart_signal)

        logger.info("🆕 Yangi 'Application' nusxasi yaratildi va komponentlar bog'landi.")

    async def _handle_restart_signal(self, key: str, value: Any):
        """'system.restart_pending' o'zgarganda klientlarni to'xtatadi, bu esa app.run() dan chiqishga olib keladi."""
        logger.debug(f"[RESTART_HANDLER_CALLED] Signal qabul qilindi. Key: '{key}', Value: '{value}', IsRunning: {self.is_running}")
        if self.is_running:
            logger.info(f"⚙️ Restart/Shutdown signali ({value}) qabul qilindi. Klientlar uzilmoqda...")
            await self.client_manager.stop_all_clients()
            logger.debug("[RESTART_HANDLER_END] client_manager.stop_all_clients() bajarildi.")
        else:
            logger.debug("[RESTART_HANDLER_SKIP] Dastur ishlamayotgani uchun handler o'tkazib yuborildi.")




    async def cleanup_for_restart(self):
        """
        Qayta ishga tushirishdan oldin resurslarni tozalaydi.
        """
        logger.info("♻️ Qayta ishga tushirish uchun resurslar tozalanmoqda...")

        if self.periodic_save_task:
            self.periodic_save_task.cancel()
            try:
                await self.periodic_save_task
            except asyncio.CancelledError:
                logger.debug("Periodik saqlash vazifasi bekor qilindi.")

        await self.client_manager.stop_all_clients()
        logger.debug("Barcha klientlar to'xtatildi.")

        logger.debug("Plugin menejeri endi avtomatik tozalanadi.")

        self.scheduler.shutdown()
        logger.debug("Scheduler to'xtatildi.")

        await self.db.close()
        logger.debug("Ma'lumotlar bazasi ulanishi yopildi.")

        await self.cache.save_to_disk()
        await self.state.save_to_disk()
        logger.debug("Kesh va holat diskka yakuniy saqlandi.")

        self.tasks.clear()
        logger.debug("Resurslar muvaffaqiyatli tozalandi.")

    async def _periodic_persistence_task(self):
        """
        Kesh va holatni muntazam ravishda diskka saqlaydigan fon vazifasi.
        """
        interval = self.config.get("PERSIST_INTERVAL_SECONDS", 3600)
        logger.info(f"💾 Kesh va holat har {interval} soniyada avtomatik saqlanadi.")
        try:
            while self.is_running:
                await asyncio.sleep(interval)
                await self.cache.save_to_disk()
                await self.state.save_to_disk()
                logger.debug("💾 Kesh va holat fon rejimida avtomatik saqlandi.")
        except asyncio.CancelledError:
            logger.info("Periodik saqlash vazifasi bekor qilindi.")
            raise
        except Exception as e:
            logger.error(f"💾 Avtomatik saqlashda kutilmagan xatolik: {e}", exc_info=True)

    async def full_shutdown(self):
        """Ilovani to'liq va xavfsiz o'chirish jarayonini boshqaradi.
        (Xabar tahrirlash bu yerda bajarilmaydi, u main.py ga ko'chirildi)."""
        logger.info("🔴 Resurslarni tozalash va o'chirish jarayoni boshlandi.")
        
        self.is_running = False
        if self.periodic_save_task:
            self.periodic_save_task.cancel()
            with suppress(asyncio.CancelledError):
                await self.periodic_save_task

        self.scheduler.shutdown()
        await self.client_manager.stop_all_clients()
        
        # Shutdown notice xabarini tahrirlash shu yerda emas, main.py ga ko'chirildi
        # main.py faylida yakuniy o'chirish xabarini tahrirlash logikasi bor.
        # Bu joydan o'chirildi, chunki klient bu bosqichda allaqachon to'xtatilgan bo'lishi mumkin.
        # if notice := await self.state.get('system.shutdown_notice'):
        #     if self.client_manager.get_all_clients():
        #         # Asosiy klientni topish va xabarni tahrirlashga urinish
        #         if main_client := next((c for c in self.client_manager.get_all_clients() if c.is_connected()), None):
        #             try:
        #                 original_text = notice.get('original_text', "Userbot o'chirilmoqda...")
        #                 reason = notice.get('reason', '')
        #                 final_text = f"<s>{html.escape(original_text)}</s>\n\n✅ <b>Muvaffaqiyatli o'chirildi.</b>"
        #                 if reason:
        #                     final_text += f"\nSabab: <i>{html.escape(reason)}</i>"
        #                 await main_client.edit_message(
        #                     entity=int(notice['chat_id']), 
        #                     message=int(notice['message_id']), 
        #                     text=final_text, 
        #                     parse_mode='HTML'
        #                 )
        #                 logger.success("O'chirish xabari muvaffaqiyatli tahrirlandi.")
        #             except Exception as e:
        #                 logger.error(f"O'chirish xabarini tahrirlashda xatolik: {e}")
        #             finally:
        #                 await self.state.delete('system.shutdown_notice')
        #     else:
        #         logger.warning("O'chirish xabarini tahrirlash uchun aktiv klient topilmadi.")

        if self.db and self.db.is_connected():
            await self.db.close()
        
        await self.cache.save_to_disk()
        await self.state.save_to_disk()
        
        logger.info("🔴 To'liq to'xtatish jarayoni muvaffaqiyatli yakunlandi.")



    async def _handle_post_restart_actions(self):
        """Dastur qayta ishga tushirilgandan keyin bajariladigan amallar."""
        logger.debug("[POST_RESTART] Qayta ishga tushishdan keyingi amallar boshlandi.")
        notice = self.state.get('system.restart_notice')
        
        if not notice or not isinstance(notice, dict):
            return

        try:
            await asyncio.sleep(2.0) # Klient tayyor bo'lishi uchun biroz kutish

            clients = self.client_manager.get_all_clients()
            if not (main_client := next((c for c in clients if c.is_connected()), None)):
                logger.warning("Restart xabarini tahrirlash uchun aktiv klient topilmadi.")
                return

            original_text = notice.get('original_text', "Userbot qayta ishga tushirildi...")
            
            final_text = f"<s>{html.escape(original_text)}</s>\n\n✅ <b>Muvaffaqiyatli qayta ishga tushirildi</b>"
            await main_client.edit_message(
                entity=int(notice['chat_id']), 
                message=int(notice['message_id']), 
                text=final_text, 
                parse_mode='HTML'
            )
            logger.success("Restart xabari muvaffaqiyatli tahrirlandi!")
        except Exception as e:
            logger.error(f"Restart xabarini tahrirlashda xatolik: {e}", exc_info=True)
        finally:
            await self.state.delete('system.restart_notice')



    async def interactive_startup_menu(self, force_menu: bool = False) -> Optional[int]:
        """
        Interaktiv menyu orqali akkauntni tanlash yoki yangi akkaunt qo'shish.
        """
        await self.db.connect()
        db_accounts = await self.db.fetchall("SELECT id, session_name, telegram_id, is_active FROM accounts ORDER BY id")
        json_credentials = load_credentials_from_file()

        if not db_accounts and json_credentials:
            logger.warning("Ma'lumotlar bazasi bo'sh, ammo saqlangan akkaunt ma'lumotlari (accounts.json) topildi.")
            print("--- Akkauntni Tiklash Menyusi ---")
            for i, cred in enumerate(json_credentials, 1):
                print(f" [{i}] {cred['session_name']}")
            print("\n [0] Butunlay yangi akkaunt qo'shish\n [q] Chiqish")
            while True:
                choice = await cli_prompt("\nTiklash yoki qo'shish uchun tanlang: ")
                if choice.lower() == 'q':
                    return None
                if choice == '0':
                    break
                try:
                    choice_idx = int(choice)
                    if 1 <= choice_idx <= len(json_credentials):
                        selected = json_credentials[choice_idx - 1]
                        logger.info(f"'{selected['session_name']}' akkauntini tiklash boshlanmoqda...")
                        new_account_id = await self.client_manager.add_new_account_interactive(cli_prompt, prefilled_data=selected)
                        if new_account_id:
                            await self.db.execute("UPDATE accounts SET is_active = ? WHERE id = ?", (True, new_account_id))
                            return new_account_id
                        else:
                            print("Xato: Akkauntni tiklash muvaffaqiyatsiz tugadi.")
                    else:
                        print("Xato: Noto'g'ri raqam. Qayta urinib ko'ring.")
                except ValueError:
                    print("Xato: Raqam kiriting.")

        if not db_accounts:
            logger.warning("Hech qanday akkaunt topilmadi. Yangi akkaunt qo'shish jarayoni boshlanmoqda...")
            new_account_id = await self.client_manager.add_new_account_interactive(cli_prompt)
            if new_account_id:
                await self.db.execute("UPDATE accounts SET is_active = ? WHERE id = ?", (True, new_account_id))
                return new_account_id
            return None

        active_db_accounts = [acc for acc in db_accounts if acc['is_active']]

        if len(active_db_accounts) == 1 and not force_menu:
            account = active_db_accounts[0]
            logger.info(f"Yagona faol akkaunt topildi: '{account['session_name']}'. Avtomatik ulanilmoqda...")
            return account['id']

        else:
            print("--- Userbotni Boshqarish Menyusi ---")
            for i, acc in enumerate(db_accounts, 1):
                status_indicator = " (aktiv)" if acc['is_active'] else ""
                tg_id_str = f"(TG ID: {acc['telegram_id']})" if acc['telegram_id'] else ""
                print(f" [{i}] {acc['session_name']} {tg_id_str}{status_indicator}")
            print("\n [0] Yangi akkaunt qo'shish\n [q] Chiqish")
            while True:
                choice = await cli_prompt("\nTanlovingizni kiriting: ")
                if choice.lower() == 'q':
                    return None
                if choice == '0':
                    new_account_id = await self.client_manager.add_new_account_interactive(cli_prompt)
                    if new_account_id:
                        await self.db.execute("UPDATE accounts SET is_active = ? WHERE id = ?", (True, new_account_id))
                        return new_account_id
                    return None
                try:
                    choice_idx = int(choice)
                    if 1 <= choice_idx <= len(db_accounts):
                        selected_account_id = db_accounts[choice_idx - 1]['id']

                        UPDATE_ACTIVE_STATUS_SQL = "UPDATE accounts SET is_active = ? WHERE id = ?"

                        if active_db_accounts:
                            await self.db.executemany(UPDATE_ACTIVE_STATUS_SQL, [(False, acc['id']) for acc in active_db_accounts])

                        await self.db.execute(UPDATE_ACTIVE_STATUS_SQL, (True, selected_account_id))
                        return selected_account_id
                    else:
                        print("Xato: Noto'g'ri raqam kiritildi.")
                except ValueError:
                    print("Xato: Raqam yoki 'q'/'0' harflaridan birini kiriting.")

        return None

    async def non_interactive_setup(self) -> Optional[int]:
        """
        Non-interaktiv rejimda akkauntni sozlash.
        .env faylidagi sozlamalardan foydalaniladi.
        """
        logger.info("🤖 Interaktiv bo'lmagan rejimda ishga tushirish...")
        await self.db.connect()

        active_account = await self.db.fetchone("SELECT id FROM accounts WHERE is_active = ? LIMIT 1", (True,))
        if active_account:
            logger.info(f"Mavjud faol akkaunt (ID: {active_account['id']}) topildi. Ulanilmoqda...")
            return active_account['id']

        logger.info("Faol akkaunt topilmadi. .env faylidan yangi akkaunt sozlamalari qidirilmoqda...")
        creds = {
            "api_id": self.config.get("NEW_ACCOUNT_API_ID"),
            "api_hash": self.config.get("NEW_ACCOUNT_API_HASH"),
            "session_name": self.config.get("NEW_ACCOUNT_SESSION_NAME"),
            "phone": self.config.get("NEW_ACCOUNT_PHONE"),
            "code": self.config.get("NEW_ACCOUNT_CODE"),
            "password": self.config.get("NEW_ACCOUNT_PASSWORD"),
        }

        for k, v in creds.items():
            if isinstance(v, SecretStr):
                creds[k] = v.get_secret_value()

        if not all([creds['api_id'], creds['api_hash'], creds['session_name']]):
            logger.critical(
                "Kritik xato: Interaktiv bo'lmagan rejimda yangi akkaunt qo'shish uchun .env faylida "
                "NEW_ACCOUNT_API_ID, NEW_ACCOUNT_API_HASH, va NEW_ACCOUNT_SESSION_NAME o'zgaruvchilari to'ldirilishi shart."
                "\nNEW_ACCOUNT_PHONE ham kerak bo'lishi mumkin, agar mavjud bo'lmasa interaktiv kiritishni talab qiladi."
            )
            return None

        new_account_id = await self.client_manager.add_account_non_interactive(creds)

        if new_account_id:
            logger.info(f"Yangi akkaunt (ID: {new_account_id}) muvaffaqiyatli qo'shildi.")
            await self.db.execute("UPDATE accounts SET is_active = ? WHERE id = ?", (True, new_account_id))
            return new_account_id
        else:
            logger.error("Yangi akkauntni .env sozlamalari orqali qo'shib bo'lmadi.")
            return None


    async def run(self, force_menu: bool = False):
        """Ilovaning asosiy ishga tushirish tsiklini boshqaradi."""
        try:
            logger.debug("[RUN_START] `app.run` metodi ishga tushdi.")
            await asyncio.gather(self.state.load_from_disk(), self.cache.load_from_disk())
            
            await self.state.set('system.lifecycle_signal', None, persistent=True)
            await self.state.set('system.start_time', time.time(), persistent=True)

            if self.config.get("NON_INTERACTIVE"):
                selected_account_id = await self.non_interactive_setup()
            else:
                selected_account_id = await self.interactive_startup_menu(force_menu=force_menu)

            if selected_account_id is None:
                logger.info("Foydalanuvchi tanlovi yoki sozlamalar xatosi bilan dastur yakunlandi.")
                await self.state.set('system.lifecycle_signal', 'shutdown')
                return

            await self.config.load_dynamic_settings()
            await self.ai_service.configure()

            if not await self.client_manager.start_client_by_id(selected_account_id):
                logger.critical("Tanlangan klientni ishga tushirib bo'lmadi. Dastur to'xtatiladi.")
                await self.state.set('system.lifecycle_signal', 'shutdown')
                return

            self.scheduler.start()
            
            # TUZATISH: Avval plaginlarni yuklaymiz, keyin vazifalarni
            await self.plugin_manager.load_all_plugins()
            
            # Endi barcha vazifalar ro'yxatdan o'tgan, scheduler ularni topa oladi
            await self.scheduler.load_jobs_from_db()
            await self.scheduler.schedule_system_tasks()

            logger.success("✅ Userbot muvaffaqiyatli ishga tushdi va xabarlarni tinglamoqda!")
            await self._handle_post_restart_actions()
            self.periodic_save_task = asyncio.create_task(self._periodic_persistence_task())
            logger.info("🔴 Dasturni to'xtatish uchun terminalda CTRL + C bosing.")
            
            clients = self.client_manager.get_all_clients()
            if not clients:
                logger.error("Ishga tushirilgan klientlar yo'q. Dastur to'xtatilmoqda.")
                await self.state.set('system.lifecycle_signal', 'shutdown')
                return

            disconnect_futures = {c.disconnected for c in clients}
            
            while self.is_running:
                check_signal_task = asyncio.create_task(asyncio.sleep(1))
                
                done, pending = await asyncio.wait(
                    disconnect_futures | {check_signal_task},
                    return_when=asyncio.FIRST_COMPLETED
                )

                if check_signal_task in done:
                    signal = self.state.get('system.lifecycle_signal')
                    if signal in ['restart', 'shutdown']:
                        logger.info(f"[LIFECYCLE] '{signal}' signali aniqlandi. `app.run` sikli to'xtatilmoqda.")
                        self.is_running = False
                        for task in pending: task.cancel()
                        break
                else:
                    logger.warning("Bir yoki bir nechta klient aloqadan uzildi. Qayta ishga tushiriladi.")
                    await self.state.set('system.lifecycle_signal', 'restart')
                    self.is_running = False
                    for task in pending: task.cancel()
                    break

        except (KeyboardInterrupt, asyncio.CancelledError):
            logger.warning("\n⌨️ Dastur foydalanuvchi tomonidan (CTRL+C) to'xtatildi.")
            await self.state.set('system.lifecycle_signal', 'shutdown')
        except Exception as e:
            logger.exception(f"💥 Dasturning asosiy qismida kutilmagan xatolik yuz berdi: {e}")
            await self.state.set('system.lifecycle_signal', 'shutdown')
        finally:
            if self.periodic_save_task and not self.periodic_save_task.done():
                self.periodic_save_task.cancel()
            logger.info("🏁 Ilova ish sikli (app.run) yakunlandi.")
