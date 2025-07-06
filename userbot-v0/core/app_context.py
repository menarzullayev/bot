# core/app_context.py
# Fayl faqat "AppContext" klassini ta'riflash uchun mas'ul.
# Qat'iy "Dependency Injection" uchun yagona markaziy klass.

from dataclasses import dataclass
from typing import TYPE_CHECKING

# Siklik importlarning oldini olish uchun TYPE_CHECKING dan foydalanamiz.
# Bu faqat tip tekshiruvchilar (Mypy, Pylance) uchun ishlaydi, ish vaqtida (runtime) import qilinmaydi.
if TYPE_CHECKING: # pragma: no cover
    from core.database import AsyncDatabase
    from core.config_manager import ConfigManager
    from core.state import AppState
    from core.cache import CacheManager
    from core.tasks import TaskRegistry
    from core.scheduler import SchedulerManager
    from core.ai_service import AIService
    from core.client_manager import ClientManager
    from bot.loader import PluginManager


#  `frozen=True` orqali AppContext obyektini o'zgarmas (immutable) qilamiz.
# Bu obyekt yaratilgandan so'ng uning biror maydonini tasodifan o'zgartirib yuborishning oldini oladi.
@dataclass(frozen=True)
class AppContext:
    """
    Dasturning barcha asosiy komponentlarini o'zida saqlaydigan yagona, o'zgarmas kontekst.
    Bu butun dastur bo'ylab bog'liqliklarni uzatish uchun ishlatiladi.
    """
    #  Barcha komponentlar uchun aniq tiplar (Type Hinting) ko'rsatilgan.
    db: "AsyncDatabase"
    config: "ConfigManager"
    state: "AppState"
    cache: "CacheManager"
    tasks: "TaskRegistry"
    scheduler: "SchedulerManager"
    ai_service: "AIService"
    client_manager: "ClientManager"
    plugin_manager: "PluginManager"

