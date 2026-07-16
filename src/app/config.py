import sys
import os
sys.path.insert(0, os.path.dirname(__file__))
"""Единая точка конфигурации SKV."""
from pydantic_settings import BaseSettings, SettingsConfigDict
from functools import lru_cache

class Settings(BaseSettings):
    # No default credentials — must come from environment / .env (not committed secrets).
    DATABASE_URL: str = ""
    POLZA_KEY: str = ""
    RESEND_API_KEY: str = ""
    SKV_SALT: str = ""
    DEBUG: bool = False

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=True,
        extra="ignore",
    )

@lru_cache()
def get_settings() -> Settings:
    return Settings()

settings = get_settings()
