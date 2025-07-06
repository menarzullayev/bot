# tests/bot/test_telegram.py
"""
bot/lib/telegram.py faylidagi yordamchi funksiyalar uchun
pytest testlar to'plami.
"""

import asyncio
from unittest.mock import MagicMock, AsyncMock, patch

import pytest
from telethon.tl.custom import Message
from telethon.tl.types import (
    User, Chat, PeerUser, PeerChannel, ChatAdminRights
)
from telethon.errors import FloodWaitError, MessageNotModifiedError

# Test qilinayotgan funksiyalarni import qilamiz
from bot.lib import telegram

# ----- TESTLAR UCHUN SOZLAMALAR (FIXTURES) -----

@pytest.fixture
def mock_client() -> AsyncMock:
    """TelethonClient uchun soxta (mock) obyekt yaratadi."""
    client = AsyncMock()
    client.get_entity = AsyncMock()
    client.iter_participants = AsyncMock()
    client.get_permissions = AsyncMock()
    client.send_message = AsyncMock()
    client.delete_messages = AsyncMock()
    client.iter_messages = AsyncMock()
    return client

@pytest.fixture
def mock_message() -> MagicMock:
    """Message obyekti uchun soxta (mock) obyekt yaratadi."""
    message = MagicMock(spec=Message)
    message.edit = AsyncMock()
    message.get_reply_message = AsyncMock()
    message.download_media = AsyncMock()
    message.text = ""
    message.reply_to_msg_id = None
    message.peer_id = None
    message.file = None
    message.media = None
    return message


# ===== 1. API MUROJAATLARI VA XATOLIKLARNI BOSHQARISH TESTLARI =====

@pytest.mark.asyncio
async def test_retry_telegram_api_call():
    """`retry_telegram_api_call` funksiyasining to'g'ri ishlashini tekshiradi."""
    # Muvaffaqiyatli holat
    mock_api_func = AsyncMock(return_value="success")
    result = await telegram.retry_telegram_api_call(mock_api_func, "arg1")
    assert result == "success"
    mock_api_func.assert_awaited_once_with("arg1")

    # FloodWaitError bilan qayta urinish holati
    mock_api_func.reset_mock()
    # YAKUNIY O'ZGARISH: `seconds` atributiga int (butun son) berilishi kerak.
    flood_error = FloodWaitError(request=MagicMock())
    flood_error.seconds = 1  # 0.01 o'rniga 1
    mock_api_func.side_effect = [flood_error, "success"]
    result = await telegram.retry_telegram_api_call(mock_api_func)
    assert result == "success"
    assert mock_api_func.await_count == 2

    # Barcha urinishlar muvaffaqiyatsiz bo'lgan holat
    mock_api_func.reset_mock()
    mock_api_func.side_effect = flood_error
    result = await telegram.retry_telegram_api_call(mock_api_func)
    assert result is None
    assert mock_api_func.await_count == 5




@pytest.mark.asyncio
async def test_resolve_entity(mock_client):
    """`resolve_entity` funksiyasining obyektlarni to'g'ri topishini tekshiradi."""
    # Oddiy obyektni topish
    mock_user = User(id=1, first_name="Test")
    mock_client.get_entity.return_value = mock_user
    result = await telegram.resolve_entity(mock_client, "testuser")
    assert result == mock_user

    # Ro'yxat qaytargan holat
    mock_client.get_entity.return_value = [mock_user]
    result = await telegram.resolve_entity(mock_client, "testuser")
    assert result == mock_user

    # Xatolik holati
    mock_client.get_entity.side_effect = ValueError("Not found")
    result = await telegram.resolve_entity(mock_client, "nonexistent")
    assert result is None


# ===== 2. FOYDALANUVCHI VA CHATLAR BILAN ISHLASH TESTLARI =====

@pytest.mark.asyncio
async def test_get_user(mock_client):
    mock_client.get_entity.return_value = User(id=1, first_name="Test")
    user = await telegram.get_user(mock_client, 123)
    assert isinstance(user, User)

    # O'ZGARISH: Chat konstruktoriga barcha kerakli argumentlar berildi.
    mock_client.get_entity.return_value = Chat(
        id=1, title="Test", photo=MagicMock(), participants_count=1, date=MagicMock(), version=1
    )
    user = await telegram.get_user(mock_client, 123)
    assert user is None


