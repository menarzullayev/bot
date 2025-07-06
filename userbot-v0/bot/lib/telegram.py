# bot/lib/telegram.py
"""
Telethon kutubxonasi bilan ishlashni soddalashtiradigan, qayta ishlatiladigan
professional yordamchi funksiyalar to'plami.
"""

import asyncio
import html
from typing import Any, Callable, Coroutine, List, Optional, Union, AsyncGenerator, TypeAlias, Dict, Tuple

from loguru import logger
from telethon.tl.custom import Message
from telethon.tl.types import User, Chat, Channel, PeerChannel, PeerUser, PeerChat, UserProfilePhoto
from telethon.tl.types import ChannelParticipantsAdmins
from telethon.tl import types, functions

from telethon.errors import (
    FloodWaitError,
    MessageNotModifiedError,
    UserIsBlockedError,
    RpcCallFailError,
    TimedOutError,
    MessageDeleteForbiddenError,
)
from telethon import TelegramClient

from core.app_context import AppContext


# ----- TURLAR UCHUN ALIASLAR (TYPE ALIASES) -----
Entity: TypeAlias = Union[User, Chat, Channel]
EntityResolvable: TypeAlias = Union[int, str, Entity]


# ===== 1. API MUROJAATLARI VA XATOLIKLARNI BOSHQARISH =====

async def retry_telegram_api_call(
    api_func: Callable[..., Any], *args: Any, retries: int = 4, delay: float = 1.0, **kwargs: Any
) -> Any:
    """
    Telegram API so'rovini kengaytirilgan xatolik turlari va dinamik kutish
    vaqti bilan himoyalaydi.
    """
    for i in range(retries):
        try:
            return await api_func(*args, **kwargs)
        except (FloodWaitError, RpcCallFailError, TimedOutError, ConnectionError, asyncio.TimeoutError) as e:
            wait_time = delay * (2**i)
            if isinstance(e, FloodWaitError):
                wait_time = max(wait_time, e.seconds + 1)

            logger.warning(
                f"Telegram API xatosi ({api_func.__name__}): {e}. "
                f"{wait_time:.2f}s dan keyin qayta urinilmoqda... ({i+1}/{retries})"
            )
            await asyncio.sleep(wait_time)
        except (MessageDeleteForbiddenError, MessageNotModifiedError, UserIsBlockedError) as e:
            logger.debug(f"Maxsus Telegram xatosi, qayta urinilmaydi ({api_func.__name__}): {e}")
            raise  # Bu xatoliklarni yuqoriga uzatamiz, chunki qayta urinish befoyda
        except Exception as e:
            logger.error(f"Telegram API chaqiruvida kutilmagan xato ({api_func.__name__}): {e}", exc_info=True)
            raise # Noma'lum xatolikni ham yuqoriga uzatgan ma'qul
    logger.error(f"Telegram API chaqiruvi ({api_func.__name__}) {retries} urinishdan keyin ham muvaffaqiyatsiz tugadi.")
    return None



async def resolve_entity(context: AppContext, client: TelegramClient, entity_resolvable: EntityResolvable) -> Optional[Entity]:
    """Username, ID yoki havola orqali Telegram obyektini (user, chat) keshdan foydalanib xavfsiz topadi."""
    if not client or not entity_resolvable:
        logger.warning("resolve_entity: Client yoki entity_resolvable bo'sh.")
        return None

    # Raqamli ID'larni normallashtirish
    entity_id_str = str(entity_resolvable)
    if entity_id_str.startswith('-') and entity_id_str[1:].isdigit():
        entity_resolvable = int(entity_id_str)

    cache_key = f"entity:{entity_resolvable}"

    cached_entity = await context.cache.get(cache_key)
    if isinstance(cached_entity, (User, Chat, Channel)):
        logger.debug(f"Entity keshdan olindi: {entity_resolvable}")
        return cached_entity

    try:
        entity = await retry_telegram_api_call(client.get_entity, entity_resolvable)
        if isinstance(entity, (User, Chat, Channel)):
            await context.cache.set(cache_key, entity, ttl=3600)
            logger.debug(f"Entity API'dan olindi va keshga saqlandi: {entity_resolvable}")
            return entity
    except (ValueError, TypeError) as e:
        logger.debug(f"Entity topilmadi (ID/username: {entity_resolvable}): {e}")
    except Exception as e:
        logger.error(f"resolve_entity da kutilmagan xato (ID/username: {entity_resolvable}): {e}")

    return None




# ===== 2. FOYDALANUVCHI VA CHATLAR BILAN ISHLASH =====

