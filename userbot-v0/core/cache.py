# userbot-v0/core/cache.py faylining to'liq va yangilangan versiyasi

import asyncio
import pickle
from functools import wraps
from pathlib import Path
from typing import Any, Callable, Coroutine, Dict, Generic, Optional, TypeVar, cast, Hashable

import aiofiles
from cachetools import LRUCache, TTLCache
from loguru import logger

from .config import BASE_DIR
from typing import TYPE_CHECKING
if TYPE_CHECKING:
    from core.config_manager import ConfigManager


VT = TypeVar('VT')

CACHE_FILE_PATH = BASE_DIR / "data" / "cache.pkl"


class CacheManager(Generic[VT]):
    """
    Asinxron, TTL va LRU siyosatlarini qo'llab-quvvatlaydigan, nomlar makoniga
    ega, diskka saqlanadigan markazlashtirilgan kesh menejeri.
    """

    def __init__(self, config_manager: 'ConfigManager'):
        self._config = config_manager
        self._default_max_size: int = self._config.get("CACHE_DEFAULT_MAX_SIZE", 512)
        self._default_ttl: Optional[int] = self._config.get("CACHE_DEFAULT_TTL", 300)
        self._stores: Dict[str, LRUCache | TTLCache] = {}
        self._lock = asyncio.Lock()
        self._hits = 0
        self._misses = 0
        logger.info(f"CacheManager ishga tayyor. Standart hajm: {self._default_max_size}, TTL: {self._default_ttl}s")

    async def _get_store(self, namespace: str, ttl: Optional[int] = -1) -> LRUCache | TTLCache:
        async with self._lock:
            current_store = self._stores.get(namespace)
            effective_ttl = self._default_ttl if ttl == -1 else ttl

            is_new_store = current_store is None
            is_ttl_to_lru = isinstance(current_store, TTLCache) and effective_ttl is None
            is_lru_to_ttl = isinstance(current_store, LRUCache) and effective_ttl is not None

            if is_new_store or is_ttl_to_lru or is_lru_to_ttl:
                if is_ttl_to_lru:
                    logger.warning(f"'{namespace}' uchun kesh turi TTLCache'dan LRUCache'ga o'zgartirilmoqda.")
                    self._stores[namespace] = LRUCache(maxsize=self._default_max_size)
                elif is_lru_to_ttl:
                    logger.warning(f"'{namespace}' uchun kesh turi LRUCache'dan TTLCache'ga o'zgartirilmoqda.")
                    self._stores[namespace] = TTLCache(
                        maxsize=self._default_max_size,
                        ttl=float(effective_ttl if effective_ttl is not None else 300)
                    )
                else:
                    if effective_ttl is not None:
                        self._stores[namespace] = TTLCache(
                            maxsize=self._default_max_size,
                            ttl=float(effective_ttl)
                        )
                    else:
                        self._stores[namespace] = LRUCache(maxsize=self._default_max_size)
            
            elif isinstance(current_store, TTLCache) and effective_ttl is not None and current_store.ttl != effective_ttl:
                self._stores[namespace] = TTLCache(maxsize=self._default_max_size, ttl=effective_ttl)

            return self._stores[namespace]

    async def get(self, key: Hashable, namespace: str = "default", default: Any = None) -> Optional[VT]:
        if namespace not in self._stores:
            self._misses += 1
            return default
        store = await self._get_store(namespace)
        async with self._lock:
            value = store.get(key)
            if value is not None:
                self._hits += 1
                return cast(VT, value)
            self._misses += 1
            return default
            
    async def set(self, key: Hashable, value: VT, namespace: str = "default", ttl: Optional[int] = -1) -> None:
        store = await self._get_store(namespace, ttl)
        async with self._lock:
            store[key] = value
            
    async def delete(self, key: Hashable, namespace: str = "default") -> bool:
        if namespace not in self._stores: return False
        store = await self._get_store(namespace)
        async with self._lock:
            if key in store:
                del store[key]
                return True
            return False

    async def exists(self, key: Hashable, namespace: str = "default") -> bool:
        if namespace not in self._stores: return False
        store = await self._get_store(namespace)
        async with self._lock:
            return key in store

    async def clear_namespace(self, namespace: str) -> bool:
        async with self._lock:
            if namespace in self._stores:
                del self._stores[namespace]
                return True
            return False

    async def clear_all(self) -> None:
        async with self._lock:
            self._stores.clear()
            self._hits = 0
            self._misses = 0

    async def load_from_disk(self) -> None:
        if not CACHE_FILE_PATH.exists():
            return
        try:
            async with aiofiles.open(CACHE_FILE_PATH, 'rb') as f:
                pickled_data = await f.read()
                data = await asyncio.to_thread(pickle.loads, pickled_data)
            async with self._lock:
                self._stores = data.get('_stores', {})
        except Exception as e:
            logger.error(f"Keshni diskdan yuklashda xatolik: {e}", exc_info=True)
            await self.clear_all()

    async def save_to_disk(self) -> None:
        CACHE_FILE_PATH.parent.mkdir(parents=True, exist_ok=True)
        try:
            data_to_save = {'_stores': self._stores, '_hits': self._hits, '_misses': self._misses}
            pickled_data = await asyncio.to_thread(pickle.dumps, data_to_save)
            async with aiofiles.open(CACHE_FILE_PATH, 'wb') as f:
                await f.write(pickled_data)
        except Exception as e:
            logger.error(f"Keshni diskka saqlashda xatolik: {e}", exc_info=True)

    def _create_cache_key(self, func: Callable[..., Coroutine[Any, Any, Any]], args: Any, kwargs: Any) -> Hashable:
        hashable_kwargs = frozenset(kwargs.items())
        key_tuple = (func.__module__, func.__name__, args, hashable_kwargs)
        hash(key_tuple) # Agar key_tuple hashlanmaydigan elementlarni o'z ichiga olsa, bu yerda TypeError yuzaga keladi.
        return key_tuple

    def cachable(
        self,
        ttl: Optional[int] = -1,
        namespace: str = "default",
        condition: Optional[Callable[[Any], bool]] = None,
        cache_key_fn: Optional[Callable[..., Hashable]] = None
    ) -> Callable[[Callable[..., Coroutine[Any, Any, Any]]], Callable[..., Coroutine[Any, Any, Any]]]:
        def decorator(func: Callable[..., Coroutine[Any, Any, Any]]) -> Callable[..., Coroutine[Any, Any, Any]]:
            @wraps(func)
            async def wrapper(*args: Any, **kwargs: Any) -> Any:
                try:
                    key = cache_key_fn(*args, **kwargs) if cache_key_fn else self._create_cache_key(func, args, kwargs)
                except TypeError:
                    # Kesh kalitini yaratishda TypeError yuzaga kelsa, ogohlantirishni logga yozing
                    logger.warning(f"Kesh kalitini yaratishda TypeError: '{func.__name__}' funksiyasi hashlanmaydigan argumentlarga ega. Keshlanish bekor qilindi.")
                    return await func(*args, **kwargs)

                cached_value = await self.get(key, namespace)
                if cached_value is not None:
                    return cached_value

                result = await func(*args, **kwargs)

                if condition is None or condition(result):
                    await self.set(key, result, namespace, ttl)
                return result
            return wrapper
        return decorator

    async def get_stats(self) -> Dict[str, Any]:
        async with self._lock:
            return {"total_hits": self._hits, "total_misses": self._misses}

