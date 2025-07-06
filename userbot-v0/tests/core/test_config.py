# tests/core/test_config.py (To'liq yangilangan va kengaytirilgan versiya)

import os
import pytest
from pathlib import Path
from pydantic import SecretStr, ValidationError

# Test qilinayotgan asosiy klassni import qilamiz
from core.config import StaticSettings, BASE_DIR

# --- Testlarni sozlash uchun Fixture'lar ---

@pytest.fixture
def temp_env_file(tmp_path):
    """
    Har bir test uchun vaqtinchalik .env faylini yaratadigan va yo'lini taqdim etadigan fixture.
    Test davomida `StaticSettings` shu fayldan ma'lumot o'qiydi.
    """
    env_path = tmp_path / ".env.test"
    
    # StaticSettings'ni vaqtincha shu faylga yo'naltiramiz
    original_env_file = StaticSettings.model_config.get("env_file")
    StaticSettings.model_config["env_file"] = env_path

    # Fayl yaratiladi, test ishlaydi, so'ng eski konfiguratsiya tiklanadi
    yield env_path

    StaticSettings.model_config["env_file"] = original_env_file

# --- Testlar To'plami ---

class TestStaticSettings:
    """StaticSettings klassining funksionalligini va validatorlarini tekshiradi."""

    def write_to_env(self, path: Path, content: str):
        """Vaqtinchalik .env fayliga matn yozish uchun yordamchi funksiya."""
        path.write_text(content, encoding="utf-8")

    # 1-TEST
    def test_successful_load_from_env_file(self, temp_env_file):
        """1. Turli xil ma'lumotlar turlarining .env faylidan to'g'ri yuklanishini tekshiradi."""
        self.write_to_env(temp_env_file, """
OWNER_ID=123456
ADMIN_IDS='[100, 200]'
WEB_ENABLED=true
AI_STREAM_EDIT_INTERVAL=2.5
        """)
        
        settings = StaticSettings()
        
        assert settings.OWNER_ID == 123456
        assert settings.ADMIN_IDS == [100, 200]
        assert settings.WEB_ENABLED is True
        assert settings.AI_STREAM_EDIT_INTERVAL == pytest.approx(2.5) # SonarLint fix

    # 2-TEST
    def test_default_values_are_used_correctly(self, temp_env_file):
        """.env faylida ko'rsatilmagan maydonlar uchun standart qiymatlar ishlatilishini tekshiradi."""
        self.write_to_env(temp_env_file, "OWNER_ID=98765") # Faqat majburiy maydonni beramiz
        
        settings = StaticSettings()
        
        assert settings.LOG_LEVEL == "DEBUG"
        assert settings.NON_INTERACTIVE is False
        assert settings.AI_DEFAULT_MODEL == "gemini-1.5-flash-latest"
        assert settings.WEB_HOST == "0.0.0.0"
        assert settings.ADMIN_IDS == [] # default_factory orqali
        
    # 3-TEST
    def test_secretstr_fields_are_handled_securely(self, temp_env_file):
        """Maxfiy maydonlar (`SecretStr`) to'g'ri qayta ishlanishini tekshiradi."""
        self.write_to_env(temp_env_file, """
OWNER_ID=1
GEMINI_API_KEY="my-secret-gemini-key"
WEB_PASSWORD=super_secret_password
        """)

        settings = StaticSettings()
        
        # GEMINI_API_KEY
        assert isinstance(settings.GEMINI_API_KEY, SecretStr)
        assert "my-secret-gemini-key" not in repr(settings.GEMINI_API_KEY) # Maxfiy qiymat yashirilgan
        assert settings.GEMINI_API_KEY.get_secret_value() == "my-secret-gemini-key"
        
        # WEB_PASSWORD
        assert isinstance(settings.WEB_PASSWORD, SecretStr)
        assert settings.WEB_PASSWORD.get_secret_value() == "super_secret_password"

    # 4-TEST
    def test_missing_owner_id_raises_validation_error(self, temp_env_file):
        """`OWNER_ID` ko'rsatilmaganda, `model_validator` xatolik berishini tekshiradi."""
        self.write_to_env(temp_env_file, "# Bo'sh fayl") # OWNER_ID yo'q
        
        with pytest.raises(ValidationError) as exc_info: # type: ignore # Pylance fix
            StaticSettings()
        
        assert "OWNER_ID qiymati .env faylida ko'rsatilmagan" in str(exc_info.value)
        
    # 5-TEST
    def test_log_level_validator(self, temp_env_file):
        """`LOG_LEVEL` uchun `field_validator`ning ishlashini tekshiradi."""
        # Kichik harflar bilan berilgan to'g'ri qiymat
        self.write_to_env(temp_env_file, "OWNER_ID=1\nLOG_LEVEL=warning")
        settings = StaticSettings()
        assert settings.LOG_LEVEL == "WARNING"

        # Noto'g'ri qiymat
        self.write_to_env(temp_env_file, "OWNER_ID=1\nLOG_LEVEL=NOT_A_LEVEL")
        with pytest.raises(ValidationError) as exc_info: # type: ignore # Pylance fix
            StaticSettings()
        assert "LOG_LEVEL noto'g'ri" in str(exc_info.value)

    # 6-TEST
    def test_admin_ids_json_parsing(self, temp_env_file):
        """`ADMIN_IDS` maydoni JSON formatidagi matnni to'g'ri o'girishini tekshiradi."""
        # To'g'ri JSON massivi
        self.write_to_env(temp_env_file, "OWNER_ID=1\nADMIN_IDS='[11, 22, 33]'")
        settings = StaticSettings()
        assert settings.ADMIN_IDS == [11, 22, 33]
        
        # Noto'g'ri format
        self.write_to_env(temp_env_file, "OWNER_ID=1\nADMIN_IDS='1,2,3'")
        with pytest.raises(ValidationError): # type: ignore # Pylance fix
             StaticSettings() # Pydantic v2 JSON parse xatoligini beradi
            
    # 7-TEST
    def test_environment_variable_precedence(self, temp_env_file):
        """Muhit o'zgaruvchisi .env faylidagi qiymatdan ustun turishini tekshiradi."""
        # .env faylida bir qiymat
        self.write_to_env(temp_env_file, "OWNER_ID=111\nLOG_LEVEL=INFO")
        
        # Muhit o'zgaruvchisida esa boshqa qiymat o'rnatamiz
        os.environ['OWNER_ID'] = '999'
        os.environ['LOG_LEVEL'] = 'CRITICAL'
        
        settings = StaticSettings()
        
        # Muhit o'zgaruvchisidagi qiymat tanlanganini tekshiramiz
        assert settings.OWNER_ID == 999
        assert settings.LOG_LEVEL == 'CRITICAL'
        
        # Testdan so'ng muhitni tozalaymiz
        del os.environ['OWNER_ID']
        del os.environ['LOG_LEVEL']
        
    # 8-TEST
    def test_type_coercion_for_various_fields(self, temp_env_file):
        """Matnli qiymatlar kerakli turlarga (int, bool, float) to'g'ri o'girilishini tekshiradi."""
        self.write_to_env(temp_env_file, """
OWNER_ID=1
WEB_PORT="8000"
NON_INTERACTIVE=False
AI_STREAM_EDIT_INTERVAL=1.0
        """)
        
        settings = StaticSettings()
        
        assert isinstance(settings.WEB_PORT, int) and settings.WEB_PORT == 8000
        assert isinstance(settings.NON_INTERACTIVE, bool) and settings.NON_INTERACTIVE is False
        assert isinstance(settings.AI_STREAM_EDIT_INTERVAL, float) and settings.AI_STREAM_EDIT_INTERVAL == pytest.approx(1.0) # SonarLint fix

    # 9-TEST
    def test_extra_fields_in_env_are_ignored(self, temp_env_file):
        """`extra='ignore'` sozlamasi tufayli .env faylidagi ortiqcha maydonlar e'tiborsiz qoldirilishini tekshiradi."""
        self.write_to_env(temp_env_file, """
OWNER_ID=1
THIS_IS_AN_EXTRA_VARIABLE=some_value
        """)
        
        try:
            settings = StaticSettings()
            # `settings` obyektida ortiqcha atribut yo'qligini tekshiramiz
            assert not hasattr(settings, 'THIS_IS_AN_EXTRA_VARIABLE')
        except ValidationError:
            pytest.fail("Ortiqcha maydon sababli ValidationError yuz berdi, lekin bermasligi kerak edi.")
            
    # 10-TEST
    def test_path_objects_are_correctly_formed(self, temp_env_file):
        """Fayl yo'llari `pathlib.Path` obyektlariga to'g'ri aylantirilishini tekshiradi."""
        self.write_to_env(temp_env_file, "OWNER_ID=1")
        
        settings = StaticSettings()
        
        assert isinstance(settings.DB_PATH, Path)
        assert isinstance(settings.LOG_FILE_PATH, Path)
        assert settings.DB_PATH == BASE_DIR / "data" / "userbot.db"
        assert settings.LOG_FILE_PATH.name == "userbot.log"