def get_peer_id(peer: Union[int, types.TypePeer]) -> int:
    """Telethon'ning Peer obyektidan to'g'ri sonli ID'ni ajratib oladi."""
    if isinstance(peer, int):
        return peer
    if isinstance(peer, PeerUser):
        return peer.user_id
    if isinstance(peer, PeerChat):
        return -peer.chat_id
    if isinstance(peer, PeerChannel):
        # -100 formatiga o'tkazish
        return int(f"-100{peer.channel_id}")
    if hasattr(peer, 'id'):
        # Umumiy holat
        is_channel = hasattr(peer, 'megagroup') or isinstance(peer, Channel)
        return int(f"-100{peer.id}") if is_channel else peer.id

    logger.error(f"Kutilmagan peer turi: {type(peer)}")
    raise TypeError(f"Kutilmagan peer turi: {type(peer)}")


async def get_me(context: AppContext, client: TelegramClient) -> Optional[User]:
    """Hozirgi klientning User obyektini (o'zini) keshdan foydalanib oladi."""
    if not client:
        logger.warning("get_me(): Client obyekti bo'sh.")
        return None

    # session yoki uning filename atributi None bo'lishi mumkinligini hisobga olamiz
    session_identifier = getattr(client.session, 'filename', None)
    if not session_identifier:
        # Agar sessiya fayli bo'lmasa, klientning xotiradagi ID'sidan foydalanamiz
        session_identifier = id(client)
        logger.debug("Sessiya fayli topilmadi, vaqtinchalik identifikator ishlatilmoqda.")

    session_key = f"me:{session_identifier}"
    cached_me = await context.cache.get(session_key)
    if isinstance(cached_me, User):
        logger.debug("O'zim haqimdagi ma'lumotlar keshdan olindi.")
        return cached_me

    me = await retry_telegram_api_call(client.get_me)
    if isinstance(me, User):
        await context.cache.set(session_key, me, ttl=3600)
        logger.debug(f"O'zim haqimdagi ma'lumotlar API'dan olindi va keshga saqlandi: {me.id}")
        return me
    return None



async def get_account_id(context: AppContext, client: TelegramClient) -> Optional[int]:
    """Hozirgi klientning Telegram ID'si orqali ma'lumotlar bazasidagi ichki 'accounts' jadvali ID'sini oladi."""
    if me := await get_me(context, client):
        if me.id:
            account_id = await context.db.fetch_val(
                "SELECT id FROM accounts WHERE telegram_id = ?", (me.id,)
            )
            logger.debug(f"Telegram ID {me.id} uchun ichki account_id topildi: {account_id}")
            return account_id
    return None


async def _get_user_from_reply(context: AppContext, event: Message) -> Tuple[Optional[User], Optional[str]]:
    """Xabarga qilingan javobdan foydalanuvchini topadi."""
    if not event.client:
        logger.warning(f"Javobdan foydalanuvchini olishda xato ({event.id}): event.client mavjud emas.")
        return None, "<b>Ichki xatolik: Client obyekti topilmadi.</b>"
    try:
        reply_message = await retry_telegram_api_call(event.get_reply_message)
        if reply_message and reply_message.from_id:
            user_id = get_peer_id(reply_message.from_id)
            # Bu yerda event.client None emasligiga ishonchimiz komil
            entity = await resolve_entity(context, event.client, user_id)
            if isinstance(entity, User):
                return entity, None
            return None, "<b>Javob berilgan xabar foydalanuvchiga tegishli emas.</b>"
        return None, "<b>Javobdan foydalanuvchini olib bo'lmadi.</b>"
    except Exception as e:
        logger.error(f"Javobdan foydalanuvchini olishda xato ({event.id}): {e}")
        return None, "<b>Xatolik:</b> Javobdan foydalanuvchini olib bo'lmadi."




async def _get_user_from_arg(context: AppContext, client: TelegramClient, text_arg: str) -> Tuple[Optional[User], Optional[str]]:
    """Matnli argumentdan (ID yoki username) foydalanuvchini topadi."""
    try:
        entity = await resolve_entity(context, client, int(text_arg) if text_arg.isdigit() else text_arg.lstrip('@'))
        if isinstance(entity, User):
            return entity, None
        return None, f"<b>Foydalanuvchi topilmadi:</b> <code>{html.escape(text_arg)}</code>"
    except Exception as e:
        logger.error(f"Argumentdan foydalanuvchini topishda kutilmagan xato ({text_arg}): {e}")
        return None, f"<b>Foydalanuvchini topishda xatolik:</b> <code>{html.escape(str(e))}</code>"


