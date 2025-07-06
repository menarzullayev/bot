import pytest
import asyncio
from typing import AsyncGenerator
from unittest.mock import MagicMock, AsyncMock, patch

import pytest_asyncio

# Test qilinadigan klasslar va obyektlar
from core.ai_service import AIService, GeminiProvider, ProviderError
from core.config_manager import ConfigManager
from core.cache import CacheManager

pytestmark = pytest.mark.asyncio

# --- Fixtures (Test uchun tayyorgarlik) ---

@pytest.fixture
def mock_config() -> MagicMock:
    """Soxta (mock) ConfigManager obyektini to'g'ri sozlaydi."""
    def get_side_effect(key, default=None):
        return {
            "AI_DEFAULT_MODEL": "gemini-test-model",
            "AI_VISION_MODEL": "gemini-vision-model",
            "GEMINI_API_KEY": "test_gemini_key",
            "YANDEX_API_KEY": "test_yandex_key",
            "YANDEX_FOLDER_ID": "test_yandex_folder",
            "RAG_SEARCH_RESULTS_COUNT": 3,
            "RAG_FETCH_MAX_URLS": 2,
            "RAG_MAX_CONTEXT_LENGTH": 1000
        }.get(key, default)
    
    mock = MagicMock(spec=ConfigManager)
    mock.get.side_effect = get_side_effect
    return mock

@pytest.fixture
def mock_cache() -> AsyncMock:
    """Soxta (mock) CacheManager obyektini yaratadi."""
    return AsyncMock(spec=CacheManager)

@pytest_asyncio.fixture
async def ai_service(mock_config: MagicMock, mock_cache: AsyncMock) -> AsyncGenerator[AIService, None]:
    """Har bir test uchun yangi, toza AIService obyektini yaratadi."""
    # Tashqi kutubxonalarni to'liq "soxtalashtiramiz" (patch qilamiz)
    with patch('core.ai_service.genai', MagicMock()):
        service = AIService(config_manager=mock_config, cache_manager=mock_cache)
        await service.configure()
        yield service

# --- Test Klasslari ---

