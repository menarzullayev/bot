# bot/plugins/user/tts.py
"""
Matnni ovozga o'girish (Text-to-Speech) plagini.
Microsoft Edge va Yandex Cloud provayderlarini qo'llab-quvvatlaydi.
"""

import asyncio
import hashlib
import html
import io
import shlex
from pathlib import Path
from typing import Any, Dict, Optional

try:
    import httpx
except ImportError:
    httpx = None

try:
    import edge_tts
    EDGE_TTS_AVAILABLE = True
except ImportError:
    edge_tts = None
    EDGE_TTS_AVAILABLE = False

from loguru import logger
from telethon.tl.custom import Message
from telethon.tl.types import SendMessageRecordAudioAction

from core.app_context import AppContext
from bot.decorators import userbot_cmd
from bot.lib.ui import PaginationHelper, format_error, format_success
from bot.lib.utils import RaiseArgumentParser
from bot.lib.telegram import get_account_id

# --- Konfiguratsiya va Yordamchi o'zgaruvchilar ---
CACHE_DIR = Path("cache/tts")
CACHE_DIR.mkdir(parents=True, exist_ok=True)


async def _get_cache_path(provider: str, text: str, options: Dict[str, Any]) -> Path:
    """TTS audio uchun unikal kesh fayl yo'lini yaratadi."""
    key_string = f"provider:{provider}|text:{text}|" + "|".join(f"{k}:{v}" for k, v in sorted(options.items()))
    filename = hashlib.md5(key_string.encode()).hexdigest() + ".ogg"
    return CACHE_DIR / filename

async def _synthesize(context: AppContext, provider: str, text: str, **kwargs: Any) -> Optional[bytes]:
    """Tanlangan provayder orqali ovozni sintez qiladi."""
    try:
        if provider == 'edge':
            if not edge_tts: raise ValueError("`edge-tts` kutubxonasi o'rnatilmagan.")
            voice = str(kwargs.get('voice', "uz-UZ-SardorNeural"))
            rate = str(kwargs.get('rate', "+0%")) if kwargs.get('rate') else "+0%"
            pitch = str(kwargs.get('pitch', "+0Hz")) if kwargs.get('pitch') else "+0Hz"
            communicate = edge_tts.Communicate(text, voice, rate=rate, pitch=pitch)
            
            buffer = io.BytesIO()
            async for chunk in communicate.stream():
                if chunk["type"] == "audio" and (data := chunk.get("data")):
                    buffer.write(data)
            buffer.seek(0)
            return buffer.getvalue()

        elif provider == 'yandex':
            if not httpx: raise ValueError("`httpx` kutubxonasi o'rnatilmagan.")
            api_key = context.config.get("YANDEX_API_KEY")
            folder_id = context.config.get("YANDEX_FOLDER_ID")
            if not api_key or not folder_id:
                raise ValueError("Yandex API Key yoki Folder ID sozlanmagan.")
            
            params = {'folderId': folder_id, 'text': text, 'format': 'oggopus', **kwargs}
            
            async with httpx.AsyncClient() as client:
                resp = await client.post(
                    'https://tts.api.cloud.yandex.net/speech/v1/tts:synthesize',
                    headers={'Authorization': f'Api-Key {api_key}'}, data=params, timeout=60.0
                )
                resp.raise_for_status()
                return resp.content
    except Exception as e:
        logger.error(f"{provider.capitalize()} TTS sintezida xato: {e}")
    return None

async def _get_user_defaults(context: AppContext, account_id: int) -> Dict[str, str]:
    """Foydalanuvchi uchun standart TTS sozlamalarini oladi."""
    # `state` dan foydalanish bazaga doimiy murojaatdan tezroq
    provider = context.state.get(f"tts_default_provider_{account_id}", "yandex")
    voice = context.state.get(f"tts_default_voice_{account_id}", "nigora" if provider == 'yandex' else "uz-UZ-SardorNeural")
    return {"provider": provider, "voice": voice}

async def _process_tts_request(context: AppContext, event: Message, provider: str, text: str, tts_options: dict, live: bool):
    """TTS so'rovini qayta ishlaydi: ovozni sintez qiladi, keshlaydi va yuboradi."""
    client = event.client
    if not client: return

    action = SendMessageRecordAudioAction() if live else "typing"
    try:
        async with client.action(event.chat_id, action):
            cache_path = await _get_cache_path(provider, text, tts_options)
            if cache_path.exists():
                logger.info(f"Audio keshdan topildi: {cache_path.name}")
                audio_content = await asyncio.to_thread(cache_path.read_bytes)
            else:
                audio_content = await _synthesize(context, provider, text, **tts_options)
                if not audio_content:
                    raise ValueError(f"{provider.capitalize()} provayderi ovoz yarata olmadi.")
                await asyncio.to_thread(cache_path.write_bytes, audio_content)
                logger.success(f"Audio yaratildi va keshlandi: {cache_path.name}")

            await client.send_file(event.chat_id, file=audio_content, reply_to=event.reply_to_msg_id, voice_note=True)
    except Exception as e:
        logger.exception("TTS handlerda umumiy xatolik.")
        await event.respond(format_error(f"TTS xatoligi: {e}"), parse_mode='html')

# --- Asosiy TTS Buyrug'i ---

