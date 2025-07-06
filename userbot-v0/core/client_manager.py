import asyncio
import json
import random
from pathlib import Path
from typing import Any, Dict, List, Optional, Callable, Awaitable, Union, cast

from loguru import logger

from telethon import TelegramClient, errors, events
from telethon.tl.types import User, InputPeerUser
from telethon.tl.types.photos import Photo # <-- Photo klassini import qildik


# Bog'liqliklar uchun type-hinting
from typing import TYPE_CHECKING
if TYPE_CHECKING:
    from core.database import AsyncDatabase
    from core.config_manager import ConfigManager
    from core.state import AppState
    from pydantic import SecretStr # SecretStr tipi uchun, agar to'g'ridan-to'g'ri ishlatilsa


# Konstanta va tiplarni aniqlaymiz
UPDATE_ACC_STATUS_SQL = "UPDATE accounts SET status = ? WHERE id = ?"
CLIENT_START_DELAY = 2 # Klientlarni ishga tushirish orasidagi kechikish
RECONNECT_DELAY = 5    # Qayta ulanish kechikishi

ProgressCallback = Optional[Callable[[str], Awaitable[None]]] # Type alias


def save_credential_to_file(credential: Dict[str, Any]):
    """
    Akkaunt ma'lumotlarini accounts.json fayliga vaqtinchalik saqlaydi.
    Bu, asosan, interaktiv login paytida sessiyani zaxiralash uchun ishlatiladi.
    """
    file_path = Path("data/accounts.json")
    file_path.parent.mkdir(parents=True, exist_ok=True)
    accounts: List[Dict[str, Any]] = []
    if file_path.exists() and file_path.stat().st_size > 0:
        with file_path.open('r', encoding='utf-8') as f:
            try:
                accounts = json.load(f)
            except json.JSONDecodeError:
                logger.warning("accounts.json fayli buzilgan yoki noto'g'ri formatda. Yangitdan yaratiladi.", exc_info=True)

    found = False
    for i, acc in enumerate(accounts):
        if acc.get("session_name") == credential.get("session_name"):
            accounts[i] = credential
            found = True
            break
    if not found:
        accounts.append(credential)

    with file_path.open('w', encoding='utf-8') as f:
        json.dump(accounts, f, indent=4, ensure_ascii=False)
    logger.debug(f"'{credential.get('session_name', 'Noma`lum sessiya')}' ma'lumotlari accounts.json faylida vaqtinchalik saqlandi.")


