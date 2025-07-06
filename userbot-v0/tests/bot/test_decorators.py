# tests/bot/test_decorators.py

import pytest
import re
from typing import Any, cast, Pattern
from telethon import events

# Test qilinadigan dekoratorni va yordamchi funksiyani import qilamiz
from bot.decorators import userbot_handler, _create_final_pattern

# --- Yordamchi Funksiya Testlari ---


def test_create_final_pattern_with_single_command():
    """Yakka buyruqdan to'g'ri regex yaratilishini tekshiradi."""
    pattern = _create_final_pattern(command=".test", pattern=None)
    assert isinstance(pattern, Pattern)
    assert pattern.pattern == r"^\.(?:test)(?: |$)(.*)"
    assert bool(pattern.flags & re.IGNORECASE)
    assert bool(pattern.flags & re.DOTALL)
    assert pattern.match(".test hello world")


def test_create_final_pattern_with_command_list():
    """Buyruqlar ro'yxatidan to'g'ri regex yaratilishini tekshiradi."""
    pattern = _create_final_pattern(command=[".help", ".start"], pattern=None)
    assert pattern.pattern == r"^\.(?:help|start)(?: |$)(.*)"
    assert pattern.match(".help")
    assert pattern.match(".start command")


def test_create_final_pattern_with_str_pattern():
    """Oddiy matnli patterndan to'g'ri regex yaratilishini tekshiradi."""
    # `^` belgisini avtomatik qo'shishni tekshirish
    pattern = _create_final_pattern(command=None, pattern=r"item_(\d+)")
    assert pattern.pattern == r"^item_(\d+)"
    assert pattern.match("item_123")
    assert not pattern.match(" an item_123")

    # `^` belgisi allaqachon mavjud bo'lsa, qayta qo'shmaslikni tekshirish
    pattern_with_anchor = _create_final_pattern(command=None, pattern=r"^item_(\d+)")
    assert pattern_with_anchor.pattern == r"^item_(\d+)"


def test_create_final_pattern_with_compiled_pattern():
    """Oldindan kompilyatsiya qilingan regex obyekti o'zgarishsiz qolishini tekshiradi."""
    compiled = re.compile(r"^\d+$", re.ASCII)
    pattern = _create_final_pattern(command=None, pattern=compiled)
    assert pattern is compiled  # Obyektning o'zi qaytishi kerak
    assert pattern.flags & re.ASCII


# --- Asosiy Dekorator Testlari ---


def test_handler_with_command():
    """`command` argumenti bilan dekoratorni tekshirish."""

    @userbot_handler(command=".ping", description="Ping buyrug'i")
    async def handler(event):
        pass

    assert hasattr(handler, "_userbot_handler")
    assert getattr(handler, "_userbot_handler") is True

    meta = getattr(handler, "_userbot_meta")
    assert meta["description"] == "Ping buyrug'i"
    assert meta["commands"] == [".ping"]
    assert meta["usage"] == ".ping"

    handler_args = getattr(handler, "_handler_args")
    assert isinstance(handler_args.get("pattern"), Pattern)
    assert handler_args["pattern"].pattern == r"^\.(?:ping)(?: |$)(.*)"


def test_handler_with_pattern():
    """`pattern` argumenti bilan dekoratorni tekshirish."""

    @userbot_handler(pattern=r"hello (\w+)", description="Salomlashish")
    async def handler(event):
        pass

    assert hasattr(handler, "_userbot_handler")

    meta = getattr(handler, "_userbot_meta")
    assert meta["description"] == "Salomlashish"
    assert meta["commands"] == []
    assert meta["usage"] == "Regex asosida"

    handler_args = getattr(handler, "_handler_args")
    assert handler_args["pattern"].pattern == r"^hello (\w+)"


def test_handler_with_extra_kwargs():
    """Qo'shimcha `kwargs` (Telethon argumentlari) to'g'ri o'tishini tekshiradi."""

    # --- YECHIM: `outgoing` ni `False` qilib, standart holat bekor qilinishini tekshiramiz ---
    @userbot_handler(command=".secret", incoming=True, outgoing=False, chats=[-100, -200])
    async def handler(event):
        pass

    handler_args = getattr(handler, "_handler_args")
    assert handler_args["incoming"] is True
    assert handler_args["outgoing"] is False  # Endi bu `False` bo'lishi kerak
    assert handler_args["chats"] == [-100, -200]

    # Standart holatni alohida tekshirish
    @userbot_handler(command=".default")
    async def default_handler(event):
        pass

    default_args = getattr(default_handler, "_handler_args")
    assert default_args["outgoing"] is True


def test_handler_no_command_or_pattern_raises_error():
    """`command` ham, `pattern` ham berilmaganda xatolikni tekshiradi."""
    with pytest.raises(ValueError, match="Argumentlardan faqat bittasi ishlatilishi kerak"):

        @userbot_handler(description="Xato test")
        async def handler(event):
            pass


def test_handler_both_command_and_pattern_raises_error():
    """`command` va `pattern` birga berilganda xatolikni tekshiradi."""
    with pytest.raises(ValueError, match="Argumentlardan faqat bittasi ishlatilishi kerak"):

        @userbot_handler(command=".test", pattern="test", description="Xato test")
        async def handler(event):
            pass


def test_handler_meta_data_structure():
    """Meta-ma'lumotlar lug'atining tuzilishi to'g'riligini tekshiradi."""

    @userbot_handler(command=[".info", ".i"], description="Ma'lumot olish")
    async def handler(event):
        pass

    assert hasattr(handler, "_userbot_meta")
    meta = getattr(handler, "_userbot_meta")

    expected_keys = {"description", "commands", "pattern_str", "flags", "is_admin_only", "usage"}
    assert set(meta.keys()) == expected_keys

    assert meta["commands"] == [".info", ".i"]
    assert isinstance(meta["pattern_str"], str)
    # --- YECHIM: re.RegexFlag o'rniga int'ni tekshiramiz ---
    assert isinstance(meta["flags"], int)