@userbot_cmd(command="tts", description="Matnni ovozga o'giradi (Edge yoki Yandex).")
async def unified_tts_handler(event: Message, context: AppContext):
    """
    .tts Salom!
    .tts -p edge -v uz-UZ-MadinaNeural Bu Madinaning ovozi.
    .tts -p yandex -v alena Привет, мир!
    .tts -l (jonli yozish effekti bilan)
    """
    if not (event.client and event.text): return
    
    account_id = await get_account_id(context, event.client)
    if not account_id: return

    args_str = event.text.split(maxsplit=1)[1] if len(event.text.split()) > 1 else ""
    user_defaults = await _get_user_defaults(context, account_id)

    parser = RaiseArgumentParser(prog=".tts", add_help=False)
    parser.set_defaults(**user_defaults)
    parser.add_argument('-p', '--provider', choices=['yandex', 'edge'])
    parser.add_argument('-v', '--voice')
    parser.add_argument('-e', '--emotion')
    parser.add_argument('-s', '--speed')
    parser.add_argument('-r', '--rate')
    parser.add_argument('--pitch')
    parser.add_argument('-l', '--live', action='store_true')
    parser.add_argument('text', nargs='*')

    try:
        args = parser.parse_args(shlex.split(args_str))
    except (ValueError, SystemExit) as e:
        return await event.edit(format_error(f"Argument xatosi: {e}"), parse_mode='html')

    text_to_speak = " ".join(args.text).strip()
    if not text_to_speak:
        if replied := await event.get_reply_message():
            text_to_speak = replied.text
    if not text_to_speak:
        return await event.edit(format_error("Matn kiriting yoki matnli xabarga javob bering."), parse_mode='html')

    provider = args.provider
    if provider == 'edge' and not EDGE_TTS_AVAILABLE:
        return await event.edit(format_error("`edge-tts` kutubxonasi o'rnatilmagan."), parse_mode='html')

    tts_options = {}
    if provider == 'edge':
        tts_options.update({'voice': args.voice, 'rate': args.rate, 'pitch': args.pitch})
    else: # yandex
        tts_options.update({'voice': args.voice, 'emotion': args.emotion, 'speed': args.speed})
    tts_options = {k: v for k, v in tts_options.items() if v is not None}

    await event.delete()
    await _process_tts_request(context, event, provider, text_to_speak, tts_options, live=args.live)

# --- Qo'shimcha Buyruqlar ---

@userbot_cmd(command="tts-voices", description="Mavjud ovozlar ro'yxatini ko'rsatadi.")
async def list_voices_handler(event: Message, context: AppContext):
    """
    .tts-voices edge
    .tts-voices yandex
    """
    if not event.text: return
    provider = event.text.split(maxsplit=1)[1].lower() if len(event.text.split()) > 1 else 'edge'
    
    await event.edit(f"<i>🔄 {provider} uchun ovozlar ro'yxati olinmoqda...</i>", parse_mode='html')
    
    lines = []
    if provider == 'edge':
        # YECHIM: `EDGE_TTS_AVAILABLE` va `edge_tts` mavjudligini birgalikda tekshirish
        if not EDGE_TTS_AVAILABLE or not edge_tts:
            return await event.edit(format_error("`edge-tts` kutubxonasi o'rnatilmagan."), parse_mode='html')
        
        voices = await edge_tts.VoicesManager.create()
        for voice in sorted(voices.voices, key=lambda v: v['FriendlyName']):
            lines.append(f"<b>{voice['FriendlyName']}</b>: <code>{voice['ShortName']}</code> ({voice['Gender']})")

    elif provider == 'yandex':
        yandex_voices = {"uz": ["nigora", "madina"], "ru": ["alena", "filipp", "ermil", "jane", "omazh", "zahar"]}
        for lang, voice_list in yandex_voices.items():
            lines.append(f"\n<b>{lang.upper()} Ovozlar:</b>")
            lines.extend([f"• <code>{v}</code>" for v in voice_list])
    else:
        return await event.edit(format_error("Noto'g'ri provayder. `yandex` yoki `edge` tanlang."), parse_mode='html')

    paginator = PaginationHelper(context=context, items=lines, title=f"{provider.title()} Ovozlari Ro'yxati", origin_event=event)
    await paginator.start()



@userbot_cmd(command="set-tts-defaults", description="Siz uchun standart TTS sozlamalarini o'rnatadi.")
async def set_defaults_handler(event: Message, context: AppContext):
    """ .set-tts-defaults -p edge -v uz-UZ-MadinaNeural """
    if not (event.text and event.client): return
    account_id = await get_account_id(context, event.client)
    if not account_id: return

    args_str = event.text.split(maxsplit=1)[1] if len(event.text.split()) > 1 else ""
    parser = RaiseArgumentParser(prog=".set-tts-defaults", add_help=False)
    parser.add_argument('-p', '--provider', choices=['yandex', 'edge'])
    parser.add_argument('-v', '--voice')
    
    try:
        args = parser.parse_args(shlex.split(args_str))
        settings_to_save = {k: v for k, v in vars(args).items() if v is not None}
        if not settings_to_save:
            return await event.edit(format_error("O'rnatish uchun kamida bitta parametr kiriting (masalan, `-v nigora`)."), parse_mode='html')

        for key, value in settings_to_save.items():
            await context.state.set(f"tts_default_{key}_{account_id}", value, persistent=True)
        
        await event.edit(format_success("Standart sozlamalar muvaffaqiyatli saqlandi!"), parse_mode='html')
    except (ValueError, SystemExit) as e:
        await event.edit(format_error(f"Argument xatosi: {e}"), parse_mode='html')
