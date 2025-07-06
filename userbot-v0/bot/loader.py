import asyncio
from functools import wraps
import importlib
import inspect
import pkgutil
import re
import sys
import html
from datetime import datetime
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Set, Tuple, Iterator

from loguru import logger
from telethon.events import NewMessage

from core.state import AppState
from core.config_manager import ConfigManager
from core.app_context import AppContext


PROJECT_ROOT = Path(__file__).parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))


from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from core.client_manager import ClientManager
    
class PluginManager:
    def __init__(self, client_manager: "ClientManager", state: AppState, config_manager: ConfigManager, plugins_dir_override: Optional[Path] = None, plugins_module_prefix: str = "bot.plugins"):
        self.client_manager = client_manager
        self.state = state
        self.config_manager = config_manager
        self._loaded_plugins: Dict[str, Dict[str, Any]] = {}
        self.app_context: Optional["AppContext"] = None
        self._error_registry: Dict[str, List[Dict[str, Any]]] = {}
        self.plugins_module_prefix = plugins_module_prefix

        if plugins_dir_override:
            self.plugins_dir: Path = plugins_dir_override
            logger.info(f"Test uchun plaginlar papkasi ishlatilmoqda: {self.plugins_dir}")
        else:
            self.plugins_dir: Path = self._get_plugins_directory()

        self._plugin_maps: Dict[str, str] = self._build_plugin_maps()
        logger.info(f"PluginManager tayyor. {len(self._plugin_maps)} ta plagin yo'li topildi.")
    
    
    def set_app_context(self, app_context: AppContext):
        """PluginManager ga AppContext ni o'rnatadi."""
        self.app_context = app_context
        logger.debug("PluginManager ga AppContext o'rnatildi.")

    def _get_plugins_directory(self) -> Path:
        """Plaginlar katalogini konfiguratsiyadan oladi yoki standart yo'lni qaytaradi."""
        try:

            plugins_dir_str = self.config_manager.get("PLUGINS_DIR")
            if plugins_dir_str:
                configured_path = Path(str(plugins_dir_str))
                if configured_path.is_absolute():
                    return configured_path
                return PROJECT_ROOT / configured_path
        except Exception as e:
            logger.warning(f"PLUGINS_DIR konfiguratsiyasini yuklashda xatolik: {e}. Standart yo'l ishlatiladi.")

        return PROJECT_ROOT / "bot" / "plugins"

    
    def _build_plugin_maps(self) -> Dict[str, str]:
        maps = {}
        plugins_dir = self.plugins_dir
        if not plugins_dir.is_dir():
            logger.warning(f"Plaginlar katalogi topilmadi: {plugins_dir}. Plaginlar yuklanmaydi.")
            return {}
        for path_obj in plugins_dir.rglob("*.py"):
            if path_obj.name.startswith("_"):
                continue
            full_module_path_rel = str(path_obj.relative_to(plugins_dir).with_suffix("")).replace("\\", ".").replace("/", ".")
            full_module_path = f"{self.plugins_module_prefix}.{full_module_path_rel}" if self.plugins_module_prefix else full_module_path_rel
            short_name = path_obj.stem
            relative_path_slash = str(path_obj.relative_to(plugins_dir).with_suffix("")).replace("\\", "/")
            relative_path_dot = full_module_path_rel
            maps[short_name] = full_module_path
            maps[relative_path_slash] = full_module_path
            maps[relative_path_dot] = full_module_path
            maps[full_module_path] = full_module_path
        return maps
    

    def _get_module_path(self, name: str) -> Optional[str]:
        """Kiritilgan nomdan to'liq Python modul yo'lini (`bot.plugins.admin.system`) qaytaradi."""

        normalized_name_dot = name.strip().replace('/', '.')
        normalized_name_slash = name.strip().replace('.', '/')

        return self._plugin_maps.get(name.strip()) or self._plugin_maps.get(normalized_name_dot) or self._plugin_maps.get(normalized_name_slash)

    def _register_error(self, module_path: str, error_message: str, exc: Optional[Exception] = None):
        """Xatoliklarni markazlashgan holda ro'yxatdan o'tkazadi."""
        error_info = {"timestamp": datetime.now().isoformat(), "error": error_message}
        self._error_registry.setdefault(module_path, []).append(error_info)
        if exc:
            logger.opt(exception=exc).error(f"'{module_path}' bilan bog'liq xatolik: {error_message}")
        else:
            logger.error(f"'{module_path}' bilan bog'liq xatolik: {error_message}")

    async def load_plugin(self, name: str) -> Tuple[bool, str]:
        """Plaginni nomi bo'yicha yuklaydi va uning vazifalarini ro'yxatdan o'tkazadi."""
        module_path = self._get_module_path(name)
        if not module_path:
            msg = f"❌ `{name}` nomli plagin topilmadi."
            self._register_error(name, msg)
            return False, msg

        if module_path in self._loaded_plugins:
            return False, f"ℹ️ `{name}` plagini allaqachon yuklangan."

        try:
            module = importlib.import_module(module_path)
            importlib.reload(module)
        except Exception as e:
            msg = f"❌ `{module_path}` plaginini yuklashda xatolik: `{e}`"
            self._register_error(module_path, msg, exc=e)
            return False, msg

        dependencies = getattr(module, "_dependencies_", [])
        if not await self._check_dependencies(module_path, dependencies):
            msg = f"❌ `{name}` plagini yuklanmadi: bog'liqliklar bajarilmadi."
            self._register_error(module_path, msg)
            return False, msg

        handlers = self._process_module_for_handlers(module)
        if not handlers:
            logger.debug(f"'{name}' plaginida hech qanday handler topilmadi.")

        # --- YANGI QISM: PLAGIN VAZIFALARINI RO'YXATDAN O'TKAZISH ---
        if hasattr(module, "register_plugin_tasks") and self.app_context:
            try:
                # `register_plugin_tasks` funksiyasiga AppContext'ni uzatamiz
                module.register_plugin_tasks(self.app_context)
                logger.debug(f"'{module_path}' plaginidagi vazifalar ro'yxatdan o'tkazildi.")
            except Exception as e:
                msg = f"❌ `{module_path}` plaginidagi vazifalarni ro'yxatdan o'tkazishda xato: {e}"
                self._register_error(module_path, msg, exc=e)
                # Vazifani ro'yxatdan o'tkazishda xato bo'lsa ham, plaginning qolgan qismi ishlashi mumkin
        # -------------------------------------------------------------

        self._loaded_plugins[module_path] = {"module": module, "handlers": handlers}
        self._add_handlers_to_clients(handlers)

        msg = f"✅ `{name}` plagini ({len(handlers)} ta buyruq) muvaffaqiyatli yuklandi."
        logger.info(msg)
        return True, msg

    async def _check_dependencies(self, plugin_name: str, dependencies: List[str]) -> bool:
        """Plagin bog'liqliklarini tekshiradi."""
        if not dependencies:
            return True

        missing_dependencies = []
        for dep_name in dependencies:
            dep_module_path = self._get_module_path(dep_name)
            if not dep_module_path or dep_module_path not in self._loaded_plugins:
                missing_dependencies.append(dep_name)

        if missing_dependencies:
            logger.error(f"Plagin '{plugin_name}' uchun bog'liqliklar topilmadi: {', '.join(missing_dependencies)}")
            return False
        return True

    def _process_module_for_handlers(self, module: Any) -> List[Dict[str, Any]]:
        """Modul ichidan @register_command va @userbot_handler handlerlarini topadi."""
        handlers_meta = []
        prefix = str(self.config_manager.get("PREFIX", "."))
        escaped_prefix = re.escape(prefix)

        for func_name, func in inspect.getmembers(module, inspect.isfunction):
            meta = None
            event_builder = None
            
            # Yangi `@register_command` tizimini tekshirish
            if hasattr(func, "_command_meta"):
                meta = getattr(func, "_command_meta", {})
                commands = meta.get("commands", [])
                if not commands: continue

                # Buyruqlar uchun regex pattern yaratish
                pattern_str = rf"^{escaped_prefix}(?:{'|'.join(commands)})(?: |$)(.*)"
                event_builder = NewMessage(outgoing=True, pattern=re.compile(pattern_str, re.DOTALL))
            
            # Eski `@userbot_handler` tizimini tekshirish
            elif hasattr(func, "_userbot_handler"):
                meta = getattr(func, "_userbot_meta", {})
                handler_args = getattr(func, "_handler_args", {})
                
                if 'listen' in handler_args:
                    event_builder = handler_args.pop('listen')
                else:
                    # Agar `listen` bo'lmasa, `NewMessage` yaratiladi
                    event_builder = NewMessage(**handler_args)

            # Agar handler topilsa, uni ro'yxatga qo'shamiz
            if meta and event_builder:
                module_prefix_to_remove = f"{self.plugins_module_prefix}."
                clean_module_name = module.__name__.removeprefix(module_prefix_to_remove)
                command_id = f"{clean_module_name.replace('.', '/')}:{func_name}"
                
                wrapped_func = self._create_context_wrapper(func, module.__name__)

                handlers_meta.append({
                    "wrapped_func": wrapped_func, 
                    "event_builder": event_builder, 
                    "command_id": command_id, 
                    "meta": meta
                })
        return handlers_meta


    

    def _add_handlers_to_clients(self, handlers: List[Dict[str, Any]]):
        """Topilgan handlerlarni barcha Telethon klientlariga qo'shadi."""
        clients = self.client_manager.get_all_clients()
        for handler in handlers:

            is_disabled = self.state.get(f"commands.disabled.{handler['command_id']}", False)
            if not is_disabled:
                for client in clients:
                    client.add_event_handler(handler["wrapped_func"], handler["event_builder"])

    async def unload_plugin(self, name: str) -> Tuple[bool, str]:
        """Plaginni o'chiradi va uning handlerlarini klientlardan olib tashlaydi."""
        module_path = self._get_module_path(name)
        if not module_path or module_path not in self._loaded_plugins:
            return False, f"⚠️ `{name}` plagini topilmadi yoki yuklanmagan."
        plugin_data = self._loaded_plugins.pop(module_path)
        clients = self.client_manager.get_all_clients()
        for handler in plugin_data.get("handlers", []):
            for client in clients:
                if handler.get("event_builder"):
                    client.remove_event_handler(handler["wrapped_func"], handler["event_builder"])
        msg = f"✅ `{name}` plagini muvaffaqiyatli o'chirildi."
        logger.success(msg)
        return True, msg
    

    async def reload_plugin(self, name: str) -> Tuple[bool, str]:
        """Plaginni o'chirib, qayta yuklaydi."""
        logger.info(f"'{name}' plaginini qayta yuklash boshlandi...")
        unload_success, unload_msg = await self.unload_plugin(name)

        if not unload_success and "yuklanmagan" not in unload_msg:
            self._register_error(name, f"Plaginni qayta yuklashda o'chirish xatosi: {unload_msg}")
            return unload_success, unload_msg

        load_success, load_msg = await self.load_plugin(name)

        if load_success:
            module_path = self._get_module_path(name)
            if module_path and module_path in self._loaded_plugins:
                module = self._loaded_plugins[module_path]["module"]
                if hasattr(module, "_on_reload") and inspect.iscoroutinefunction(module._on_reload):

                    if self.app_context:
                        try:
                            await module._on_reload(self.app_context)
                            logger.info(f"'{name}' plaginining _on_reload funksiyasi bajarildi.")
                        except Exception as e:
                            msg = f"'{name}' plaginining _on_reload funksiyasida xatolik: {e}"
                            self._register_error(name, msg, exc=e)
                            return False, f"❌ `{name}` plaginini qayta yuklashda _on_reload xatosi: `{e}`"
                    else:
                        logger.warning(f"'{name}' plaginining _on_reload funksiyasiga AppContext uzatilmadi, chunki u hali o'rnatilmagan.")

        return load_success, load_msg

    async def load_all_plugins(self):
        """`plugins` papkasidagi barcha topilgan plaginlarni yuklaydi."""
        logger.info("Barcha plaginlarni yuklash boshlandi...")
        unique_paths = sorted(list(set(self._plugin_maps.values())))
        successful_loads = 0
        total_handlers = 0
        for path in unique_paths:
            success, _ = await self.load_plugin(path)
            if success:
                successful_loads += 1

        for plugin_data in self._loaded_plugins.values():
            total_handlers += len(plugin_data.get("handlers", []))

        logger.success(f"✅ Barcha plaginlar yuklandi: {successful_loads}/{len(unique_paths)} moduldan {total_handlers} ta handler.")

    async def toggle_command(self, command_id: str, enable: bool) -> Tuple[bool, str]:
        """Berilgan ID bo'yicha buyruqni yoqadi yoki o'chiradi."""
        handler_data = self.get_handler_by_id(command_id)
        if not handler_data:
            return False, f"❌ `{command_id}` IDli buyruq topilmadi."

        clients = self.client_manager.get_all_clients()
        wrapped_func = handler_data["wrapped_func"]
        event_builder = handler_data["event_builder"]

        current_state_disabled = self.state.get(f"commands.disabled.{command_id}", False)

        action_text = ""
        is_already_set = False

        if enable:
            action_text = "yoqildi"
            if not current_state_disabled:
                is_already_set = True
            else:
                await self.state.set(f"commands.disabled.{command_id}", False, persistent=True)
                for client in clients:
                    client.add_event_handler(wrapped_func, event_builder)
        else:
            action_text = "o'chirildi"
            if current_state_disabled:
                is_already_set = True
            else:
                await self.state.set(f"commands.disabled.{command_id}", True, persistent=True)
                for client in clients:
                    client.remove_event_handler(wrapped_func, event_builder)

        if is_already_set:
            return False, f"ℹ️ Buyruq allaqachon {action_text} holatida."

        return True, f"✅ Buyruq `{html.escape(command_id)}` muvaffaqiyatli {action_text}."

    def _create_context_wrapper(self, func: Callable, module_path: str) -> Callable:
        """
        Handler funksiyasini `AppContext` bilan ta'minlaydigan 'o'ram' (wrapper).
        Funksiya signaturasini tekshirib, agar 'context: AppContext' mavjud bo'lsa,
        uni avtomatik ravishda uzatadi.
        """
        @wraps(func)
        async def wrapper(event: NewMessage.Event):
            try:
                # Funksiya argumentlarini tekshirish
                sig = inspect.signature(func)
                if 'context' in sig.parameters:
                    # Agar `context` parametri bo'lsa, AppContext'ni uzatamiz
                    await func(event, context=self.app_context)
                else:
                    # Aks holda, faqat `event` ni uzatamiz (eski plaginlar uchun)
                    await func(event)
            except Exception as e:
                error_info = {"timestamp": datetime.now().isoformat(), "error": f"{type(e).__name__}: {e}"}
                self._error_registry.setdefault(module_path, []).append(error_info)
                logger.opt(exception=e).error(f"'{module_path}' plaginida xatolik yuz berdi.")

        return wrapper


    def _create_error_tracking_wrapper(self, func: Callable, module_path: str) -> Callable:
        """Handler ishlaganda yuzaga keladigan xatoliklarni ushlab oluvchi 'o'ram' (wrapper)."""
        
        @wraps(func)
        async def wrapper(event: NewMessage.Event):
            try:
                await func(event)
            except Exception as e:
                error_info = {"timestamp": datetime.now().isoformat(), "error": f"{type(e).__name__}: {e}"}
                self._error_registry.setdefault(module_path, []).append(error_info)
                logger.opt(exception=e).error(f"'{module_path}' plaginida xatolik yuz berdi.")

        return wrapper

    def iter_handlers(self) -> Iterator[Dict[str, Any]]:
        """Barcha yuklangan handlerlar bo'ylab iteratsiya qiladi."""
        for plugin_data in self._loaded_plugins.values():
            yield from plugin_data.get("handlers", [])

    def get_handler_by_id(self, command_id: str) -> Optional[Dict[str, Any]]:
        """Unikal ID bo'yicha handlerni topadi."""
        for handler in self.iter_handlers():
            if handler.get("command_id") == command_id:
                return handler
        return None


    def get_all_categories(self) -> List[str]:
        """Barcha plaginlardan mavjud bo'lgan unikal kategoriyalar ro'yxatini qaytaradi."""
        categories: Set[str] = set()
        for handler in self.iter_handlers():
            if category := handler.get("meta", {}).get("category"):
                categories.add(category)
        return sorted(list(categories))

    def get_commands_by_category(self, category_name: str) -> List[Dict[str, Any]]:
        """Berilgan kategoriya bo'yicha barcha buyruqlar ma'lumotlarini qaytaradi."""
        commands: List[Dict[str, Any]] = []
        for handler in self.iter_handlers():
            meta = handler.get("meta", {})
            if meta.get("category") == category_name:
                commands.append(meta)
        return commands

    def get_command(self, command_name: str) -> Optional[Dict[str, Any]]:
        """Nomi bo'yicha bitta buyruq ma'lumotlarini topadi."""
        clean_command_name = command_name.lstrip(self.config_manager.get("PREFIX", ".")).lower()
        for handler in self.iter_handlers():
            meta = handler.get("meta", {})
            if clean_command_name in meta.get("commands", []):
                return meta
        return None
