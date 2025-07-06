import abc
import asyncio
import html
import random
from typing import Dict, Optional, AsyncGenerator, Any, List, Callable, Union, cast, Awaitable

import httpx
import google.generativeai as genai
from google.generativeai.types import (
    GenerationConfig,
    ContentDict,
    PartDict,
    HarmCategory,
    HarmBlockThreshold,
    GenerateContentResponse,
    AsyncGenerateContentResponse,
    Tool
)
from google.api_core import exceptions as google_exceptions
from loguru import logger
from tenacity import retry, stop_after_attempt, wait_exponential, retry_if_exception_type
from bs4 import BeautifulSoup
from googlesearch import search, SearchResult 

# Dependencies uchun type-hinting
from typing import TYPE_CHECKING
if TYPE_CHECKING:
    from core.config_manager import ConfigManager
    from core.cache import CacheManager


class AIError(Exception):
    """AI xizmatlaridagi umumiy xatoliklar uchun asosiy klass."""
    pass

class ProviderError(AIError):
    """Provayderni sozlash yoki ishlatishdagi xatoliklar."""
    pass

class BaseProvider(abc.ABC):
    """Barcha AI provayderlari uchun asosiy abstrakt klass."""

    @abc.abstractmethod
    async def generate_text(self, model: str, prompt: str, system_prompt: Optional[str] = None) -> Dict[str, Any]:
        """Matn yaratadi."""
        pass
    
    @abc.abstractmethod
    async def generate_text_stream(self, model: str, prompt: str, system_prompt: Optional[str] = None) -> AsyncGenerator[str, None]:
        """Matnni stream tarzida yaratadi."""
        yield ""

    @abc.abstractmethod
    async def generate_from_image(self, model: str, prompt: str, image_bytes: bytes) -> Dict[str, Any]:
        """Rasmga asoslanib matn yaratadi."""
        pass
    
    @abc.abstractmethod
    async def start_chat(self, chat_id: str, persona: Optional[str] = None):
        """Yangi suhbat seansini boshlaydi."""
        pass

    @abc.abstractmethod
    async def generate_chat_response(self, chat_id: str, prompt: str) -> Dict[str, Any]:
        """Suhbatda javob yaratadi."""
        pass
    
    @abc.abstractmethod
    async def transcribe_audio(self, audio_bytes: bytes) -> Dict[str, Any]:
        """Audio faylni transkripsiya qiladi."""
        pass


