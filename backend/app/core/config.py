from functools import lru_cache

from pydantic import Field, computed_field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    app_name: str = "JARVIS AI OS"
    app_env: str = "development"
    api_v1_prefix: str = "/api/v1"
    enable_docs: bool = True
    log_level: str = "INFO"

    backend_cors_origins: str = Field(
        default="http://localhost:5173,http://127.0.0.1:5173",
        alias="BACKEND_CORS_ORIGINS",
    )

    database_url: str = "postgresql+asyncpg://jarvis:jarvis_dev_password@localhost:5432/jarvis"
    chroma_host: str = "localhost"
    chroma_port: int = 8001
    chroma_collection_prefix: str = "jarvis"
    agent_default_recursion_limit: int = 25

    @computed_field
    @property
    def cors_origins(self) -> list[str]:
        return [origin.strip() for origin in self.backend_cors_origins.split(",") if origin.strip()]

    @computed_field
    @property
    def chroma_url(self) -> str:
        return f"http://{self.chroma_host}:{self.chroma_port}"


@lru_cache
def get_settings() -> Settings:
    return Settings()
