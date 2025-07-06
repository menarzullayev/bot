import json
from pathlib import Path
from typing import Dict, Optional, List, Any, Literal

from loguru import logger

from pydantic_settings import BaseSettings, SettingsConfigDict
from pydantic import Field, SecretStr, ValidationError, field_validator, model_validator

from .db_whitelists import DB_TABLE_WHITELIST, DB_COLUMN_WHITELIST

BASE_DIR = Path(__file__).resolve().parent.parent


class StaticSettings(BaseSettings):
    """
    Ilova sozlamalari uchun Pydantic BaseSettings modeli.
    """

    model_config = SettingsConfigDict(env_file=BASE_DIR / ".env", env_file_encoding="utf-8", extra='ignore', validate_default=True, populate_by_name=True)

    OWNER_ID: Optional[int] = Field(default=None, description="Userbot egasining Telegram IDsi.")

    ADMIN_IDS: Optional[List[int]] = Field(default_factory=list, description="Qo'shimcha adminlar ro'yxati (JSON formatida).")

    NON_INTERACTIVE: bool = False
    NEW_ACCOUNT_API_ID: Optional[int] = None
    NEW_ACCOUNT_API_HASH: Optional[SecretStr] = None
    NEW_ACCOUNT_SESSION_NAME: str = "my_userbot_session"
    NEW_ACCOUNT_PHONE: Optional[str] = None
    NEW_ACCOUNT_CODE: Optional[str] = None
    NEW_ACCOUNT_PASSWORD: Optional[SecretStr] = None
    LOG_LEVEL: str = "DEBUG"
    DB_PATH: Path = BASE_DIR / "data" / "userbot.db"
    LOG_FILE_PATH: Path = BASE_DIR / "logs" / "userbot.log"
    DB_TABLE_WHITELIST: List[str] = Field(default_factory=lambda: DB_TABLE_WHITELIST)
    DB_COLUMN_WHITELIST: Dict[str, List[str]] = Field(default_factory=lambda: DB_COLUMN_WHITELIST)
    GEMINI_API_KEY: Optional[SecretStr] = None
    YANDEX_API_KEY: Optional[SecretStr] = None
    YANDEX_FOLDER_ID: Optional[str] = None
    WEB_ENABLED: bool = False
    WEB_PASSWORD: Optional[SecretStr] = None
    FLASK_SECRET_KEY: Optional[SecretStr] = None
    WEB_HOST: str = "0.0.0.0"
    WEB_PORT: int = 8080
    AI_DEFAULT_MODEL: str = "gemini-1.5-flash-latest"
    AI_SYSTEM_PROMPT: str = "Sen O'zbekistondan bo'lgan do'stona va yordamchi assistantsan. Har doim o'zbek tilida, iloji boricha, markdown formatida javob ber."
    AI_VISION_MODEL: str = "gemini-pro-vision"
    AI_STREAM_EDIT_INTERVAL: float = 1.5
    PERSIST_INTERVAL_SECONDS: int = 3600
    CACHE_DEFAULT_MAX_SIZE: int = 512
    CACHE_DEFAULT_TTL: int = 300
    DB_CLEANUP_DAYS: int = 7
    AI_CHAT_TTL_SECONDS: int = 3600
    RAG_SEARCH_RESULTS_COUNT: int = 5
    RAG_SEARCH_LANG: str = "uz"
    RAG_FETCH_MAX_URLS: int = 3
    RAG_MAX_CONTEXT_LENGTH: int = 3500

    @model_validator(mode='after')
    def _check_required_fields(self) -> 'StaticSettings':
        if self.OWNER_ID is None:
            raise ValueError("KRITIK XATO: OWNER_ID qiymati .env faylida ko'rsatilmagan! Bu maydon majburiy.")
        return self

    @field_validator('LOG_LEVEL')
    @classmethod
    def log_level_must_be_valid(cls, v: str) -> str:
        """Log darajasining haqiqiy qiymat ekanligini tekshiradi."""
        valid_levels = ["TRACE", "DEBUG", "INFO", "SUCCESS", "WARNING", "ERROR", "CRITICAL"]
        if v.upper() not in valid_levels:
            raise ValueError(f"LOG_LEVEL noto'g'ri: '{v}'. Mumkin qiymatlar: {valid_levels}")
        return v.upper()
