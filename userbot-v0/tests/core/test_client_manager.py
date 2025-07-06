# userbot-v0/tests/core/test_client_manager.py

import pytest
import asyncio
from unittest.mock import MagicMock, AsyncMock, patch, call

import pytest_asyncio
from telethon import TelegramClient
from telethon.tl.types import User

# Test qilinadigan klasslar va obyektlar
from core.client_manager import ClientManager
from core.database import AsyncDatabase
from core.state import AppState
from core.config_manager import ConfigManager

pytestmark = pytest.mark.asyncio


# --- Fixtures (Test uchun tayyorgarlik) ---

@pytest.fixture
def mock_db() -> AsyncMock:
    """Soxta (mock) AsyncDatabase obyektini yaratadi."""
    return AsyncMock(spec=AsyncDatabase)

@pytest.fixture
def mock_state() -> AsyncMock:
    """Soxta (mock) AppState obyektini yaratadi."""
    return AsyncMock(spec=AppState)

@pytest.fixture
def mock_config() -> MagicMock:
    """Soxta (mock) ConfigManager obyektini yaratadi."""
    return MagicMock(spec=ConfigManager)

@pytest_asyncio.fixture
async def client_manager(
    mock_db: AsyncMock,
    mock_state: AsyncMock,
    mock_config: MagicMock,
) -> ClientManager:
    """Har bir test uchun yangi, toza ClientManager obyektini yaratadi."""
    manager = ClientManager(database=mock_db, config=mock_config, state=mock_state)
    return manager

@pytest.fixture
def mock_telethon_client_instance() -> AsyncMock: 
    """Soxta (mock) TelegramClient obyektini yaratadi."""
    client = AsyncMock(spec=TelegramClient)
    
    # `is_connected` metodi Telethonda sinxron bo'lganligi sababli,
    # uni `MagicMock` bilan sinxron tarzda mocklaymiz
    client.is_connected = MagicMock(return_value=True) 

    # is_user_authorized metodining mockini sozlaymiz
    client.is_user_authorized = AsyncMock() 

    # Soxta 'me' obyektini qaytaramiz
    me_user = AsyncMock(spec=User)
    me_user.id = 12345
    me_user.first_name = "Test"
    me_user.phone = "998901234567" 
    client.get_me.return_value = me_user

    # disconnect() metodi endi to'g'ridan-to'g'ri AsyncMock obyektining o'zi bo'lishi kerak.
    client.disconnect = AsyncMock(return_value=None) 

    # client.disconnected atributi Future qaytaradi (Telethonning asl xulqi)
    future_disconnected = asyncio.Future()
    future_disconnected.set_result(None)
    client.disconnected = future_disconnected


    # Mock send_code_request and sign_in to return a mock User object
    async def mock_send_code_request_effect(*args, **kwargs):
        pass 

    async def mock_sign_in_effect(*args, **kwargs):
        client.is_user_authorized.return_value = True 
        return me_user

    client.send_code_request.side_effect = mock_send_code_request_effect
    client.sign_in.side_effect = mock_sign_in_effect

    return client

# --- Test Klasslari ---

