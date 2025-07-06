"""
bot/lib/ui.py faylidagi foydalanuvchi interfeysi bilan bog'liq
barcha funksiyalar uchun pytest testlar to'plami.
"""

import asyncio
from unittest.mock import MagicMock, AsyncMock, patch

import pytest
from telethon.tl.custom import Message


from bot.lib import ui
from core.app_context import AppContext


@pytest.fixture
def mock_message() -> MagicMock:
    """Message obyekti uchun to'liq soxta (mock) obyekt."""
    message = MagicMock(spec=Message)

    message.client = MagicMock()
    message.client.conversation = AsyncMock()
    message.peer_id = 12345
    message.id = 54321
    message.sender_id = 98765
    message.chat_id = 12345
    message.text = ""
    return message


@pytest.fixture
def mock_context() -> MagicMock:
    """AppContext uchun to'liq soxta (mock) obyekt."""
    context = MagicMock(spec=AppContext)
    context.cache = AsyncMock()
    context.cache.set = AsyncMock()
    context.cache.get = AsyncMock()
    context.cache.delete = AsyncMock()
    return context


class TestFormattingFunctions:
    """Matnni formatlash yordamchilarini tekshiradi."""

    def test_simple_formatters(self):
        assert ui.bold("test") == "<b>test</b>"
        assert ui.italic("test") == "<i>test</i>"
        assert ui.code("test") == "<code>test</code>"
        assert ui.pre("test") == "<pre>test</pre>"

        assert ui.bold("<tag>") == "<b>&lt;tag&gt;</b>"

    def test_link_formatter(self):
        assert ui.link("Google", "https://google.com") == '<a href="https://google.com">Google</a>'

        assert ui.link("test", 'https://e.com/?a="b"&c=d') == '<a href="https://e.com/?a=&quot;b&quot;&amp;c=d">test</a>'

    def test_status_formatters(self):
        assert ui.format_success("Bajarildi") == "✅ <b>Muvaffaqiyatli:</b>\nBajarildi"
        assert ui.format_error("Bajarilmadi") == "❌ <b>Xatolik:</b>\nBajarilmadi"

    def test_format_as_table(self):
        """Jadvalni formatlash funksiyasini tekshiradi."""
        headers = ["ID", "Nomi"]
        rows = [[1, "Bir"], [20, "Yigirma"]]
        table = ui.format_as_table(headers, rows)

        cleaned_table_lines = [line.strip() for line in table.strip().split('\n')]
        assert "ID | Nomi" in cleaned_table_lines[0]
        assert "1  | Bir" in cleaned_table_lines[2]
        assert "20 | Yigirma" in cleaned_table_lines[3]

        assert ui.format_as_table(headers, []) == "<i>(Natija bo'sh)</i>"


@pytest.mark.asyncio
@patch("bot.lib.ui.retry_telegram_api_call", new_callable=AsyncMock)
async def test_safe_edit_message(mock_retry, mock_message):
    """`_safe_edit_message` funksiyasining to'g'ri ishlashini tekshiradi."""

    result = await ui._safe_edit_message(mock_message, "Yangi matn")
    assert result is True
    mock_retry.assert_awaited_once_with(mock_message.client.edit_message, entity=mock_message.peer_id, message=mock_message.id, text="Yangi matn", parse_mode="html", link_preview=False)

    mock_retry.reset_mock()
    mock_retry.side_effect = Exception("Test xatoligi")
    result = await ui._safe_edit_message(mock_message, "Yana bir matn")
    assert result is False

    mock_retry.reset_mock()
    result = await ui._safe_edit_message(mock_message, "")
    assert result is False
    mock_retry.assert_not_awaited()


@pytest.mark.asyncio
@patch("bot.lib.ui.uuid.uuid4")
@patch("bot.lib.ui._safe_edit_message", new_callable=AsyncMock)
@patch("bot.lib.ui.retry_telegram_api_call", new_callable=AsyncMock)
async def test_request_confirmation(mock_retry, mock_edit, mock_uuid, mock_message, mock_context):
    """`request_confirmation` oqimining barcha holatlarini tekshiradi."""

    mock_uuid.return_value.hex = "a1b2c3d4e5"
    confirm_code = "a1b2c3"
    command_name = "delete_all"

    mock_conv = AsyncMock()
    mock_message.client.conversation.return_value = mock_conv
    mock_conv.__aenter__.return_value = mock_conv

    correct_response = MagicMock(spec=Message)
    correct_response.text = f".{command_name} {confirm_code}"
    correct_response.delete = AsyncMock()
    mock_conv.get_response.return_value = correct_response

    mock_message.client.conversation.side_effect = None

    result = await ui.request_confirmation(mock_message, mock_context, "hamma narsani o'chirish", command_name)

    assert result is True, "Tasdiqlash muvaffaqiyatli bo'lishi kerak edi"

    assert f"<code>.{command_name} {confirm_code}</code>" in mock_edit.call_args_list[0].args[1]

    assert "✅ <b>Tasdiqlandi.</b>" in mock_edit.call_args_list[1].args[1]
    mock_context.cache.delete.assert_awaited_with(f"confirm:{mock_message.sender_id}:{command_name}")
    mock_retry.assert_awaited_with(correct_response.delete)

    mock_edit.reset_mock()
    mock_retry.reset_mock()
    mock_context.cache.delete.reset_mock()

    wrong_response = MagicMock(spec=Message)
    wrong_response.text = f".{command_name} wrong_code"
    wrong_response.delete = AsyncMock()
    mock_conv.get_response.return_value = wrong_response

    result = await ui.request_confirmation(mock_message, mock_context, "...", command_name)
    assert result is False, "Noto'g'ri kod bilan tasdiqlash muvaffaqiyatsiz bo'lishi kerak edi"

    assert "❌ <i>Noto'g'ri tasdiqlash kodi." in mock_edit.call_args_list[1].args[1]

    mock_edit.reset_mock()
    mock_context.cache.get.return_value = True

    mock_message.client.conversation.side_effect = asyncio.TimeoutError

    result = await ui.request_confirmation(mock_message, mock_context, "...", command_name)
    assert result is False, "Timeout holati muvaffaqiyatsiz bo'lishi kerak edi"

    assert "⏳ <i>Vaqt tugadi." in mock_edit.call_args_list[1].args[1]