class GeminiProvider(BaseProvider):

    def __init__(self, api_key: str, config_manager: 'ConfigManager', cache_manager: 'CacheManager'):
        try:
            cast(Any, genai).configure(api_key=api_key) 
            self._models: Dict[str, genai.GenerativeModel] = {}  # type: ignore
            self._config = config_manager
            self._cache = cache_manager
            logger.success("✅ Google Gemini Provider muvaffaqiyatli sozlandi.")
        except Exception as e:
            raise ProviderError(f"Gemini Providerni sozlashda xatolik: {e}") from e

    def _get_model(self, model_name: str, system_prompt: Optional[str] = None) -> genai.GenerativeModel: # type: ignore
        """Keshdan yoki yangi Gemini modelini yaratadi."""
        key = f"{model_name}_{system_prompt or 'default'}"
        if key not in self._models:
            safety_settings = {
                HarmCategory.HARM_CATEGORY_HARASSMENT: HarmBlockThreshold.BLOCK_ONLY_HIGH,
                HarmCategory.HARM_CATEGORY_HATE_SPEECH: HarmBlockThreshold.BLOCK_ONLY_HIGH,
                HarmCategory.HARM_CATEGORY_SEXUALLY_EXPLICIT: HarmBlockThreshold.BLOCK_ONLY_HIGH,
                HarmCategory.HARM_CATEGORY_DANGEROUS_CONTENT: HarmBlockThreshold.BLOCK_ONLY_HIGH
            }
            model_class = cast(Any, genai).GenerativeModel 

            if system_prompt and model_name.startswith("gemini-1.5"):
                 self._models[key] = model_class(model_name, system_instruction=system_prompt, safety_settings=safety_settings)
            else:
                 self._models[key] = model_class(model_name, safety_settings=safety_settings)
        return self._models[key]

    @retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1, min=2, max=10), retry=retry_if_exception_type(google_exceptions.ResourceExhausted))
    async def _generate_content(self, model_name: str, contents: List[Union[str, PartDict]], system_prompt: Optional[str] = None) -> Dict[str, Any]:
        """Umumiy kontent generatsiya qilish logikasi."""
        model = self._get_model(model_name, system_prompt)
        
        response: AsyncGenerateContentResponse = await model.generate_content_async(contents) 
        
        generated_text = ""
        if response.parts:
            for part in response.parts:
                if hasattr(part, 'text') and part.text is not None:
                    generated_text += part.text
        
        tokens = (await model.count_tokens_async(contents)).total_tokens
        return {"text": generated_text, "tokens": tokens}

    async def generate_text(self, model: str, prompt: str, system_prompt: Optional[str] = None) -> Dict[str, Any]:
        """Matnni generatsiya qiladi."""
        return await self._generate_content(model, [prompt], system_prompt=system_prompt)

    async def generate_text_stream(self, model: str, prompt: str, system_prompt: Optional[str] = None) -> AsyncGenerator[str, None]:
        """Matnni stream tarzida generatsiya qiladi."""
        model_instance = self._get_model(model, system_prompt)
        async for chunk in await model_instance.generate_content_async(prompt, stream=True):
            if chunk.text: 
                yield chunk.text

    async def generate_from_image(self, model: str, prompt: str, image_bytes: bytes) -> Dict[str, Any]:
        """Rasmga asoslanib matn generatsiya qiladi."""
        image_part: PartDict = cast(PartDict, {"inline_data": {"mime_type": "image/jpeg", "data": image_bytes}})
        return await self._generate_content(model, [prompt, image_part]) 

    async def start_chat(self, chat_id: str, persona: Optional[str] = None):
        """Yangi suhbat seansini boshlaydi va keshga saqlaydi."""
        system_instruction_text = persona or self._config.get("AI_SYSTEM_PROMPT", "Siz foydali yordamchisiz.") 
        
        chat_ttl = self._config.get("AI_CHAT_TTL_SECONDS")
        await self._cache.set(chat_id, [], namespace="ai_chat_sessions", ttl=chat_ttl)
        logger.debug(f"Chat ID '{chat_id}' uchun suhbat persona bilan yangilandi. TTL: {chat_ttl}s")

    async def generate_chat_response(self, chat_id: str, prompt: str) -> Dict[str, Any]:
        """Suhbatda javob generatsiya qiladi."""
        model_name = self._config.get("AI_DEFAULT_MODEL", "gemini-1.5-flash-latest")
        chat_ttl = self._config.get("AI_CHAT_TTL_SECONDS")

        history: Optional[List[ContentDict]] = await self._cache.get(chat_id, namespace="ai_chat_sessions")
        if history is None: 
            return {"text": "Suhbat muddati tugagan. Iltimos, yangi suhbat boshlang.", "tokens": 0}

        model_instance = self._get_model(model_name)
        chat = model_instance.start_chat(history=history)
        
        response: AsyncGenerateContentResponse = await chat.send_message_async(prompt) 
        
        await self._cache.set(chat_id, chat.history, namespace="ai_chat_sessions", ttl=chat_ttl)
        tokens = (await model_instance.count_tokens_async(chat.history)).total_tokens 
        
        generated_text = ""
        if response.parts:
            for part in response.parts:
                if hasattr(part, 'text') and part.text is not None:
                    generated_text += part.text

        return {"text": generated_text, "tokens": tokens}

    async def transcribe_audio(self, audio_bytes: bytes) -> Dict[str, Any]:
        """
        Audio faylni transkripsiya qiladi.
        Gemini API'sida to'g'ridan-to'g'ri audio transkripsiya funksiyasi yo'q.
        Shuning uchun Yandex SpeechKit (yoki boshqa provayder) orqali amalga oshiriladi.
        """
        logger.info("Yandex SpeechKit orqali audio transkripsiya boshlanmoqda...")
        yandex_api_key = self._config.get("YANDEX_API_KEY")
        yandex_folder_id = self._config.get("YANDEX_FOLDER_ID")

        if not yandex_api_key or not yandex_folder_id:
            logger.error("Yandex SpeechKit uchun API kaliti yoki Folder ID sozlanmagan.")
            return {"text": "Audio transkripsiya xizmati sozlanmagan (Yandex API kaliti/Folder ID yetishmayapti).", "tokens": 0}

        try:
            url = "https://stt.api.cloud.yandex.net/speech/v1/stt:recognize"
            headers = {
                "Authorization": f"Api-Key {yandex_api_key}"
            }
            params = {
                "folderId": yandex_folder_id,
                "lang": "uz-UZ",  # Yoki boshqa tillar, masalan 'ru-RU', 'en-EN'
                "format": "oggopus" # Agar boshqa formatlar bo'lsa, uni ham qo'shish kerak (misol: "lpcm")
            }

            async with httpx.AsyncClient(timeout=30) as client:
                response = await client.post(url, headers=headers, params=params, content=audio_bytes)
                response.raise_for_status()
                
                result = response.json()
                if "result" in result:
                    logger.success("✅ Audio muvaffaqiyatli transkripsiya qilindi.")
                    return {"text": result["result"], "tokens": len(result["result"].split())} # Tokenlarni so'zlar soni bilan taxminan hisoblaymiz
                elif "error_code" in result:
                    logger.error(f"Yandex SpeechKit xatosi: {result.get('error_code')}, {result.get('message')}")
                    return {"text": f"Audio transkripsiya xatosi: {result.get('message', 'Noma`lum xato')}", "tokens": 0}
                else:
                    logger.warning(f"Yandex SpeechKit dan kutilmagan javob: {result}")
                    return {"text": "Audio transkripsiya xatosi: Kutilmagan javob.", "tokens": 0}

        except httpx.HTTPStatusError as e:
            logger.error(f"Yandex SpeechKit HTTP xatosi: {e.response.status_code} - {e.response.text}", exc_info=True)
            return {"text": f"Audio transkripsiya HTTP xatosi: {e.response.status_code}", "tokens": 0}
        except Exception as e:
            logger.error(f"Audio transkripsiya jarayonida kutilmagan xato: {e}", exc_info=True)
            return {"text": f"Audio transkripsiya xatosi: {str(e)}", "tokens": 0}

