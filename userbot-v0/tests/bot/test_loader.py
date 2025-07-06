import sys
import asyncio
from pathlib import Path
from unittest.mock import MagicMock, AsyncMock, patch
import importlib

import pytest
import pytest_asyncio
from telethon.events import NewMessage


@pytest.fixture(scope="session", autouse=True)
def setup_project_root():
    project_root = Path(__file__).parent.parent.parent
    if str(project_root) not in sys.path:
        sys.path.insert(0, str(project_root))


@pytest.fixture
def mock_client_manager():
    manager = MagicMock()
    client = MagicMock()
    client.add_event_handler = MagicMock()
    client.remove_event_handler = MagicMock()
    manager.get_all_clients.return_value = [client]
    return manager


@pytest.fixture
def mock_state():
    from core.state import AppState

    state = AsyncMock(spec=AppState)
    state.get.return_value = False
    state.set = AsyncMock()
    return state


@pytest.fixture
def mock_config_manager():
    config = MagicMock()
    config.get.side_effect = lambda key, default=None: {"PREFIX": "."}.get(key, default)
    return config


@pytest.fixture
def plugins_dir(tmp_path, monkeypatch):
    """Vaqtinchalik plaginlar papkasini yaratadi va test muhitini to'liq izolyatsiya qiladi."""
    plugins_path = tmp_path / "plugins"
    admin_path = plugins_path / "admin"
    admin_path.mkdir(parents=True)
    (plugins_path / "__init__.py").touch()
    (admin_path / "__init__.py").touch()

    monkeypatch.syspath_prepend(str(tmp_path))

    for module in list(sys.modules):
        if module.startswith("plugins"):
            del sys.modules[module]

    yield plugins_path


@pytest_asyncio.fixture
async def manager(plugins_dir, mock_client_manager, mock_state, mock_config_manager):
    """Har bir test uchun yangi va toza PluginManager yaratadi."""
    from bot.loader import PluginManager

    importlib.reload(sys.modules['bot.loader'])

    pm = PluginManager(client_manager=mock_client_manager, state=mock_state, config_manager=mock_config_manager, plugins_dir_override=plugins_dir, plugins_module_prefix="plugins")
    pm.set_app_context(MagicMock())
    yield pm


@pytest.mark.asyncio
async def test_plugin_discovery_and_paths(manager, plugins_dir):
    (plugins_dir / "ping.py").touch()
    (plugins_dir / "admin" / "system.py").touch()
    (plugins_dir / "_internal.py").touch()
    manager._plugin_maps = manager._build_plugin_maps()
    assert manager._get_module_path("ping") == "plugins.ping"
    assert manager._get_module_path("admin/system") == "plugins.admin.system"
    assert manager._get_module_path("_internal") is None
    assert len(manager._plugin_maps) == 6


@pytest.mark.asyncio
async def test_load_and_unload_plugin(manager, plugins_dir):
    (plugins_dir / "ping.py").write_text(
        """
def userbot_handler(**kwargs):
    def d(f): f._userbot_handler=True; f._handler_args=kwargs; f.__module__="plugins.ping"; return f
    return d
@userbot_handler()
async def p(e): pass
"""
    )
    manager._plugin_maps = manager._build_plugin_maps()
    success, msg = await manager.load_plugin("ping")
    assert success, msg
    assert "plugins.ping" in manager._loaded_plugins
    success, msg = await manager.unload_plugin("ping")
    assert success, msg
    assert "plugins.ping" not in manager._loaded_plugins


@pytest.mark.asyncio
async def test_reload_plugin(manager, plugins_dir):
    """4. Plaginni qayta yuklashni tekshirish."""

    plugin_code = """
def userbot_handler(**kw):
    def d(f):f._userbot_handler=True;f._handler_args=kw;return f
    return d
@userbot_handler()
async def test(e): pass
"""
    (plugins_dir / "reload.py").write_text(plugin_code)
    manager._plugin_maps = manager._build_plugin_maps()

    await manager.load_plugin("reload")

    client = manager.client_manager.get_all_clients()[0]
    client.reset_mock()

    success, msg = await manager.reload_plugin("reload")

    assert success, msg
    client.remove_event_handler.assert_called_once()
    client.add_event_handler.assert_called_once()


@pytest.mark.asyncio
async def test_dependency_handling(manager, plugins_dir):
    (plugins_dir / "core.py").write_text("")
    (plugins_dir / "app.py").write_text('_dependencies_=["core"]')
    manager._plugin_maps = manager._build_plugin_maps()

    success, msg = await manager.load_plugin("core")
    assert success, msg

    success, msg = await manager.load_plugin("app")
    assert success, msg