async def get_user(context: AppContext, event: Message, text_arg: str = "") -> Tuple[Optional[User], Optional[str]]:
    """Foydalanuvchini aniqlashning asosiy funksiyasi: javobdan yoki argumentdan izlaydi."""
    if not event.client:
        return None, "<b>Ichki xatolik: Client obyekti topilmadi.</b>"
    if text_arg:
        return await _get_user_from_arg(context, event.client, text_arg)
    if event.reply_to_msg_id:
        return await _get_user_from_reply(context, event)
    return None, "<b>Foydalanuvchini aniqlash uchun uning xabariga javob bering yoki ID/username kiriting.</b>"


async def get_chat(context: AppContext, client: TelegramClient, chat: EntityResolvable) -> Optional[Union[Chat, Channel]]:
    """Chat yoki kanalni xavfsiz tarzda oladi."""
    entity = await resolve_entity(context, client, chat)
    return entity if isinstance(entity, (Chat, Channel)) else None


async def get_extended_user_info(context: AppContext, client: TelegramClient, user_id: int) -> Optional[Dict[str, Any]]:
    """Foydalanuvchi haqida kengaytirilgan ma'lumotlarni (bio, rasm ID) oladi."""
    user_entity = await resolve_entity(context, client, user_id)
    if not isinstance(user_entity, User):
        return None

    info = {
        "id": user_entity.id, "first_name": user_entity.first_name,
        "last_name": user_entity.last_name, "username": user_entity.username,
        "phone": user_entity.phone, "access_hash": user_entity.access_hash,
        "status": str(user_entity.status) if user_entity.status else None,
        "is_bot": user_entity.bot, "is_self": user_entity.is_self,
        "lang_code": user_entity.lang_code, "photo_id": None, "bio": None
    }
    try:
        if isinstance(user_entity.photo, UserProfilePhoto):
            info['photo_id'] = user_entity.photo.photo_id
        if user_entity.access_hash is None:
            return info # access_hashsiz to'liq ma'lumot olib bo'lmaydi

        full_user_res = await retry_telegram_api_call(
            client, functions.users.GetFullUserRequest(id=types.InputUser(user_entity.id, user_entity.access_hash))
        )
        if full_user_res and hasattr(full_user_res, 'full_user') and hasattr(full_user_res.full_user, 'about'):
            info['bio'] = full_user_res.full_user.about
    except Exception as e:
        logger.warning(f"Foydalanuvchi {user_id} uchun kengaytirilgan ma'lumotlarni olishda xato: {e}")
    return info


async def get_chat_admins(client: TelegramClient, chat: EntityResolvable) -> List[User]:
    """Chatdagi barcha adminlar ro'yxatini qaytaradi."""
    admins: List[User] = []
    try:
        async for admin in client.iter_participants(chat, filter=ChannelParticipantsAdmins()):
            if not admin.bot:
                admins.append(admin)
    except Exception as e:
        logger.error(f"'{chat}' uchun adminlarni olishda xato: {e}")
    return admins


async def is_user_admin(client: TelegramClient, chat: EntityResolvable, user: EntityResolvable) -> bool:
    """Foydalanuvchi chatda admin yoki egasi ekanligini tekshiradi."""
    try:
        participant = await client.get_permissions(chat, user)
        if participant:
            return participant.is_admin or participant.is_creator
        return False
    except Exception:
        return False


# ===== 3. XABARLAR BILAN ISHLASH =====

async def get_reply_message(event: Message) -> Optional[Message]:
    """Buyruqqa javob (reply) qilingan xabarni qaytaradi."""
    if event.reply_to_msg_id:
        return await event.get_reply_message()
    return None


def get_message_link(message: Message) -> Optional[str]:
    """Xabardan t.me havolasini yaratadi."""
    if isinstance(message.peer_id, PeerChannel):
        return f"https://t.me/c/{message.peer_id.channel_id}/{message.id}"
    return None


async def edit_message(event: Message, new_text: str, **kwargs: Any) -> Optional[Message]:
    """
    Xabarni xavfsiz tahrirlaydi, `MessageNotModified` xatosini chetlab o'tadi
    va barcha kerakli parametrlarni avtomatik o'rnatadi.
    """
    # Agar event yoki client mavjud bo'lmasa, hech narsa qilmaymiz
    if not event or not hasattr(event, "client") or not event.client:
        logger.warning("edit_message: Tahrirlash uchun 'event' yoki 'client' obyekti topilmadi.")
        return None
        
    # Standart parametrlarni o'rnatamiz
    kwargs.setdefault('parse_mode', 'html')
    kwargs.setdefault('link_preview', False)
    
    try:
        # Asosiy tahrirlash amali
        return await retry_telegram_api_call(
            event.edit,
            text=new_text,
            **kwargs
        )
    except MessageNotModifiedError:
        logger.debug("Xabar o'zgarmadi, tahrirlanmadi.")
        return event  # O'zgarmagan bo'lsa ham, eventni qaytaramiz
    except Exception as e:
        logger.error(f"Xabarni (ID: {event.id}) tahrirlashda kutilmagan xato: {e}")
        return None