class ClientManager:
    """Userbotning barcha TelegramClient obyektlarini boshqaruvchi markaziy klass."""

    def __init__(
        self,
        database: 'AsyncDatabase',
        config: 'ConfigManager', # ConfigManager ni qabul qilish uchun
        state: 'AppState'       # AppState ni qabul qilish uchun
    ):
        self._db: 'AsyncDatabase' = database
        self._config: 'ConfigManager' = config
        self._state: 'AppState' = state
        self._clients: Dict[int, TelegramClient] = {}
        self._reconnect_tasks: Dict[int, asyncio.Task] = {}
        self._lock = asyncio.Lock()

        # --- XATO TUZATISH: Sessiya fayllari uchun papka yaratish ---
        sessions_dir = Path("sessions")
        sessions_dir.mkdir(parents=True, exist_ok=True)
        # -------------------------------------------------------------
        
        logger.info(f"ClientManager (Modernized v1.4) ishga tayyor. Sessiyalar papkasi: '{sessions_dir.resolve()}'")


    def set_db_instance(self, db_instance: 'AsyncDatabase'):
        self._db = db_instance
        logger.debug("ClientManager database instance bilan bog'landi.")

    def set_config_instance(self, config_instance: 'ConfigManager'):
        self._config = config_instance
        logger.debug("ClientManager config instance bilan bog'landi.")

    def set_state_instance(self, state_instance: 'AppState'):
        self._state = state_instance
        logger.debug("ClientManager state instance bilan bog'landi.")


    async def start_all_clients(self) -> None:
        """Ma'lumotlar bazasidagi barcha faol klientlarni ishga tushiradi."""
        logger.info("Barcha faol klientlarni ishga tushirish jarayoni boshlandi...")
        try:
            accounts_to_start = await self._db.fetchall("SELECT * FROM accounts WHERE is_active = ?", (True,))
            if not accounts_to_start:
                logger.warning("Ishga tushirish uchun faol akkauntlar topilmadi.")
                return

            successful_starts, failed_starts = 0, 0
            for account in accounts_to_start:
                if await self.start_single_client(account):
                    successful_starts += 1
                else:
                    failed_starts += 1
                await asyncio.sleep(CLIENT_START_DELAY)

            logger.success(f"Klientlarni ishga tushirish yakunlandi: {successful_starts} muvaffaqiyatli, {failed_starts} xatolik.")
        except Exception as e:
            logger.critical(f"Klientlarni ommaviy ishga tushirishda kutilmagan kritik xatolik: {e}", exc_info=True)

    async def start_single_client(self, account_data: Dict[str, Any]) -> bool:
        """Berilgan akkaunt ma'lumotlari asosida bitta klientni ishga tushiradi."""
        if not account_data:
            logger.warning("Klientni ishga tushirish uchun akkaunt ma'lumotlari bo'sh.")
            return False

        account_id = account_data.get('id')
        session_name = account_data.get('session_name')
        logger.debug(f"ID {account_id} ('{session_name}') uchun klientni ishga tushirish boshlandi.")
        
        api_id_raw = account_data.get('api_id')
        api_hash_raw = account_data.get('api_hash')

        if not isinstance(account_id, int) or \
           not isinstance(session_name, str) or \
           not isinstance(api_id_raw, int) or \
           not isinstance(api_hash_raw, str):
            logger.error(f"ID {account_id} uchun akkaunt ma'lumotlari to'liq yoki noto'g'ri tipda. Klient ishga tushirilmadi.")
            if isinstance(account_id, int):
                await self._db.execute(UPDATE_ACC_STATUS_SQL, ('invalid_data', account_id))
            return False

        api_id: int = api_id_raw
        api_hash: str = api_hash_raw
        
        logger.debug(f"ID {account_id}: Mavjud klient holati tekshirilmoqda...")
        if account_id in self._clients and self._clients[account_id].is_connected():
            logger.info(f"ID {account_id} ('{session_name}') allaqachon ishga tushgan va ulangan. O'tkazib yuborildi.")
            return True

        logger.debug(f"ID {account_id}: Yangi TelegramClient nusxasi yaratilmoqda. Sessiya: 'sessions/{session_name}.session'")
        client = TelegramClient(
            session=Path("sessions") / session_name,
            api_id=api_id,
            api_hash=api_hash
        )
        
        successfully_started = False
        try:
            logger.debug(f"ID {account_id}: Telegram serverlariga ulanishga harakat qilinmoqda (client.connect)...")
            await client.connect()
            logger.debug(f"ID {account_id}: Ulanish muvaffaqiyatli. Foydalanuvchi avtorizatsiyasi tekshirilmoqda (is_user_authorized)...")
            
            if not await client.is_user_authorized():
                logger.error(f"ID {account_id} ('{session_name}') avtorizatsiyadan o'tmagan. Qayta login kerak.")
                await self._db.execute(UPDATE_ACC_STATUS_SQL, ('login_required', account_id))
                return False

            logger.debug(f"ID {account_id}: Avtorizatsiya muvaffaqiyatli. Foydalanuvchi ma'lumotlari olinmoqda (get_me)...")
            me_result: Union[User, InputPeerUser] = await client.get_me()

            if isinstance(me_result, User):
                user_id = me_result.id
                user_name = me_result.first_name or f"ID: {user_id}"
                logger.debug(f"ID {account_id}: Foydalanuvchi ma'lumotlari olindi: '{user_name}' (TG ID: {user_id})")
            elif isinstance(me_result, InputPeerUser):
                user_id = me_result.user_id
                user_name = f"InputPeerUser ID: {user_id}"
                logger.warning(f"ID {account_id}: To'liq foydalanuvchi ma'lumotlari olinmadi (InputPeerUser).")
            else:
                logger.error(f"ID {account_id}: get_me() kutilmagan tipni qaytardi: {type(me_result).__name__}. Klient ishga tushirilmadi.")
                return False

            async with self._lock:
                self._clients[account_id] = client
                logger.debug(f"ID {account_id}: Klient menejerning ichki ro'yxatiga qo'shildi.")

            await self._db.execute("UPDATE accounts SET status = ?, telegram_id = ? WHERE id = ?", ('running', user_id, account_id))
            logger.debug(f"ID {account_id}: Ma'lumotlar bazasidagi status 'running' ga o'zgartirildi.")

            self._setup_auto_reconnect(client, account_id)
            logger.success(f"✅ Akkaunt '{user_name}' (ID: {account_id}) muvaffaqiyatli ishga tushdi va ulandi.")
            successfully_started = True
            return True

        except errors.AuthKeyUnregisteredError:
            logger.error(f"XATO: ID {account_id} ('{session_name}') uchun sessiya bekor qilingan (AuthKeyUnregisteredError). Qayta login kerak.", exc_info=False)
            await self._db.execute(UPDATE_ACC_STATUS_SQL, ('login_required', account_id))
            return False
        except (errors.RPCError, ConnectionError) as e:
            logger.error(f"XATO: ID {account_id} ('{session_name}') uchun ulanish yoki RPC xatoligi: {e!r}", exc_info=False)
            await self._db.execute(UPDATE_ACC_STATUS_SQL, ('auth_error', account_id))
            return False
        except Exception as e:
            logger.error(f"XATO: ID {account_id} ('{session_name}') ni ishga tushirishda noma'lum xatolik: {e!r}", exc_info=True)
            await self._db.execute(UPDATE_ACC_STATUS_SQL, ('unknown_error', account_id))
            return False
        finally:
            logger.trace(f"ID {account_id}: 'finally' bloki ishga tushdi. Muvaffaqiyatli start: {successfully_started}")
            if not successfully_started and client.is_connected():
                logger.debug(f"ID {account_id}: Ishga tushirish muvaffaqiyatsiz bo'lgani uchun klient ulanishi uzilmoqda...")
                try:
                    await cast(Awaitable[None], client.disconnect())
                except Exception as disconnect_e:
                    logger.warning(f"ID {account_id}: Klientni xatolikdan so'ng ajratishda qo'shimcha xatolik: {disconnect_e!r}")


    async def monitor_disconnect(self, client: TelegramClient, account_id: int):
        """Klient uzilishini kuzatadi va qayta ulanishga urinadi."""
        try:
            await cast(Awaitable[None], client.disconnected)

            logger.warning(f"Akkaunt ID: {account_id} aloqadan uzildi. Qayta ulanishga urinilmoqda...")

            retries = 5
            base_delay = RECONNECT_DELAY
            for attempt in range(retries):
                logger.info(f"Akkaunt ID: {account_id} uchun qayta ulanish urinishi {attempt + 1}/{retries}...")
                await self._state.set(f'client.{account_id}.reconnecting', True, persistent=False)

                if await self.start_client_by_id(account_id):
                    logger.success(f"Akkaunt ID: {account_id} muvaffaqiyatli qayta ulandi.")
                    await self._state.set(f'client.{account_id}.reconnecting', False, persistent=False)
                    return

                delay = base_delay * (2 ** attempt) + random.uniform(0, 1) # Jitter qo'shish
                logger.info(f"Akkaunt ID: {account_id} uchun {delay:.2f} soniya kutib, qayta ulanishga urinish...")
                await asyncio.sleep(delay)

            logger.error(f"Akkaunt ID: {account_id} bir nechta urinishdan so'ng qayta ulanmadi. Tekshirish kerak.")
            await self._db.execute(UPDATE_ACC_STATUS_SQL, ('disconnected', account_id))
            await self._state.set(f'client.{account_id}.reconnecting', False, persistent=False)

        except asyncio.CancelledError:
            logger.debug(f"Akkaunt ID: {account_id} uchun qayta ulanish monitori bekor qilindi.")
            await self._state.set(f'client.{account_id}.reconnecting', False, persistent=False)
            raise
        except Exception as e:
            logger.error(f"Akkaunt ID: {account_id} uchun qayta ulanish monitorida kutilmagan xato: {e!r}", exc_info=True)
            await self._db.execute(UPDATE_ACC_STATUS_SQL, ('reconnect_error', account_id))
            await self._state.set(f'client.{account_id}.reconnecting', False, persistent=False)


    def _setup_auto_reconnect(self, client: TelegramClient, account_id: int):
        """Har bir klient uchun avtomatik qayta ulanish monitorini sozlaydi."""
        task = asyncio.create_task(self.monitor_disconnect(client, account_id))
        self._reconnect_tasks[account_id] = task
        logger.debug(f"ID: {account_id} uchun auto-reconnect monitor ishga tushdi.")

    async def _cancel_reconnect_tasks(self):
        """Barcha avtomatik qayta ulanishni kuzatuvchi vazifalarni bekor qiladi."""
        if not self._reconnect_tasks:
            return

        logger.debug(f"{len(self._reconnect_tasks)} ta qayta ulanish monitorini bekor qilish...")
        tasks_to_cancel = list(self._reconnect_tasks.values())
        for task in tasks_to_cancel:
            task.cancel()

        await asyncio.gather(*tasks_to_cancel, return_exceptions=True)
        self._reconnect_tasks.clear()
        logger.info("Avtomatik qayta ulanish monitorlari to'xtatildi.")

    async def _authenticate_client(
        self,
        client: TelegramClient,
        prompt: Callable[[str], Awaitable[str]],
        phone: Optional[str],
        code: Optional[str] = None,
        password: Optional[str] = None,
        progress: ProgressCallback = None
    ) -> bool:
        """TelegramClient ni avtorizatsiya qiladi va jarayonni batafsil loglaydi."""
        if await client.is_user_authorized():
            logger.info("Mijoz allaqachon avtorizatsiyadan o'tgan.")
            return True

        current_phone = phone
        logger.debug(f"Autentifikatsiya boshlandi. Telefon: {current_phone}")

        if not current_phone:
            phone_input = await prompt("Telefon raqamingizni kiriting (+998...): ")
            if not phone_input:
                logger.error("Telefon raqami kiritilmadi. Avtorizatsiya bekor qilindi.")
                return False
            current_phone = phone_input
            logger.debug(f"Foydalanuvchi telefon raqamini kiritdi: {current_phone}")

        current_code: str = ""  # Always define current_code before try block
        try:
            if progress: await progress("Tasdiqlash kodi yuborilmoqda...")
            logger.debug(f"'{current_phone}' raqamiga kod so'rovi yuborilmoqda...")

            sent_code = await client.send_code_request(current_phone)
            logger.info(f"Kod so'rovi muvaffaqiyatli yuborildi. Qaytgan obyekt: {sent_code.to_dict()}")

            # --- XATO TUZATISH: `current_code` unbound bo'lishining oldini olish ---
            current_code = code if code is not None else ""
            if not current_code:
                code_input = await prompt("Telegramdan kelgan kodni kiriting: ")
                if not code_input:
                    logger.error("Tasdiqlash kodi kiritilmadi. Avtorizatsiya bekor qilindi.")
                    return False
                current_code = code_input
            # --------------------------------------------------------------------
            logger.debug(f"Foydalanuvchi tasdiqlash kodini kiritdi: '{current_code}'")

            if progress: await progress("Kod tekshirilmoqda...")
            logger.debug(f"client.sign_in(phone='{current_phone}', code='...') chaqirilmoqda.")
            
            result = await client.sign_in(phone=current_phone, code=current_code, phone_code_hash=sent_code.phone_code_hash)
            logger.success("sign_in muvaffaqiyatli bajarildi.")
            return bool(result)

        except errors.SessionPasswordNeededError:
            logger.info("Akkaunt uchun 2FA paroli talab qilinmoqda.")
            if progress: await progress("Ikki bosqichli parol (2FA) kutilmoqda...")

            current_password: str = password if password is not None else ""
            if not current_password:
                password_input = await prompt("Ikki bosqichli autentifikatsiya (2FA) parolini kiriting: ")
                if not password_input:
                    logger.error("Ikki bosqichli parol kiritilmadi. Avtorizatsiya bekor qilindi.")
                    return False
                current_password = password_input
            logger.debug("Foydalanuvchi 2FA parolini kiritdi.")

            if progress: await progress("Parol tekshirilmoqda...")
            logger.debug("client.sign_in(password='...') chaqirilmoqda.")
            
            result = await client.sign_in(password=current_password)
            logger.success("2FA parol bilan sign_in muvaffaqiyatli bajarildi.")
            return bool(result)

        except errors.PhoneCodeInvalidError as e:
            logger.critical(f"Telegram NOTO'G'RI KOD xatoligini qaytardi. Kiritilgan kod: '{current_code}'. Xato: {e!r}")
            return False
            
        except errors.FloodWaitError as e:
            logger.warning(f"Juda ko'p urinishlar. {e.seconds} soniya kutiladi: {e!r}")
            if progress: await progress(f"Kuting... {e.seconds} soniya.")
            await asyncio.sleep(e.seconds + 2)
            return False
        except Exception as e:
            logger.error(f"Kirish jarayonida kutilmagan xatolik: {e!r}", exc_info=True)
            return False

    async def _save_account_to_db(self, client: TelegramClient, s_name: str, api_id: int, api_hash: str) -> Optional[int]:
        """Yangi avtorizatsiya qilingan akkaunt ma'lumotlarini ma'lumotlar bazasiga saqlaydi."""
        logger.debug("Foydalanuvchi ma'lumotlarini olish uchun get_me() chaqirilmoqda...")
        me_result: Union[User, InputPeerUser] = await client.get_me() 
        logger.debug(f"get_me() dan olingan natija turi: {type(me_result).__name__}")

        user_id: Optional[int] = None
        user_first_name: Optional[str] = None
        user_phone: Optional[str] = None

        if isinstance(me_result, User):
            user_id = me_result.id
            user_first_name = me_result.first_name
            user_phone = f"+{me_result.phone}" if me_result.phone else None
            logger.success(f"Akkaunt '{user_first_name}' (ID: {user_id}) tizimga muvaffaqiyatli kirdi!")
        elif isinstance(me_result, InputPeerUser):
            user_id = me_result.user_id
            user_first_name = f"User (ID: {user_id})"
            user_phone = None
            logger.warning(f"Akkaunt '{s_name}' uchun to'liq foydalanuvchi ma'lumotlari olinmadi (InputPeerUser).")
        else:
            logger.error(f"Akkaunt '{s_name}' uchun foydalanuvchi ma'lumotlari kutilmagan tipda ({type(me_result).__name__}). DBga saqlanmadi.")
            return None

        if user_id is None:
            logger.error(f"Akkaunt '{s_name}' uchun foydalanuvchi IDsi aniqlanmadi. DBga saqlanmadi.")
            return None

        save_credential_to_file({"session_name": s_name, "api_id": api_id, "api_hash": api_hash, "phone": user_phone})
        
        logger.debug(f"Yangi akkaunt (TG_ID: {user_id}) ma'lumotlar bazasiga saqlanmoqda...")
        inserted_id = await self._db.execute_insert(
            "INSERT INTO accounts (session_name, api_id, api_hash, telegram_id, status, is_active) VALUES (?, ?, ?, ?, ?, ?)",
            (s_name, api_id, api_hash, user_id, 'stopped', False),
        )
        logger.debug(f"Akkaunt DBga {inserted_id} ID bilan saqlandi.")
        return inserted_id



    async def add_new_account_interactive(self, prompt: Callable[[str], Awaitable[str]], progress: ProgressCallback = None, prefilled_data: Optional[Dict[str, Any]] = None) -> Optional[int]:
        """Interaktiv rejimda yangi akkaunt qo'shish yoki mavjudini tiklash."""
        logger.info("Yangi akkaunt qo'shish jarayoni boshlandi (interaktiv rejim)...")
        client: Optional[TelegramClient] = None
        s_name: Optional[str] = None # `finally` bloki uchun
        try:
            api_id: Optional[int] = None
            api_hash: Optional[str] = None
            phone: Optional[str] = None
            code: Optional[str] = None
            password: Optional[str] = None

            if not prefilled_data:
                logger.debug("Foydalanuvchidan sozlamalar so'ralmoqda...")
                try:
                    api_id_input = await prompt("API ID: ")
                    api_id = int(api_id_input) if api_id_input and api_id_input.strip().isdigit() else None
                    api_hash = await prompt("API Hash: ")
                    s_name = await prompt("Sessiya nomi: ")
                except ValueError:
                    logger.error("API ID raqam bo'lishi kerak. Jarayon bekor qilindi.")
                    return None
            else:
                logger.debug("Oldindan to'ldirilgan ma'lumotlar ishlatilmoqda...")
                api_id = prefilled_data.get('api_id')
                api_hash = prefilled_data.get('api_hash')
                s_name = prefilled_data.get('session_name')
                phone = prefilled_data.get('phone')

            if not prefilled_data: # Agar prefilled_data mavjud bo'lmasa yoki to'liq bo'lmasa, foydalanuvchidan so'raymiz
                if progress:
                    await progress("Sozlamalar kiritilmoqda...")
                try:
                    api_id_input = await prompt("API ID: ")
                    api_id = int(api_id_input) if api_id_input and api_id_input.strip().isdigit() else None
                    api_hash = await prompt("API Hash: ")
                    s_name = await prompt("Sessiya nomi: ")
                except ValueError:
                    logger.error("API ID raqam bo'lishi kerak. Jarayon bekor qilindi.")
                    return None

            if not (isinstance(api_id, int) and isinstance(api_hash, str) and isinstance(s_name, str)):
                logger.error("API ID, API Hash yoki sessiya nomi kiritilmadi/noto'g'ri. Jarayon bekor qilindi.")
                return None

            if await self._db.fetchone("SELECT id FROM accounts WHERE session_name = ?", (s_name,)):
                logger.error(f"'{s_name}' nomli sessiya ma'lumotlar bazasida allaqachon mavjud.")
                return None
            
            logger.debug(f"'{s_name}' sessiyasi uchun TelegramClient yaratilmoqda...")
            client = TelegramClient(Path("sessions") / s_name, api_id, api_hash)
            
            logger.debug("Telegram serverlariga ulanish...")
            await client.connect()
            logger.info("✅ Serverga muvaffaqiyatli ulandi.")

            auth_success = await self._authenticate_client(
                client=client, prompt=prompt, phone=phone, progress=progress, code=code, password=password
            )

            if not auth_success:
                logger.error(f"Akkaunt '{s_name}' uchun autentifikatsiya muvaffaqiyatsiz yakunlandi.")
                return None

            return await self._save_account_to_db(client, s_name, api_id, api_hash)

        except Exception as e:
            logger.critical(f"Akkaunt qo'shishda kutilmagan kritik xatolik: {e!r}", exc_info=True)
            return None
        finally:
            if client and client.is_connected():
                logger.debug(f"'{s_name}' uchun klient ulanishini yopish (finally bloki).")
                try:
                    await client.disconnect()
                except Exception as disconnect_e:
                    logger.warning(f"Klientni ajratishda xato: {disconnect_e!r}")
                    
    async def add_account_non_interactive(self, creds: Dict[str, Any]) -> Optional[int]:
        """Akkauntni lug'atdagi ma'lumotlar orqali (interaktiv bo'lmagan rejimda) qo'shadi."""
        logger.info("🤖 Yangi akkauntni interaktiv bo'lmagan rejimda qo'shish...")
        client: Optional[TelegramClient] = None
        try:
            api_id_val = creds.get('api_id')
            api_hash_val = creds.get('api_hash')
            s_name = creds.get('session_name')
            phone = creds.get('phone')
            code = creds.get('code')
            password = creds.get('password')

            if api_id_val is None:
                logger.error("NEW_ACCOUNT_API_ID mavjud emas.")
                return None
            try:
                api_id = int(api_id_val)
            except ValueError:
                logger.error("NEW_ACCOUNT_API_ID raqam bo'lishi kerak.")
                return None

            # SecretStr obyektidan haqiqiy qiymatni olish
            if api_hash_val is not None and hasattr(api_hash_val, 'get_secret_value'):
                api_hash_val = api_hash_val.get_secret_value()
            if password is not None and hasattr(password, 'get_secret_value'):
                password = password.get_secret_value()

            # Barcha muhim ma'lumotlar mavjudligini va tiplarini tekshiramiz
            if not (isinstance(api_id, int) and isinstance(api_hash_val, str) and isinstance(s_name, str) and isinstance(phone, str)):
                logger.error("Interaktiv bo'lmagan rejim uchun API_ID, API_HASH, SESS_NAME, PHONE shart. Ba'zilar yo'q yoki noto'g'ri tipda.")
                return None

            api_hash: str = api_hash_val
            phone_str: str = phone
            s_name_str: str = s_name

            if await self._db.fetchone("SELECT id FROM accounts WHERE session_name = ?", (s_name_str,)):
                logger.error(f"'{s_name_str}' nomli sessiya allaqachon mavjud.")
                return None

            client = TelegramClient(Path("sessions") / s_name_str, api_id, api_hash)
            await client.connect()

            # --- Interaktiv bo'lmagan prompt funksiyasini yaratamiz ---
            async def prompt_non_interactive(message: str) -> str:
                if "Telefon raqamingizni kiriting" in message:
                    if phone_str: return phone_str
                elif "Telegramdan kelgan kodni kiriting" in message:
                    if isinstance(code, str): return code
                elif "Ikki bosqichli autentifikatsiya (2FA) parolini kiriting" in message:
                    if isinstance(password, str): return password
                
                logger.critical(f"Interaktiv bo'lmagan rejimda kerakli ma'lumot ({message.strip()}) mavjud emas.")
                raise ValueError("Missing credential for non-interactive login in headless mode")

            # _authenticate_client metodidan foydalanamiz
            auth_success = await self._authenticate_client(
                client=client,
                prompt=prompt_non_interactive, # Bizning non-interactive prompt
                phone=phone_str, # oldindan to'ldirilgan telefon raqami
                code=code, # oldindan to'ldirilgan kod
                password=password, # oldindan to'ldirilgan parol
                progress=None # Interaktiv bo'lmagan rejimda progress ko'rsatilmaydi
            )

            if not auth_success:
                logger.error(f"Akkaunt '{s_name_str}' uchun autentifikatsiya muvaffaqiyatsiz yakunlandi (non-interactive).")
                return None

            return await self._save_account_to_db(client, s_name_str, api_id, api_hash)

        except Exception as e:
            logger.critical(f"Akkauntni interaktiv bo'lmagan rejimda qo'shishda kutilmagan kritik xatolik: {e!r}", exc_info=True)
            return None
        finally:
            if client and client.is_connected():
                try:
                    await client.disconnect() # type: ignore
                except Exception as disconnect_e:
                    logger.warning(f"Klientni ajratishda xato: {disconnect_e!r}")

    async def start_client_by_id(self, account_id: int) -> bool:
        """Berilgan ID bo'yicha klientni topib va ishga tushiradi."""
        account_data = await self._db.fetchone("SELECT * FROM accounts WHERE id = ? AND is_active = ?", (account_id, True))
        return await self.start_single_client(account_data) if account_data else False

    async def stop_all_clients(self) -> None:
        """Barcha ulangan klientlarni to'xtatadi va DB statusini yangilaydi."""
        logger.info("Barcha klientlarni to'xtatish...")

        await self._cancel_reconnect_tasks()

        async with self._lock:
            # .values() o'rniga .items() dan foydalanamiz, bu bizga account_id (kalit) va klient (qiymat) ni beradi
            clients_to_disconnect_items = list(self._clients.items())

            # Barcha klientlarni avval uzamiz
            # Endi (account_id, client_obj) tuple bo'ylab aylanmoqdamiz
            for account_id, client_obj in clients_to_disconnect_items: # <<<< BU QATORNI O'ZGARTIRING
                if client_obj.is_connected():
                    try:
                        await cast(Awaitable[None], client_obj.disconnect())
                    except Exception as e:
                        session_name = getattr(client_obj.session, 'name', 'Noma`lum') if client_obj.session else 'Noma`lum'
                        # ID uchun endi to'g'ri 'account_id' o'zgaruvchisidan foydalanamiz
                        logger.warning(f"Klient '{session_name}' (ID: {account_id}) ni ajratishda xato: {e!r}") # <<<< BU QATORNI O'ZGARTIRING
                else:
                    session_name = getattr(client_obj.session, 'name', 'Noma`lum') if client_obj.session else 'Noma`lum'
                    # ID uchun endi to'g'ri 'account_id' o'zgaruvchisidan foydalanamiz
                    logger.debug(f"Klient {session_name} (ID: {account_id}) allaqachon uzilgan.") # <<<< BU QATORNI O'ZGARTIRING

            # Qolgan kod avvalgi tuzatishdagidek qoladi
            if self._clients:
                account_ids = list(self._clients.keys()) 
                placeholders = ','.join('?' * len(account_ids))
                
                await self._db.execute(
                    f"UPDATE accounts SET status = 'stopped' WHERE id IN ({placeholders}) AND status = 'running'",
                    tuple(account_ids)
                )
                logger.info(f"{len(account_ids)} ta klientdan 'running' holatidagilari 'stopped' ga o'zgartirildi.")
            self._clients.clear()
        logger.success("Barcha klientlar muvaffaqiyatli to'xtatildi.")

    async def broadcast_message(self, chat_id: int, message: str, delay: float = 0.5):
        """Barcha ulangan klientlar orqali xabar yuboradi."""
        logger.info(f"{chat_id} ga ommaviy xabar yuborish boshlandi...")
        sent, failed = 0, 0

        async with self._lock:
            clients_snapshot = list(self._clients.items())

        for acc_id, client in clients_snapshot:
            if not client.is_connected():
                logger.warning(f"Akkaunt ID {acc_id} ulanmagan, xabar yuborilmadi.")
                failed += 1
                continue
            try:
                await client.send_message(chat_id, message)
                sent += 1
            except Exception as e:
                logger.error(f"ID {acc_id} xabar yuborishda xatolik: {e!r}", exc_info=True)
                failed += 1
            await asyncio.sleep(delay)
        logger.info(f"Ommaviy xabar yuborish yakunlandi: {sent} muvaffaqiyatli, {failed} xatolik.")

    def get_all_clients(self) -> List[TelegramClient]:
        """Barcha aktiv TelegramClient obyektlari ro'yxatini qaytaradi."""
        return list(self._clients.values())

    def get_client(self, account_id: int) -> Optional[TelegramClient]:
        """Berilgan ID bo'yicha klient obyektini qaytaradi."""
        return self._clients.get(account_id)