@pytest.mark.asyncio
async def test_dependency_failure(manager, plugins_dir):
    (plugins_dir / "app.py").write_text('_dependencies_=["non_existent_core"]')
    manager._plugin_maps = manager._build_plugin_maps()
    success, msg = await manager.load_plugin("app")
    assert not success and "bog'liqliklar bajarilmadi" in msg


@pytest.mark.asyncio
async def test_handler_registration_and_toggle(manager, plugins_dir):
    """7. Handler'ni ro'yxatga olish va o'chirib-yoqish."""
    (plugins_dir / "cmd.py").write_text(
        """
def userbot_handler(**kw):
    def d(f):f._userbot_handler=True;f._handler_args=kw;f.__module__="plugins.cmd";return f
    return d
@userbot_handler(pattern=r"ping")
async def p(e): pass
"""
    )
    manager._plugin_maps = manager._build_plugin_maps()
    await manager.load_plugin("cmd")

    handler = manager.get_handler_by_id("cmd:p")
    assert handler is not None

    client = manager.client_manager.get_all_clients()[0]
    client.add_event_handler.assert_called_once_with(handler['wrapped_func'], handler['event_builder'])

    manager.state.get.return_value = False
    await manager.toggle_command("cmd:p", enable=False)
    client.remove_event_handler.assert_called_once_with(handler['wrapped_func'], handler['event_builder'])

    client.add_event_handler.reset_mock()
    manager.state.get.return_value = True
    await manager.toggle_command("cmd:p", enable=True)
    client.add_event_handler.assert_called_once_with(handler['wrapped_func'], handler['event_builder'])


@pytest.mark.asyncio
async def test_error_wrapper(manager, plugins_dir):
    """8. Handlerdagi xatolikni ushlab qolish."""
    (plugins_dir / "fail.py").write_text(
        """
def userbot_handler(**kw):
    def d(f):f._userbot_handler=True;f._handler_args=kw;f.__module__="plugins.fail";return f
    return d
@userbot_handler()
async def fail_cmd(e): raise ValueError("test error")
"""
    )
    manager._plugin_maps = manager._build_plugin_maps()
    await manager.load_plugin("fail")

    handler = manager.get_handler_by_id("fail:fail_cmd")
    assert handler is not None
    await handler["wrapped_func"](MagicMock())
    assert "plugins.fail" in manager._error_registry
    assert "ValueError: test error" in manager._error_registry["plugins.fail"][0]["error"]


@pytest.mark.asyncio
async def test_prefix_is_added_to_pattern(manager, plugins_dir):
    """9. Buyruq matniga prefiks avtomatik qo'shilishi."""
    (plugins_dir / "prefix.py").write_text("""
def userbot_handler(**kw):
    def d(f):f._userbot_handler=True;f._handler_args=kw;f.__module__="plugins.prefix";return f
    return d
@userbot_handler(pattern="test")
async def p(e): pass
""")
    manager._plugin_maps = manager._build_plugin_maps()
    await manager.load_plugin("prefix")
    handler_data = manager.get_handler_by_id("prefix:p")
    assert handler_data is not None
    
    # YAKUNIY O'ZGARISH: Patternni to'g'ridan-to'g'ri o'zimiz saqlagan joydan olamiz.
    pattern_obj = handler_data["compiled_pattern"]
    
    assert pattern_obj is not None, "Kompilyatsiya qilingan pattern topilmadi"
    assert hasattr(pattern_obj, 'pattern'), "Pattern obyektida .pattern atributi yo'q"
    assert pattern_obj.pattern.startswith(r"^\.") # Regex boshi `^` ham tekshirildi
    assert "test" in pattern_obj.pattern


@pytest.mark.asyncio
async def test_reload_hook_is_called(manager, plugins_dir):
    """10. Qayta yuklashda _on_reload funksiyasi chaqirilishini tekshirish."""

    (plugins_dir / "hook.py").write_text(
        """
async def _on_reload(ctx):
    ctx.hook_called_mock()
"""
    )
    manager._plugin_maps = manager._build_plugin_maps()
    await manager.load_plugin("hook")

    manager.app_context.hook_called_mock = MagicMock()

    await manager.reload_plugin("hook")

    manager.app_context.hook_called_mock.assert_called_once()