async def send_and_delete(client: TelegramClient, chat_id: int, text: str, delay: int = 5) -> None:
    """Xabarni yuboradi va belgilangan vaqtdan so'ng o'chiradi."""
    try:
        message = await client.send_message(chat_id, text)
        if not message:
            return

        await asyncio.sleep(delay)
        await retry_telegram_api_call(client.delete_messages, chat_id, [message.id])
    except UserIsBlockedError:
        pass
    except Exception as e:
        logger.error(f"send_and_delete'da xato: {e}")



def get_command_args(event: Message, separator: str = " ") -> List[str]:
    """`.buyruq arg1 arg2` kabi xabardan argumentlarni ajratib oladi."""
    if not event or not event.text:
        return []
    text_parts = event.text.split(separator)
    return text_parts[1:] if len(text_parts) > 1 else []


async def get_last_messages(client: TelegramClient, chat: EntityResolvable, limit: int = 100) -> AsyncGenerator[Message, None]:
    """Chatdagi oxirgi N ta xabarni qaytaruvchi generator."""
    try:
        async for message in client.iter_messages(chat, limit=limit):
            yield message
    except Exception as e:
        logger.error(f"'{chat}' uchun xabarlarni olishda xato: {e}")


# ===== 4. MEDIA FAYLLAR BILAN ISHLASH =====

async def download_file(message: Message, path: str = "./downloads/", progress_callback: Optional[Callable] = None) -> Optional[str]:
    """Xabardagi faylni yuklab oladi va fayl yo'lini qaytaradi."""
    if not hasattr(message, "media") or not message.media:
        return None
    try:
        return await message.download_media(file=path, progress_callback=progress_callback)
    except Exception as e:
        logger.error(f"Faylni yuklashda xato: {e}")
        return None

def get_file_properties(message: Message) -> Optional[dict]:
    """Xabardagi faylning xususiyatlarini (nom, hajm, tur) lug'at ko'rinishida qaytaradi."""
    if not message or not message.file:
        return None
    return {
        "name": message.file.name,
        "size_bytes": message.file.size,
        "mime_type": message.file.mime_type,
        "id": message.file.id,
    }
    
async def iter_files_in_messages(messages: List[Message]) -> AsyncGenerator[Message, None]:
    """Xabarlar ro'yxatidan faqat media fayllarni ajratib oladi."""
    for message in messages:
        if message and message.media:
            yield message


# ===== 5. BOSHQA YORDAMCHI FUNKSIYALAR =====

async def run_in_executor(func: Callable, *args: Any) -> Any:
    """Sinxron (oddiy) funksiyani asinxron kodni bloklamasdan ishga tushiradi."""
    loop = asyncio.get_running_loop()
    return await loop.run_in_executor(None, func, *args)


def get_display_name(entity: Optional[Entity]) -> str:
    """Foydalanuvchi, chat yoki kanalning ko'rsatish uchun nomini qaytaradi."""
    if not entity:
        return "Noma'lum"
    if isinstance(entity, User):
        if entity.first_name and entity.last_name:
            return f"{entity.first_name} {entity.last_name}"
        return html.escape(entity.first_name or entity.username or f"User ID: {entity.id}")
    if title := getattr(entity, 'title', None):
        return html.escape(title)
    return f"Chat ID: {getattr(entity, 'id', 'N/A')}"

    
async def check_rights_and_reply(event: Message, rights: List[str]) -> bool:
    """Botning guruhdagi huquqlarini tekshiradi va yetarli bo'lmasa, xabar yuboradi."""
    chat = await event.get_chat()
    if not chat or not hasattr(chat, "admin_rights") or not chat.admin_rights:
        await edit_message(event, "❌ Men bu guruhda admin emasman yoki huquqlarimni ko'ra olmayapman.")
        return False

    missing_rights = [
        right for right in rights
        if not getattr(chat.admin_rights, right, False)
    ]

    if missing_rights:
        text = "❌ Ushbu amalni bajarish uchun menda quyidagi huquqlar yetishmayapti:\n"
        text += "\n".join(f"- `{right}`" for right in missing_rights)
        await edit_message(event, text)
        return False
    return True
