# tests/core/test_app_context.py

import pytest
from unittest.mock import MagicMock

# Test qilinayotgan klassni import qilamiz
from core.app_context import AppContext

# AppContext ning bog'liqliklarini mock qilish uchun ishlatiladigan fixture
@pytest.fixture
def mock_dependencies():
    """AppContext uchun barcha bog'liqliklarni mock qiladi."""
    return {
        "db": MagicMock(name="AsyncDatabase"),
        "config": MagicMock(name="ConfigManager"),
        "state": MagicMock(name="AppState"),
        "cache": MagicMock(name="CacheManager"),
        "tasks": MagicMock(name="TaskRegistry"),
        "scheduler": MagicMock(name="SchedulerManager"),
        "ai_service": MagicMock(name="AIService"),
        "client_manager": MagicMock(name="ClientManager"),
        "plugin_manager": MagicMock(name="PluginManager"),
    }

class TestAppContext:
    """AppContext klassi uchun testlar."""

    # 1. Barcha kerakli bog'liqliklar bilan to'g'ri instansiyalashni tekshirish
    def test_app_context_instantiation_success(self, mock_dependencies):
        """AppContext barcha majburiy bog'liqliklar bilan muvaffaqiyatli yaratilishini tekshiradi."""
        context = AppContext(**mock_dependencies)
        assert context is not None
        assert isinstance(context, AppContext)

    # 2. Atributlarga to'g'ri kirishni tekshirish
    def test_app_context_attributes_accessible(self, mock_dependencies):
        """AppContext obyektining atributlariga to'g'ri kirishni tekshiradi."""
        context = AppContext(**mock_dependencies)
        assert context.db == mock_dependencies["db"]
        assert context.config == mock_dependencies["config"]
        assert context.state == mock_dependencies["state"]
        assert context.cache == mock_dependencies["cache"]
        assert context.tasks == mock_dependencies["tasks"]
        assert context.scheduler == mock_dependencies["scheduler"]
        assert context.ai_service == mock_dependencies["ai_service"]
        assert context.client_manager == mock_dependencies["client_manager"]
        assert context.plugin_manager == mock_dependencies["plugin_manager"]

    # 3. Ba'zi majburiy bog'liqliklar yo'q bo'lganda TypeError berishini tekshirish
    def test_app_context_missing_required_dependency(self, mock_dependencies):
        """Majburiy bog'liqliklardan biri etishmayotganda TypeError berishini tekshiradi."""
        del mock_dependencies["db"]  # 'db' ni o'chirib tashlaymiz
        with pytest.raises(TypeError) as excinfo:
            AppContext(**mock_dependencies)
        assert "missing 1 required positional argument: 'db'" in str(excinfo.value) or \
               "__init__() missing 1 required positional argument: 'db'" in str(excinfo.value)


    # 4. Obyektning o'zgarmasligini (immutability) tekshirish
    def test_app_context_is_frozen(self, mock_dependencies):
        """AppContext obyektining atributlarini o'zgartirish mumkin emasligini tekshiradi."""
        context = AppContext(**mock_dependencies)
        with pytest.raises(AttributeError, match="cannot assign to field 'db'"):
            context.db = MagicMock() # Atributni o'zgartirishga harakat qilamiz # type: ignore


    # 5. Bo'sh bog'liqliklar bilan instansiyalash imkoniyatini tekshirish (bu holatda TypeError beradi)
    def test_app_context_empty_dependencies_raises_type_error(self):
        """Hech qanday bog'liqliklarsiz AppContext yaratish TypeError berishini tekshiradi."""
        with pytest.raises(TypeError) as excinfo:
            AppContext() # type: ignore
        assert "missing" in str(excinfo.value) and "required positional arguments" in str(excinfo.value)


    # 6. Har xil turdagi mock obyektlari bilan ishlashini tekshirish
    def test_app_context_with_different_mock_types(self):
        """AppContext turli xil mock obyektlari bilan ham ishlashini tekshiradi."""
        # AsyncMock ham ishlatib ko'ramiz
        from unittest.mock import AsyncMock
        context = AppContext(
            db=AsyncMock(name="AsyncDatabase"),
            config=MagicMock(name="ConfigManager"),
            state=MagicMock(name="AppState"),
            cache=MagicMock(name="CacheManager"),
            tasks=MagicMock(name="TaskRegistry"),
            scheduler=MagicMock(name="SchedulerManager"),
            ai_service=MagicMock(name="AIService"),
            client_manager=MagicMock(name="ClientManager"),
            plugin_manager=MagicMock(name="PluginManager"),
        )
        assert context is not None
        assert isinstance(context.db, AsyncMock)

    # 7. __repr__ metodining to'g'ri ishlashini tekshirish (dataclass avtomatik generatsiya qiladi)
    def test_app_context_repr(self, mock_dependencies):
        """AppContext obyektining __repr__ metodi to'g'ri formatlanganligini tekshiradi."""
        context = AppContext(**mock_dependencies)
        repr_str = repr(context)
        assert "AppContext(" in repr_str
        assert f"db={mock_dependencies['db']}" in repr_str
        assert f"config={mock_dependencies['config']}" in repr_str
        # Boshqa atributlar uchun ham tekshirishingiz mumkin

    # 8. Hashable ekanligini tekshirish (frozen dataclasslar hashable bo'ladi)
    def test_app_context_is_hashable(self, mock_dependencies):
        """Frozen dataclass AppContext hashable ekanligini tekshiradi."""
        context = AppContext(**mock_dependencies)
        try:
            # Set ga qo'shish orqali hashable ekanligini tekshiramiz
            test_set = {context}
            assert context in test_set
        except TypeError:
            pytest.fail("AppContext is not hashable, but it should be (due to frozen=True)")

    # 9. Ikkita bir xil AppContext obyektining tengligini tekshirish
    def test_app_context_equality(self, mock_dependencies):
        """Bir xil bog'liqliklar bilan yaratilgan ikki AppContext obyektining tengligini tekshiradi."""
        context1 = AppContext(**mock_dependencies)
        context2 = AppContext(**mock_dependencies) # Xuddi shu mocklar bilan ikkinchisini yaratamiz
        assert context1 == context2

    # 10. Ikkita har xil AppContext obyektining teng emasligini tekshirish
    def test_app_context_inequality(self, mock_dependencies):
        """Har xil bog'liqliklar bilan yaratilgan ikki AppContext obyektining teng emasligini tekshiradi."""
        context1 = AppContext(**mock_dependencies)
        
        # Bitta bog'liqlikni o'zgartirib, ikkinchi kontekstni yaratamiz
        modified_deps = mock_dependencies.copy()
        modified_deps["config"] = MagicMock(name="AnotherConfigManager")
        context2 = AppContext(**modified_deps)
        
        assert context1 != context2