class TestAIService:
    """AIService va uning provayderlarini test qilish."""

    async def test_initialization_and_provider_access(self, ai_service: AIService):
        """1. AI Servis va Gemini Provayder muvaffaqiyatli yaratilishini tekshirish."""
        assert ai_service.is_configured is True
        assert isinstance(ai_service._get_provider('gemini'), GeminiProvider)

    async def test_generate_text(self, ai_service: AIService):
        """2. Oddiy matn generatsiyasini tekshirish."""
        with patch.object(ai_service._get_provider('gemini'), 'generate_text', new_callable=AsyncMock) as mock_gen:
            mock_gen.return_value = {"text": "Salom, Dunyo!", "tokens": 2}
            result = await ai_service.generate_text("Salom")
            mock_gen.assert_awaited_once()
            assert result["text"] == "Salom, Dunyo!"

    async def test_generate_from_image(self, ai_service: AIService):
        """3. Rasmga asoslanib matn generatsiyasini tekshirish."""
        with patch.object(ai_service._get_provider('gemini'), 'generate_from_image', new_callable=AsyncMock) as mock_gen:
            mock_gen.return_value = {"text": "Bu olma.", "tokens": 3}
            await ai_service.generate_from_image("Rasmda nima?", b"img_bytes")
            mock_gen.assert_awaited_once_with("gemini-vision-model", "Rasmda nima?", b"img_bytes")

    async def test_chat_workflow(self, ai_service: AIService):
        """4. Suhbat (chat) funksiyalarining to'liq siklini tekshirish."""
        with patch.object(ai_service._get_provider('gemini'), 'start_chat', new_callable=AsyncMock) as mock_start, \
             patch.object(ai_service._get_provider('gemini'), 'generate_chat_response', new_callable=AsyncMock) as mock_resp:
            
            mock_resp.return_value = {"text": "Albatta!", "tokens": 1}
            
            await ai_service.start_chat("chat123", persona="Hazilkash")
            mock_start.assert_awaited_once_with("chat123", "Hazilkash")

            await ai_service.generate_chat_response("chat123", "Yordam bera olasizmi?")
            mock_resp.assert_awaited_once_with("chat123", "Yordam bera olasizmi?")

    @patch('core.ai_service.GeminiProvider.transcribe_audio', new_callable=AsyncMock)
    async def test_transcribe_audio_success(self, mock_transcribe: AsyncMock, ai_service: AIService):
        """5. Audio transkripsiyaning muvaffaqiyatli ishlashi."""
        mock_transcribe.return_value = {"text": "test audio matni", "tokens": 3}
        result = await ai_service.transcribe_audio(b"audio_data")
        mock_transcribe.assert_awaited_once_with(b"audio_data")
        assert result["text"] == "test audio matni"
    
    @patch('core.ai_service.GeminiProvider.transcribe_audio', new_callable=AsyncMock)
    async def test_transcribe_audio_yandex_error(self, mock_transcribe: AsyncMock, ai_service: AIService):
        """6. Audio transkripsiya xizmatidan xato kelganda."""
        mock_transcribe.return_value = {"text": "Audio xatolik: INVALID_KEY", "tokens": 0}
        result = await ai_service.transcribe_audio(b"audio_data")
        assert "INVALID_KEY" in result["text"]

    @patch('core.ai_service.search')
    @patch('core.ai_service.AIService._fetch_url_content', new_callable=AsyncMock)
    async def test_generate_with_rag(self, mock_fetch: AsyncMock, mock_search: MagicMock, ai_service: AIService):
        """7. Internetdan qidirish (RAG) funksiyasini tekshirish."""
        mock_search.return_value = ["https://example.com/maqola"]
        mock_fetch.return_value = "Maqola matni."
        
        with patch.object(ai_service, 'generate_text', new_callable=AsyncMock) as mock_generate:
            await ai_service.generate_with_rag("Maqola nima?")
            mock_generate.assert_awaited_once()
            args, _ = mock_generate.call_args
            assert "Maqola matni." in args[0]

    async def test_handle_request_error_wrapping(self, ai_service: AIService):
        """8. AI so'rovida xatolik yuz berganda uni to'g'ri qayta ishlash."""
        # XATOLIK TUZATILDI: `_get_provider` o'rniga provayderning o'zining metodini patch qilamiz.
        with patch.object(ai_service._get_provider('gemini'), 'generate_text', new_callable=AsyncMock) as mock_generate:
            mock_generate.side_effect = ProviderError("API kaliti xato")
            result = await ai_service.generate_text("test")
            assert "<b>AI Xatoligi:</b>" in result["text"]
            assert "API kaliti xato" in result["text"]

    async def test_generate_from_document(self, ai_service: AIService):
        """9. Hujjat matniga asoslanib javob berish."""
        with patch.object(ai_service, 'generate_text', new_callable=AsyncMock) as mock_generate:
            mock_generate.return_value = {"text": "Bu muhim hujjat.", "tokens": 10}
            await ai_service.generate_from_document("Qisqacha mazmuni?", "Juda uzun hujjat matni...")
            mock_generate.assert_awaited_once()
            args, _ = mock_generate.call_args
            assert "Juda uzun hujjat matni..." in args[0]
            
    async def test_initialization_no_key_fails_gracefully(self, mock_cache: AsyncMock):
        """10. API kaliti yo'q bo'lganda xatosiz ishga tushishini tekshirish."""
        empty_config = MagicMock(spec=ConfigManager)
        empty_config.get.return_value = None
        
        # genai'ni patch qilamiz, chunki u kalitsiz ishga tushmaydi
        with patch('core.ai_service.genai', MagicMock()):
            service = AIService(config_manager=empty_config, cache_manager=mock_cache)
            await service.configure()
            assert service.is_configured is False
            assert 'gemini' not in service._providers
