# tests/bot/lib/test_auth.py
"""
bot/lib/auth.py faylidagi avtorizatsiya funksiyalari va dekoratorlari
uchun pytest testlar to'plami.
"""
import asyncio
from unittest.mock import MagicMock, AsyncMock, patch

import pytest
from telethon.tl.custom import Message

# Test qilinayotgan modulni import qilamiz
from bot.lib import auth
from core.app_context import AppContext

# --- TESTLAR UCHUN SOZLAMALAR (FIXTURES) ---

@pytest.fixture
def mock_message() -> MagicMock:
    """Telethon Message obyekti uchun soxta (mock) obyekt yaratadi."""
    msg = MagicMock(spec=Message)
    msg.sender_id = None
    # Dekoratorlar chaqiradigan yordamchi funksiyalarni soxtalashtiramiz
    msg.edit = AsyncMock()
    msg.delete = AsyncMock()
    return msg


@pytest.fixture
def mock_context() -> MagicMock:
    """AppContext uchun to'liq soxta (mock) obyekt yaratadi."""
    ctx = MagicMock(spec=AppContext)
    ctx.config = MagicMock()
    ctx.db = AsyncMock()
    ctx.cache = AsyncMock()
    return ctx

# --- ASOSIY TESTLAR ---

@pytest.mark.asyncio
async def test_get_all_admin_ids(mock_context):
    """
    `get_all_admin_ids` funksiyasining kesh, baza va konfiguratsiyadan
    to'g'ri ma'lumot olishini tekshiradi.
    """
    # Sozlamalarni mock qilamiz
    mock_context.config.get.side_effect = lambda key, default=[]: {
        "OWNER_ID": 1,
        "ADMIN_IDS": [2, 3],
    }.get(key, default)
    mock_context.db.fetchall.return_value = [{"user_id": 3}, {"user_id": 4}]
    mock_context.cache.get.return_value = None # Kesh bo'sh

    # 1. Kesh bo'sh holatda
    admin_ids = await auth.get_all_admin_ids(mock_context)
    # Barcha manbalardan ID'lar to'g'ri yig'ilganini tekshiramiz (1, 2, 3, 4)
    assert admin_ids == {1, 2, 3, 4}
    # Natija keshga yozilganini tekshiramiz
    mock_context.cache.set.assert_awaited_once_with("auth:admin_ids", {1, 2, 3, 4}, ttl=600)

    # 2. Kesh to'la holatda
    mock_context.cache.get.return_value = {10, 20} # Keshlangan ma'lumot
    # Baza va sozlamalarga murojaat qilinmasligini tekshiramiz
    mock_context.db.fetchall.reset_mock()
    admin_ids = await auth.get_all_admin_ids(mock_context)
    assert admin_ids == {10, 20}
    mock_context.db.fetchall.assert_not_called()

    # 3. Keshni majburan yangilash
    await auth.invalidate_admin_cache(mock_context)
    mock_context.cache.delete.assert_awaited_once_with("auth:admin_ids")


@pytest.mark.asyncio
@patch("bot.lib.auth._handle_permission_denied", new_callable=AsyncMock)
async def test_owner_only_decorator(mock_handler, mock_message, mock_context):
    """`@owner_only` dekoratorining to'g'ri ishlashini tekshiradi."""
    
    decorated_func = AsyncMock()
    # Dekoratorni funksiyaga qo'llaymiz
    protected_func = auth.owner_only(decorated_func)
    
    # 1. Ruxsat berilgan holat (bot egasi)
    mock_context.config.get.return_value = 123
    mock_message.sender_id = 123
    await protected_func(mock_message, mock_context)
    decorated_func.assert_awaited_once() # Asosiy funksiya chaqirildi
    mock_handler.assert_not_awaited()   # Xatolik funksiyasi chaqirilmadi

    # 2. Ruxsat rad etilgan holat (begona foydalanuvchi)
    decorated_func.reset_mock()
    mock_message.sender_id = 456
    await protected_func(mock_message, mock_context)
    decorated_func.assert_not_awaited() # Asosiy funksiya chaqirilmadi
    mock_handler.assert_awaited_once()  # Xatolik funksiyasi chaqirildi


@pytest.mark.asyncio
@patch("bot.lib.auth._handle_permission_denied", new_callable=AsyncMock)
@patch("bot.lib.auth.get_all_admin_ids", new_callable=AsyncMock)
async def test_admin_only_decorator(mock_get_admins, mock_handler, mock_message, mock_context):
    """`@admin_only` dekoratorining to'g'ri ishlashini tekshiradi."""

    decorated_func = AsyncMock()
    protected_func = auth.admin_only(decorated_func)
    
    # Adminlar ro'yxatini mock qilamiz
    mock_get_admins.return_value = {123, 456}

    # 1. Ruxsat berilgan holat (admin)
    mock_message.sender_id = 456
    await protected_func(mock_message, mock_context)
    decorated_func.assert_awaited_once()
    mock_handler.assert_not_awaited()

    # 2. Ruxsat rad etilgan holat (begona foydalanuvchi)
    decorated_func.reset_mock()
    mock_message.sender_id = 789
    await protected_func(mock_message, mock_context)
    decorated_func.assert_not_awaited()
    mock_handler.assert_awaited_once()

@pytest.mark.asyncio
@patch("bot.lib.auth._safe_edit_message", new_callable=AsyncMock)
async def test_sudo_required_decorator(mock_edit, mock_message, mock_context):
    """`@sudo_required` dekoratorining to'g'ri ishlashini tekshiradi."""

    decorated_func = AsyncMock()
    protected_func = auth.sudo_required(decorated_func)
    
    # Xavfli buyruq sozlamasini mock qilamiz
    mock_context.config.get.return_value = ["restart"]
    # Buyruq nomini xabarga qo'shamiz
    mock_message.command_meta = {"name": "restart"}
    mock_message.sender_id = 123
    
    # 1. Ruxsat rad etilgan holat (sudo rejimi o'chiq)
    mock_context.cache.get.return_value = None # Sudo rejimi o'chiq
    await protected_func(mock_message, mock_context)
    decorated_func.assert_not_awaited()
    mock_edit.assert_awaited_once() # Xatolik xabari ko'rsatildi

    # 2. Ruxsat berilgan holat (sudo rejimi yoqilgan)
    decorated_func.reset_mock()
    mock_edit.reset_mock()
    mock_context.cache.get.return_value = True # Sudo rejimi yoqilgan
    await protected_func(mock_message, mock_context)
    decorated_func.assert_awaited_once()
    mock_edit.assert_not_awaited()

    # 3. Buyruq xavfli bo'lmagan holat
    decorated_func.reset_mock()
    mock_edit.reset_mock()
    mock_message.command_meta = {"name": "ping"} # Xavfsiz buyruq
    await protected_func(mock_message, mock_context)
    decorated_func.assert_awaited_once()
    mock_edit.assert_not_awaited()
