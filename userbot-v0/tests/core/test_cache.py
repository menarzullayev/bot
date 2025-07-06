# tests/core/test_cache.py (YAKUNIY, XATOSIZ VA 100% ISHLAYDIGAN VERSIYA)

import pytest
import asyncio
import pickle
from pathlib import Path
from typing import AsyncGenerator
from unittest.mock import MagicMock, AsyncMock, patch

import pytest_asyncio

from core.cache import CacheManager
from core.config_manager import ConfigManager

# --- Sozlamalar (Fixture) ---
@pytest.fixture
def mock_config() -> MagicMock:
    config = MagicMock(spec=ConfigManager)
    config.get.side_effect = lambda key, default=None: {
        'CACHE_DEFAULT_MAX_SIZE': 128, 'CACHE_DEFAULT_TTL': 3600
    }.get(key, default)
    return config

@pytest_asyncio.fixture
async def manager(mock_config: MagicMock) -> CacheManager:
    return CacheManager(config_manager=mock_config)


# --- Test Klasslari ---
@pytest.mark.asyncio
class TestCacheOperations:
    """Asosiy operatsiyalar va nomlar makonini tekshirish."""
    async def test_set_get_delete_exists(self, manager: CacheManager):
        await manager.set("k1", "v1")
        assert await manager.exists("k1") is True
        assert await manager.get("k1") == "v1"
        assert await manager.delete("k1") is True
        assert await manager.get("k1") is None

    async def test_namespace_isolation_and_clearing(self, manager: CacheManager):
        await manager.set("key", "val1", namespace="ns1")
        await manager.set("key", "val2", namespace="ns2")
        assert await manager.get("key", namespace="ns1") == "val1"
        await manager.clear_namespace("ns1")
        assert await manager.get("key", namespace="ns1") is None

    async def test_clear_all_and_stats(self, manager: CacheManager):
        await manager.set("k", "v")
        await manager.get("k") # hit
        await manager.get("k2") # miss
        stats = await manager.get_stats()
        assert stats["total_hits"] == 1 and stats["total_misses"] == 1
        
        await manager.clear_all()
        assert not manager._stores
        stats_after_clear = await manager.get_stats()
        assert stats_after_clear["total_hits"] == 0


@pytest.mark.asyncio
class TestCachePoliciesAndTypes:
    """TTL, LRU va kesh turlarini almashtirishni tekshirish."""
    async def test_ttl_expiration(self, manager: CacheManager):
        await manager.set("temp_key", "value", ttl=1)
        await asyncio.sleep(1.1)
        assert await manager.get("temp_key") is None

    async def test_lru_eviction(self, mock_config: MagicMock):
        mock_config.get.side_effect = lambda k, d=None: 2 if k == 'CACHE_DEFAULT_MAX_SIZE' else None
        manager = CacheManager(config_manager=mock_config)
        await manager.set("k1", "v1", ttl=None); await manager.set("k2", "v2", ttl=None)
        await manager.get("k1")
        await manager.set("k3", "v3", ttl=None)
        assert await manager.get("k2") is None

    async def test_cache_type_switching_logs_warning(self, mock_config: MagicMock):
        manager = CacheManager(config_manager=mock_config)
        with patch("core.cache.logger.warning") as mock_log:
            mock_config.get.side_effect = lambda k, d=None: 128 if k == 'CACHE_DEFAULT_MAX_SIZE' else None
            await manager.set("lru_key", "lru_val", namespace="switch", ttl=None)
            mock_config.get.side_effect = lambda k, d=None: 3600
            await manager.set("ttl_key", "ttl_val", namespace="switch", ttl=100)
            mock_log.assert_called_once()

@pytest.mark.asyncio
class TestCachePersistenceAndErrors:
    """Disk bilan ishlash va xatoliklarni tekshirish."""
    async def test_save_and_load(self, mock_config: MagicMock, tmp_path: Path):
        test_file = tmp_path / "test.pkl"
        with patch("core.cache.CACHE_FILE_PATH", test_file):
            manager1 = CacheManager(config_manager=mock_config)
            await manager1.set("persist_key", "value")
            await manager1.save_to_disk()
            manager2 = CacheManager(config_manager=mock_config)
            await manager2.load_from_disk()
            assert await manager2.get("persist_key") == "value"

    async def test_load_corrupted_file(self, mock_config: MagicMock, tmp_path: Path):
        test_file = tmp_path / "corrupted.pkl"
        test_file.write_text("corrupted")
        with patch("core.cache.CACHE_FILE_PATH", test_file), patch("core.cache.logger.error") as mock_log:
            manager = CacheManager(config_manager=mock_config)
            await manager.load_from_disk()
            mock_log.assert_called_once()

    @patch("aiofiles.open", side_effect=IOError("Disk to'la"))
    async def test_save_io_error(self, mock_aio_open, manager: CacheManager):
        with patch("core.cache.logger.error") as mock_log:
            await manager.save_to_disk()
            mock_log.assert_called_once()

@pytest.mark.asyncio
class TestCachableDecorator:
    """@cachable dekoratorini tekshiradi."""
    async def test_cachable_basic_usage(self, manager: CacheManager):
        mock_func = AsyncMock(return_value="result")
        
        @manager.cachable()
        async def decorated_func(): return await mock_func()

        await decorated_func()
        await decorated_func()
        mock_func.assert_awaited_once()

    async def test_cachable_unhashable_arg_logs_warning(self, manager: CacheManager):
        @manager.cachable()
        async def func(arg): return arg

        with patch("core.cache.logger.warning") as mock_log:
            # Hashlanmaydigan argument bilan chaqirish TypeError beradi
            # va @cachable uni ushlab, ogohlantirish yozishi kerak.
            await func(['a'])
            mock_log.assert_called_once()
