import sys
import os
sys.path.insert(0, os.path.dirname(__file__))
"""Единая точка конфигурации SKV."""
from pydantic_settings import BaseSettings, SettingsConfigDict
from functools import lru_cache

class Settings(BaseSettings):
    DATABASE_URL: str = "postgresql://skv_user:skv_secret_2026@skv_postgres:5432/skv_db"
    POLZA_KEY: str = ""
    DEBUG: bool = False
    
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=True
    )

@lru_cache()
def get_settings() -> Settings:
    return Settings()

settings = get_settings()
