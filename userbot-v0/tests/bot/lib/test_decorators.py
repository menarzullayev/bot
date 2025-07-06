"""
bot/lib/decorators.py faylidagi yordamchi dekoratorlar uchun
pytest testlar to'plami.
"""

import asyncio
from unittest.mock import MagicMock, AsyncMock, patch

import pytest
from telethon.tl.custom import Message


from bot.lib import decorators
from core.app_context import AppContext


@pytest.fixture
def mock_message() -> MagicMock:
    """Telethon Message obyekti uchun soxta (mock) obyekt."""
    msg = MagicMock(spec=Message)
    msg.sender_id = 12345
    msg.text = ".test"
    return msg


@pytest.fixture
def mock_context() -> MagicMock:
    """AppContext uchun to'liq soxta (mock) obyekt."""
    ctx = MagicMock(spec=AppContext)
    ctx.cache = AsyncMock()

    ctx.cache.get = AsyncMock(return_value=None)
    ctx.cache.set = AsyncMock()
    return ctx


@pytest.mark.asyncio
@patch("bot.lib.decorators.asyncio.sleep", new_callable=AsyncMock)
@patch("bot.lib.decorators._safe_edit_message", new_callable=AsyncMock)
@patch("bot.lib.decorators.time.monotonic")
async def test_rate_limit_decorator(mock_time, mock_edit, mock_sleep, mock_message, mock_context):
    """
    `@rate_limit` dekoratorining asosiy oqimini tekshiradi:
    1. Birinchi chaqiruvga ruxsat beradi.
    2. Ikkinchi (tez) chaqiruvni bloklaydi.
    3. Vaqt o'tgandan keyin yana ruxsat beradi.
    """

    decorated_func = AsyncMock(return_value="OK")
    rate_limited_func = decorators.rate_limit(seconds=10)(decorated_func)

    mock_context.cache.get.return_value = None
    mock_time.return_value = 1000.0
    result = await rate_limited_func(mock_message, mock_context)

    assert result == "OK"
    decorated_func.assert_awaited_once()
    mock_edit.assert_not_awaited()
    mock_context.cache.set.assert_awaited_once_with(f"rate_limit:{decorated_func.__name__}:{mock_message.sender_id}", 1000.0, ttl=10)

    decorated_func.reset_mock()
    mock_context.cache.get.return_value = 1000.0
    mock_time.return_value = 1005.0

    result = await rate_limited_func(mock_message, mock_context)

    assert result is None
    decorated_func.assert_not_awaited()
    mock_edit.assert_awaited()

    warn_text = mock_edit.call_args_list[0].args[1]
    assert "5.0" in warn_text

    mock_sleep.assert_awaited_once_with(2)

    decorated_func.reset_mock()
    mock_edit.reset_mock()
    mock_context.cache.set.reset_mock()
    mock_context.cache.get.return_value = 1000.0
    mock_time.return_value = 1011.0

    result = await rate_limited_func(mock_message, mock_context)

    assert result == "OK"
    decorated_func.assert_awaited_once()
    mock_edit.assert_not_awaited()
    mock_context.cache.set.assert_awaited_once_with(f"rate_limit:{decorated_func.__name__}:{mock_message.sender_id}", 1011.0, ttl=10)


@pytest.mark.asyncio
async def test_rate_limit_no_sender_id(mock_message, mock_context):
    """`event.sender_id` mavjud bo'lmaganda funksiya ishlamasligini tekshiradi."""

    decorated_func = AsyncMock()
    rate_limited_func = decorators.rate_limit(seconds=10)(decorated_func)

    mock_message.sender_id = None
    result = await rate_limited_func(mock_message, mock_context)

    assert result is None
    decorated_func.assert_not_awaited()


@pytest.mark.asyncio
@patch("bot.lib.decorators.asyncio.sleep", new_callable=AsyncMock)
@patch("bot.lib.decorators._safe_edit_message", new_callable=AsyncMock)
@patch("bot.lib.decorators.time.monotonic")
async def test_rate_limit_with_shared_name(mock_time, mock_edit, mock_sleep, mock_message, mock_context):
    """
    Bir nechta funksiya umumiy `name` orqali bitta cheklovni bo'lishishini tekshiradi.
    """
    func_a = AsyncMock(name="func_a")
    func_b = AsyncMock(name="func_b")

    rate_limited_a = decorators.rate_limit(seconds=20, name="shared_limit")(func_a)
    rate_limited_b = decorators.rate_limit(seconds=20, name="shared_limit")(func_b)

    mock_context.cache.get.return_value = None
    mock_time.return_value = 2000.0
    await rate_limited_a(mock_message, mock_context)

    func_a.assert_awaited_once()
    mock_context.cache.set.assert_awaited_once_with(f"rate_limit:shared_limit:{mock_message.sender_id}", 2000.0, ttl=20)

    func_b.reset_mock()

    mock_context.cache.get.return_value = 2000.0
    mock_time.return_value = 2010.0

    result = await rate_limited_b(mock_message, mock_context)

    assert result is None
    func_b.assert_not_awaited()