class TestClientManager:
    """ClientManager klassining funksionalligini test qilish."""

    async def test_initialization(self, client_manager: ClientManager):
        """1. ClientManager to'g'ri yaratilganini tekshirish."""
        assert client_manager._db is not None
        assert client_manager._config is not None
        assert client_manager._state is not None
        assert isinstance(client_manager._clients, dict)

    @patch('core.client_manager.TelegramClient')
    async def test_start_single_client_success(
        self, MockTelethonClient_Class: MagicMock, client_manager: ClientManager, mock_db: AsyncMock, mock_telethon_client_instance: AsyncMock
    ):
        """2. Bitta klientni muvaffaqiyatli ishga tushirish."""
        MockTelethonClient_Class.return_value = mock_telethon_client_instance
        mock_telethon_client_instance.is_user_authorized.return_value = True

        mock_db.fetchone.return_value = {'id': 1, 'session_name': 'test_session', 'api_id': 123, 'api_hash': 'abc', 'is_active': True}


        account_data = {'id': 1, 'session_name': 'test_session', 'api_id': 123, 'api_hash': 'abc', 'is_active': True}
        result = await client_manager.start_single_client(account_data)

        assert result is True
        mock_telethon_client_instance.connect.assert_awaited_once()
        mock_telethon_client_instance.is_user_authorized.assert_awaited_once()
        mock_telethon_client_instance.get_me.assert_awaited_once()
        assert client_manager.get_client(1) is not None
        mock_db.execute.assert_called_with(
            "UPDATE accounts SET status = ?, telegram_id = ? WHERE id = ?",
            ('running', 12345, 1)
        )
        mock_telethon_client_instance.disconnect.assert_not_called()


    @patch('core.client_manager.TelegramClient') 
    async def test_start_all_clients(
        self, MockTelethonClient_Class: MagicMock, client_manager: ClientManager, mock_db: AsyncMock, mock_telethon_client_instance: AsyncMock
    ):
        """3. Barcha klientlarni ommaviy ishga tushirish."""
        MockTelethonClient_Class.return_value = mock_telethon_client_instance

        accounts = [
            {'id': 1, 'session_name': 'test1', 'api_id': 111, 'api_hash': 'aaa', 'is_active': True},
            {'id': 2, 'session_name': 'test2', 'api_id': 222, 'api_hash': 'bbb', 'is_active': True},
        ]
        mock_db.fetchall.return_value = accounts

        mock_telethon_client_instance.is_user_authorized.return_value = True

        with patch.object(client_manager, '_setup_auto_reconnect', new_callable=MagicMock) as mock_setup_auto_reconnect:
            try: 
                await client_manager.start_all_clients()

                mock_setup_auto_reconnect.assert_has_calls([
                    call(mock_telethon_client_instance, 1),
                    call(mock_telethon_client_instance, 2)
                ], any_order=False)

                assert MockTelethonClient_Class.call_count == 2
                # start_single_client ichida klientlar _clients ga qo'shiladi
                assert len(client_manager.get_all_clients()) == 2 

            finally:
                # Test tugagandan so'ng klientlarni to'g'ri to'xtatishni ta'minlaymiz
                await client_manager.stop_all_clients() 
                
        # stop_all_clients chaqirilgandan keyin _clients bo'sh bo'lishi kerak
        assert len(client_manager.get_all_clients()) == 0 
        # disconnect metodi stop_all_clients tomonidan ikki marta chaqirilishi kerak
        assert mock_telethon_client_instance.disconnect.call_count == 2 
        mock_telethon_client_instance.connect.assert_called()
        mock_telethon_client_instance.get_me.assert_called()
        mock_db.execute.assert_called() 

    async def test_stop_all_clients(self, client_manager: ClientManager, mock_db: AsyncMock, mock_telethon_client_instance: AsyncMock):
        """4. Barcha klientlarni to'xtatish."""
        mock_telethon_client_instance.is_connected.return_value = True
        client_manager._clients = {1: mock_telethon_client_instance, 2: mock_telethon_client_instance}

        await client_manager.stop_all_clients()

        assert mock_telethon_client_instance.disconnect.call_count == 2
        assert len(client_manager.get_all_clients()) == 0
        mock_db.execute.assert_called_once_with(
            "UPDATE accounts SET status = 'stopped' WHERE id IN (?,?) AND status = 'running'", 
            (1, 2)
        )

    async def test_get_client(self, client_manager: ClientManager, mock_telethon_client_instance: AsyncMock):
        """5. Ishlayotgan klientni ID orqali olish."""
        client_manager._clients[1] = mock_telethon_client_instance

        client = client_manager.get_client(1)
        assert client == mock_telethon_client_instance
        assert client_manager.get_client(999) is None

    async def test_start_client_fails_on_auth_error(
        self, client_manager: ClientManager, mock_db: AsyncDatabase
    ):
        """6. Avtorizatsiya xatosi bo'lganda klient ishga tushmasligini tekshirish."""
        mock_db.fetchone = AsyncMock(return_value={'id': 1, 'session_name': 'test', 'api_id': 123, 'api_hash': 'abc', 'is_active': True})

        with patch.object(client_manager, 'start_single_client', new_callable=AsyncMock) as mock_start:
            mock_start.return_value = False
            result = await client_manager.start_client_by_id(1)
            assert result is False
            mock_start.assert_awaited_once_with({'id': 1, 'session_name': 'test', 'api_id': 123, 'api_hash': 'abc', 'is_active': True})

    @patch('core.client_manager.save_credential_to_file')
    @patch('core.client_manager.TelegramClient')
    async def test_add_new_account_interactive(
        self, MockTelethonClient_Class: MagicMock, mock_save_file: MagicMock, client_manager: ClientManager, mock_db: AsyncMock, mock_telethon_client_instance: AsyncMock
    ):
        """7. Interaktiv rejimda yangi akkaunt qo'shish."""
        MockTelethonClient_Class.return_value = mock_telethon_client_instance
        mock_db.fetchone.return_value = None 

        mock_telethon_client_instance.is_user_authorized.return_value = False

        async def mock_prompt(text: str):
            if "API ID" in text: return "12345"
            if "API Hash" in text: return "abcdef"
            if "Sessiya nomi" in text: return "new_session"
            if "Telefon raqamingizni kiriting" in text: return "+998123456789"
            if "kodni kiriting" in text: return "54321"
            return ""

        await client_manager.add_new_account_interactive(prompt=mock_prompt)

        mock_telethon_client_instance.connect.assert_awaited_once()
        mock_telethon_client_instance.send_code_request.assert_awaited_once_with("+998123456789")
        mock_telethon_client_instance.sign_in.assert_awaited_once_with(phone="+998123456789", code="54321")
        mock_db.execute_insert.assert_awaited_once()
        mock_save_file.assert_called_once()

    @patch('core.client_manager.save_credential_to_file')
    @patch('core.client_manager.TelegramClient')
    async def test_add_new_account_non_interactive(
        self, MockTelethonClient_Class: MagicMock, mock_save_file: MagicMock, client_manager: ClientManager, mock_db: AsyncMock, mock_telethon_client_instance: AsyncMock
    ):
        """8. Interaktiv bo'lmagan rejimda yangi akkaunt qo'shish."""
        MockTelethonClient_Class.return_value = mock_telethon_client_instance
        mock_db.fetchone.return_value = None

        mock_telethon_client_instance.is_user_authorized.return_value = False

        creds = {
            'api_id': 999, 'api_hash': 'xyz', 'session_name': 'auto_session',
            'phone': '+123456789', 'code': '11111'
        }
        await client_manager.add_account_non_interactive(creds)

        mock_telethon_client_instance.send_code_request.assert_awaited_once_with('+123456789')
        mock_telethon_client_instance.sign_in.assert_awaited_once_with(phone='+123456789', code='11111')
        mock_db.execute_insert.assert_awaited_once()
        mock_save_file.assert_called_once()

    async def test_broadcast_message(self, client_manager: ClientManager):
        """9. Barcha klientlarga ommaviy xabar yuborish."""
        client1 = AsyncMock(spec=TelegramClient); client1.is_connected.return_value = True
        client2 = AsyncMock(spec=TelegramClient); client2.is_connected.return_value = True

        client_manager._clients = {1: client1, 2: client2}

        await client_manager.broadcast_message(chat_id=-100, message="Test xabar")

        client1.send_message.assert_awaited_once_with(-100, "Test xabar")
        client2.send_message.assert_awaited_once_with(-100, "Test xabar")

    async def test_monitor_disconnect_and_reconnect(self, client_manager: ClientManager, mock_db: AsyncMock, mock_state: AsyncMock):
        """10. Klient uzilganda avtomatik qayta ulanishga urinish."""
        client = AsyncMock(spec=TelegramClient)
        # `disconnected` Future'ni yaratamiz va uni darhol 'bajarilgan' deb belgilaymiz
        future = asyncio.Future()
        future.set_result(None)
        client.disconnected = future

        # Mock the initial state check for 'reconnecting'
        mock_state.get.return_value = False

        # Qayta ulanish muvaffaqiyatli bo'lganini simulyatsiya qilamiz
        with patch.object(client_manager, 'start_client_by_id', new_callable=AsyncMock) as mock_reconnect:
            mock_reconnect.return_value = True

            await client_manager.monitor_disconnect(client, account_id=1)

            mock_reconnect.assert_awaited_once_with(1)
            mock_db.execute.assert_not_called()
            mock_state.set.assert_any_call('client.1.reconnecting', True, persistent=False)
            mock_state.set.assert_any_call('client.1.reconnecting', False, persistent=False)
