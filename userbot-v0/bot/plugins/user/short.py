# bot/plugins/user/shorten.py
"""
URL manzillarni turli servislar yordamida qisqartirish uchun plagin.
(TinyURL API yangilandi va to'liq modernizatsiya qilindi).
"""
import html
from abc import ABC, abstractmethod
from typing import Dict, Any


try:
    import httpx
except ImportError:
    httpx = None

from loguru import logger
from telethon.tl.custom import Message

from core.app_context import AppContext
from bot.decorators import userbot_cmd
from bot.lib.ui import format_error, format_success, code

# --- Provayderlar Mantig'i ---
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    import httpx
    
    
class ShortenerProvider(ABC):
    """Barcha qisqartiruvchi servislar uchun asosiy klass."""
    key_name: str
    friendly_name: str

    @abstractmethod
    async def shorten(self, url: str, client: Any) -> str:
        """Berilgan URL'ni qisqartiradi va natijani qaytaradi."""
        pass


class VGdProvider(ShortenerProvider):
    """v.gd servisi uchun provayder. is.gd ning HTTPS versiyasi, barqarorroq ishlaydi."""
    key_name = "v.gd"
    friendly_name = "v.gd"

    async def shorten(self, url: str, client: Any) -> str:
        if not httpx: raise ModuleNotFoundError("`httpx` kutubxonasi o'rnatilmagan.")
        
        params = {"format": "simple", "url": url}
        response = await client.get("https://v.gd/create.php", params=params)
        response.raise_for_status()
        short_url = response.text.strip()
        if not short_url.startswith("http"):
            raise ValueError(f"{self.friendly_name} servisi xato qaytardi: {short_url}")
        return short_url


class TinyUrlProvider(ShortenerProvider):
    key_name = "tinyurl"
    friendly_name = "TinyURL.com"

    async def shorten(self, url: str, client: Any) -> str:
        if not httpx: raise ModuleNotFoundError("`httpx` kutubxonasi o'rnatilmagan.")
        
        api_url = "https://api.tinyurl.com/create"
        payload = {"url": url}
        headers = {"Content-Type": "application/json"}

        response = await client.post(api_url, json=payload, headers=headers)
        response.raise_for_status()
        
        data = response.json()
        if data.get("code") == 0 and data.get("data", {}).get("tiny_url"):
            return data["data"]["tiny_url"]
        else:
            errors = data.get('errors', ['Noma\'lum xato'])
            raise ValueError(f"{self.friendly_name} servisi xato qaytardi: {', '.join(errors)}")






PROVIDERS: Dict[str, ShortenerProvider] = {p.key_name: p() for p in [VGdProvider, TinyUrlProvider]}
DEFAULT_PROVIDER = "v.gd"

# --- Asosiy Boshqaruvchi Buyruq ---

@userbot_cmd(command="short", description="URL manzilni qisqartiradi yoki provayderni sozlaydi.")
async def shorten_manager(event: Message, context: AppContext):
    """
    .short https://google.com
    .short provider              # Mavjud provayderlar ro'yxati
    .short provider tinyurl      # Standart provayderni o'zgartirish
    """
    if not httpx:
        return await event.edit(format_error("`httpx` kutubxonasi o'rnatilmagan."), parse_mode='html')
    if not event.text: return

    args_str = event.text.split(maxsplit=1)[1] if len(event.text.split()) > 1 else ""
    
    if args_str.lower().startswith("provider"):
        sub_args = args_str.split(maxsplit=1)
        if len(sub_args) > 1:
            provider_name = sub_args[1].strip().lower()
            if provider_name not in PROVIDERS:
                return await event.edit(format_error(f"Noto'g'ri provayder. Mavjudlari: {', '.join(PROVIDERS.keys())}"), parse_mode='html')
            await context.config.set("SHORTENER_DEFAULT_PROVIDER", provider_name)
            return await event.edit(format_success(f"Standart provayder <b>{provider_name}</b>'ga o'zgartirildi."), parse_mode='html')
        else:
            current_provider = context.config.get("SHORTENER_DEFAULT_PROVIDER", DEFAULT_PROVIDER)
            providers_list = "\n".join(
                f"• <code>{key}</code> - {p.friendly_name}{' (joriy)' if key == current_provider else ''}"
                for key, p in PROVIDERS.items()
            )
            response = (f"<b>⚙️ URL Qisqartiruvchi Sozlamalari</b>\n\n"
                        f"<b>Mavjud provayderlar:</b>\n{providers_list}\n\n"
                        f"<i>O'zgartirish uchun: <code>.short provider &lt;nomi&gt;</code></i>")
            return await event.edit(response, parse_mode='html')
    
    url_to_shorten = args_str
    if not url_to_shorten:
        replied = await event.get_reply_message()
        if replied and replied.text:
            url_to_shorten = replied.text.strip()

    if not url_to_shorten:
        return await event.edit(format_error("URL kiriting yoki URL bor xabarga javob bering."), parse_mode='html')

    if not url_to_shorten.startswith(('http://', 'https://')):
        url_to_shorten = 'https://' + url_to_shorten

    await event.edit(f"<i>🔄 <code>{html.escape(url_to_shorten)}</code> manzili qisqartirilmoqda...</i>", parse_mode='html')
    
    try:
        provider_key = context.config.get("SHORTENER_DEFAULT_PROVIDER", DEFAULT_PROVIDER)
        provider = PROVIDERS.get(provider_key, PROVIDERS[DEFAULT_PROVIDER])
        
        async with httpx.AsyncClient(timeout=15.0) as client:
            short_url = await provider.shorten(url_to_shorten, client)
        
        response = (f"<b>✅ Muvaffaqiyatli qisqartirildi!</b>\n\n"
                    f"<b>Original:</b> <a href=\"{html.escape(url_to_shorten)}\">Havola</a>\n"
                    f"<b>Qisqa:</b> <code>{short_url}</code>\n"
                    f"<b>Servis:</b> {provider.friendly_name}")
        await event.edit(response, link_preview=False, parse_mode='html')
    except Exception as e:
        logger.exception("URL qisqartirishda xato")
        await event.edit(format_error(f"Xatolik: {e}"), parse_mode='html')