class AIService:
    """Barcha AI provayderlarini boshqaradigan va ularga interfeysni ta'minlaydigan markaziy xizmat."""
    def __init__(self, config_manager: 'ConfigManager', cache_manager: 'CacheManager'):
        self._providers: Dict[str, BaseProvider] = {}
        self.is_configured = False
        self._config = config_manager
        self._cache = cache_manager

    async def configure(self):
        """AI xizmatlarini sozlaydi va provayderlarni yuklaydi."""
        if self.is_configured:
            logger.debug("AI xizmati allaqachon sozlangan, qayta sozlash o'tkazib yuborildi.")
            return
            
        logger.info("AI Servis sozlanmoqda...")
        gemini_key: Optional[str] = self._config.get("GEMINI_API_KEY") 
        yandex_api_key: Optional[str] = self._config.get("YANDEX_API_KEY") # Yandex kalitini olish
        yandex_folder_id: Optional[str] = self._config.get("YANDEX_FOLDER_ID") # Yandex folder ID olish

        # Gemini provayderini sozlash
        if not gemini_key:
            logger.warning("[AI_DEBUG] .env faylidan GEMINI_API_KEY topilmadi yoki bo'sh.")
        else:
            logger.warning(f"[AI_DEBUG] Gemini'ni sozlash uchun ishlatilayotgan kalit: '{gemini_key[:5]}...{gemini_key[-4:]}'")

        if gemini_key:
            try:
                # GeminiProvider endi faqat Gemini ga tegishli funksiyalarni boshqaradi
                self._providers['gemini'] = GeminiProvider(api_key=gemini_key, config_manager=self._config, cache_manager=self._cache)
                self.is_configured = True
            except ProviderError as e:
                logger.error(f"Gemini provayderini sozlashda xato: {e}", exc_info=True)
        
        # Yandex SpeechKit provayderini sozlash (agar kerak bo'lsa, alohida provayder klassi sifatida)
        # Hozircha men transcribe_audio funksiyasini to'g'ridan-to'g'ri AIService.transcribe_audio ichida
        # Yandex logikasini chaqiradigan qilib o'zgartirdim. Agar siz alohida YandexProvider klassini xohlasangiz,
        # u holda uni BaseProvider'dan meros olib, bu yerda init qilasiz.
        # Misol uchun, AI xizmatlarida provayderlar xaritasini kengaytiramiz:
        if yandex_api_key and yandex_folder_id:
            try:
                # Transkripsiya uchun YandexProvider yaratish.
                # Agar sizda Yandex uchun alohida BaseProvider klassi bo'lmasa,
                # u holda AIService ichida transcribe_audio metodini to'g'ridan-to'g'ri
                # API chaqiruvlari bilan to'ldirish kerak.
                # Men hozircha AIService ning o'zida _config dan foydalanib to'g'ridan-to'g'ri chaqiradigan qilib qo'ydim.
                # Agar kelajakda Yandex ham matn generatsiyasini qo'llasa, alohida provayder maqsadga muvofiq bo'ladi.
                logger.info("Yandex SpeechKit sozlamalari topildi.")
                # self._providers['yandex_speech'] = YandexSpeechProvider(api_key=yandex_api_key, folder_id=yandex_folder_id, config_manager=self._config, cache_manager=self._cache)
                # self.is_configured = True # Agar bu yerda yana bir provayder sozlansa, flagni true qilish
            except Exception as e:
                logger.error(f"Yandex SpeechKit sozlashda xato: {e}", exc_info=True)
        else:
            logger.warning("Yandex SpeechKit uchun API kaliti yoki Folder ID topilmadi. Audio transkripsiya cheklangan bo'lishi mumkin.")

        if not self._providers and not (yandex_api_key and yandex_folder_id): # Agar hech qanday provayder sozlanmagan bo'lsa
            logger.warning("Hech qanday AI provayder uchun API kaliti topilmadi yoki sozlanmadi.")


    def _get_provider(self, provider_name: str = 'gemini') -> BaseProvider:
        """Berilgan nom bo'yicha AI provayderini qaytaradi."""
        # AI xizmati umumiy konfiguratsiya qilinganligini tekshiramiz
        # Agar faqat Yandex STT ishlatilsa, self.is_configured False bo'lishi mumkin,
        # shuning uchun bu tekshiruvni o'zgartiramiz yoki umumiyroq qilamiz.
        # Hozircha faqat Gemini uchun is_configured ni ishlatamiz.
        
        provider = self._providers.get(provider_name)
        if provider is None:
            raise ProviderError(f"'{provider_name}' nomli provayder topilmadi. Mavjud provayderlar: {list(self._providers.keys())}")
        return provider

    async def _handle_request(self, handler: Callable[..., Awaitable[Dict[str, Any]]], *args: Any, **kwargs: Any) -> Dict[str, Any]:
        """AI so'rovlarini boshqaradi va xatolarni qayta ishlaydi."""
        try:
            return await handler(*args, **kwargs)
        except Exception as e:
            logger.error(f"AI so'rovida xatolik: {e!r}", exc_info=True)
            return {"text": f"<b>AI Xatoligi:</b> <code>{html.escape(str(e))}</code>", "tokens": 0}

    async def _fetch_url_content(self, url: str) -> str:
        """Berilgan URL dan matnli kontentni ajratib oladi."""
        try:
            async with httpx.AsyncClient(timeout=10, follow_redirects=True) as client:
                response = await client.get(url, headers={'User-Agent': 'Mozilla/5.0 Userbot/1.0'})
                response.raise_for_status()
                
                soup = BeautifulSoup(response.text, "html.parser")
                for tag in soup(['script', 'style', 'nav', 'footer', 'header', 'aside', 'form', 'button', 'img', 'video', 'audio', 'iframe']):
                    tag.decompose()
                return ' '.join(soup.stripped_strings)
        except httpx.HTTPStatusError as e:
            logger.warning(f"URL'dan kontent olishda HTTP xatosi ({url}): {e.response.status_code}")
            return ""
        except Exception as e:
            logger.warning(f"URL'dan kontent olishda kutilmagan xatolik ({url}): {e!r}")
            return ""

    async def generate_with_rag(self, prompt: str) -> Dict[str, Any]:
        """Internetdan ma'lumot qidirib, topilgan ma'lumotlar asosida javob beradi."""
        logger.info(f"Internetdan qidirilmoqda: '{prompt}'")
        context = ""
        try:
            search_results: List[Union[str, SearchResult]] = await asyncio.to_thread(
                lambda: list(search(prompt, num_results=self._config.get("RAG_SEARCH_RESULTS_COUNT"), lang=self._config.get("RAG_SEARCH_LANG"))) 
            )
            
            valid_urls = [
                url for url in search_results 
                if isinstance(url, str) and url.startswith('http') and len(url) < 2048 
            ]

            if not valid_urls:
                context = "Internetdan ishonchli manba topilmadi."
                logger.warning(f"'{prompt}' uchun yaroqli URL topilmadi. Qidiruv natijalari: {search_results}")
            else:
                logger.debug(f"Topilgan yaroqli URLlar: {valid_urls[:self._config.get('RAG_FETCH_MAX_URLS')]}") 
                tasks_to_fetch = [self._fetch_url_content(url) for url in valid_urls[:self._config.get('RAG_FETCH_MAX_URLS')]]
                contents = await asyncio.gather(*tasks_to_fetch)
                
                non_empty_contents = [c for c in contents if c and c.strip()]
                if not non_empty_contents:
                    context = "Topilgan havolalardan matn ajratib bo'lmadi."
                else:
                    full_context = "\n\n---\n\n".join(non_empty_contents)
                    context = full_context[:self._config.get('RAG_MAX_CONTEXT_LENGTH')] 
                    if len(full_context) > self._config.get('RAG_MAX_CONTEXT_LENGTH'):
                        context += "..." 

        except Exception as e:
            logger.error(f"Internetdan qidirishda kutilmagan xatolik: {e!r}", exc_info=True)
            context = f"Internetdan qidirishda xatolik yuz berdi: {html.escape(str(e))}"
        
        rag_prompt = (
            f"Ushbu internetdan olingan ma'lumotlarga asoslanib, quyidagi savolga batafsil va aniq javob ber:\n\n"
            f"MA'LUMOTLAR:\n---\n{context}\n---\n\n"
            f"SAVOL: {prompt}"
        )
        # Generate with Gemini, as RAG is a text generation task
        return await self.generate_text(
            rag_prompt,
            system_prompt="Sen qidiruv natijalariga asoslangan holda javob beruvchi ekspert yordamchisan."
        )

    async def generate_text(self, prompt: str, system_prompt: Optional[str] = None) -> Dict[str, Any]:
        """Matnni generatsiya qiladi."""
        model = self._config.get("AI_DEFAULT_MODEL", "gemini-1.5-flash-latest")
        # Bu yerda faqat 'gemini' provayderini chaqiramiz
        return await self._handle_request(self._get_provider('gemini').generate_text, model, prompt, system_prompt=system_prompt)

    async def generate_from_document(self, prompt: str, doc_text: str) -> Dict[str, Any]:
        """Hujjat matniga asoslanib javob beradi."""
        doc_prompt = f"Ushbu hujjat matniga asoslanib savolga javob ber. Hujjatning qisqacha mazmuni:\n\n{doc_text[:self._config.get('RAG_MAX_CONTEXT_LENGTH')]}\n\nSavol: {prompt}"
        # Bu yerda ham 'gemini' provayderini chaqiramiz
        return await self.generate_text(doc_prompt, system_prompt="Sen hujjatlar bo'yicha ekspert tahlilchisan.")

    async def generate_from_image(self, prompt: str, image_bytes: bytes) -> Dict[str, Any]:
        """Rasmga asoslanib javob beradi."""
        model = self._config.get("AI_VISION_MODEL", "gemini-1.5-flash-latest")
        # Bu yerda ham 'gemini' provayderini chaqiramiz
        return await self._handle_request(self._get_provider('gemini').generate_from_image, model, prompt, image_bytes)
        
    async def start_chat(self, chat_id: str, persona: Optional[str] = None):
        """Yangi suhbat seansini boshlaydi."""
        # Bu yerda ham 'gemini' provayderini chaqiramiz
        await self._get_provider('gemini').start_chat(chat_id, persona)

    async def generate_chat_response(self, chat_id: str, prompt: str) -> Dict[str, Any]:
        """Suhbatda javob generatsiya qiladi."""
        # Bu yerda ham 'gemini' provayderini chaqiramiz
        return await self._handle_request(self._get_provider('gemini').generate_chat_response, chat_id, prompt)

    async def transcribe_audio(self, audio_bytes: bytes) -> Dict[str, Any]:
        """Audio faylni transkripsiya qiladi."""
        # Audio transkripsiya uchun to'g'ridan-to'g'ri Yandex SpeechKit chaqiruvini bajaradi
        # (Yoki sizning tanlagan boshqa provayderingiz)
        return await self._handle_request(self._providers['gemini'].transcribe_audio, audio_bytes)
        # Yuqoridagi qatorni o'zgartirdim: AIService ichida transcribe_audio chaqirilganda,
        # u endi GeminiProvider.transcribe_audio ga boradi,
        # va u o'z navbatida Yandex API'sini chaqiradi.
        # Bu AI Servisning dizayniga ko'ra to'g'ri bo'ladi,
        # chunki AIService turli provayderlarni boshqaradi.
        # Lekin, agar siz har bir provayderni mustaqil saqlashni xohlasangiz,
        # u holda Yandex uchun alohida BaseProvider merosxo'ri yaratishingiz kerak.
        # Hozirgi tuzatishda, `GeminiProvider.transcribe_audio` endi Yandex API chaqiruvini o'z ichiga oladi.


# GLOBAL obyekt bu yerda yaratilmaydi.
# ai_service = AIService()
