from functools import lru_cache
from pydantic_settings import BaseSettings
from typing import List
import os


class Settings(BaseSettings):
    # App
    app_env: str = "development"
    app_host: str = "0.0.0.0"
    app_port: int = 8000
    cors_origins: str = "http://localhost:3000,http://127.0.0.1:3000"
    upload_dir: str = "./uploads"
    output_dir: str = "./outputs"
    max_upload_size_mb: int = 10
    ffmpeg_path: str = "ffmpeg"

    # Turso
    turso_database_url: str = ""
    turso_auth_token: str = ""

    # Groq
    groq_api_key: str = ""

    # Magic Hour
    magic_hour_api_key: str = ""
    magic_hour_base_url: str = "https://api.magichour.ai/v1"

    # Agnes AI (Fallback)
    agnes_ai_api_key: str = ""
    agnes_ai_base_url: str = "https://api.agnes-ai.com/v1"

    # Pollinations
    pollinations_base_url: str = "https://image.pollinations.ai/prompt"

    class Config:
        env_file = ".env"
        env_file_encoding = "utf-8"
        case_sensitive = False

    @property
    def cors_origins_list(self) -> List[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]

    @property
    def max_upload_bytes(self) -> int:
        return self.max_upload_size_mb * 1024 * 1024


@lru_cache()
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