@pytest.mark.asyncio
async def test_is_user_admin(mock_client):
    # Admin holati
    mock_client.get_permissions.return_value = MagicMock(is_admin=True, is_creator=False)
    assert await telegram.is_user_admin(mock_client, -100, 123) is True

    # Egasi holati
    mock_client.get_permissions.return_value = MagicMock(is_admin=False, is_creator=True)
    assert await telegram.is_user_admin(mock_client, -100, 123) is True

    # Oddiy foydalanuvchi holati
    mock_client.get_permissions.return_value = MagicMock(is_admin=False, is_creator=False)
    assert await telegram.is_user_admin(mock_client, -100, 123) is False

    # Xatolik holati
    mock_client.get_permissions.side_effect = Exception("Error")
    assert await telegram.is_user_admin(mock_client, -100, 123) is False


# ===== 3. XABARLAR BILAN ISHLASH TESTLARI =====

@pytest.mark.asyncio
async def test_get_reply_message(mock_message):
    mock_message.reply_to_msg_id = 123
    replied_msg = Message(id=123, peer_id=PeerUser(123))
    mock_message.get_reply_message.return_value = replied_msg

    # YAKUNIY O'ZGARISH: Obyektlarni emas, ularning ID'larini solishtiramiz.
    result_msg = await telegram.get_reply_message(mock_message)
    assert result_msg is not None
    assert result_msg.id == replied_msg.id

    mock_message.reply_to_msg_id = None
    assert await telegram.get_reply_message(mock_message) is None



def test_get_message_link(mock_message):
    mock_message.peer_id = PeerChannel(channel_id=12345)
    mock_message.id = 987
    assert telegram.get_message_link(mock_message) == "https://t.me/c/12345/987"

    mock_message.peer_id = PeerUser(user_id=54321)
    assert telegram.get_message_link(mock_message) is None


@pytest.mark.asyncio
async def test_edit_message(mock_message):
    mock_message.edit.return_value = "edited"
    assert await telegram.edit_message(mock_message, "new text") == "edited"

    # YAKUNIY O'ZGARISH: MessageNotModifiedError konstruktoriga 'request' argumenti qo'shildi.
    mock_message.edit.side_effect = MessageNotModifiedError(request=MagicMock())
    assert await telegram.edit_message(mock_message, "same text") == mock_message



def test_get_command_args():
    mock_event = MagicMock()
    mock_event.text = ".command arg1 arg2"
    assert telegram.get_command_args(mock_event) == ["arg1", "arg2"]
    
    mock_event.text = ".command"
    assert telegram.get_command_args(mock_event) == []

    mock_event.text = None
    assert telegram.get_command_args(mock_event) == []


# ===== 4. MEDIA FAYLLAR BILAN ISHLASH TESTLARI =====

@pytest.mark.asyncio
async def test_download_file(mock_message):
    mock_message.media = True
    mock_message.download_media.return_value = "/path/to/file"
    assert await telegram.download_file(mock_message) == "/path/to/file"

    mock_message.media = None
    assert await telegram.download_file(mock_message) is None


# ===== 5. BOSHQA YORDAMCHI FUNKSIYALAR TESTLARI =====

def test_get_full_name():
    user = User(id=1, first_name="John", last_name="Doe")
    assert telegram.get_full_name(user) == "John Doe"
    
    user = User(id=1, first_name="John", last_name=None)
    assert telegram.get_full_name(user) == "John"


@pytest.mark.asyncio
async def test_check_rights_and_reply(mock_message):
    # Yetarli huquqlar bor
    mock_chat = MagicMock()
    mock_chat.admin_rights = ChatAdminRights(delete_messages=True)
    mock_message.get_chat.return_value = mock_chat
    assert await telegram.check_rights_and_reply(mock_message, ["delete_messages"]) is True

    # Yetarli huquqlar yo'q
    mock_message.edit.reset_mock() # mock hisoblagichini tozalash
    mock_chat.admin_rights = ChatAdminRights(delete_messages=False)
    mock_message.get_chat.return_value = mock_chat
    assert await telegram.check_rights_and_reply(mock_message, ["delete_messages"]) is False
    mock_message.edit.assert_awaited_once()

    # Umuman admin emas
    mock_message.edit.reset_mock()
    mock_chat.admin_rights = None
    mock_message.get_chat.return_value = mock_chat
    assert await telegram.check_rights_and_reply(mock_message, ["delete_messages"]) is False
    mock_message.edit.assert_awaited_once() # Bu yerda ham xabar tahrirlanishi kerak
