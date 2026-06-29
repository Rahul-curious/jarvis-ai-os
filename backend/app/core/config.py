from functools import lru_cache
from typing import Literal

from pydantic import Field, computed_field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        populate_by_name=True,
    )

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
    chroma_documents_collection: str = Field(
        default="documents",
        alias="CHROMA_DOCUMENTS_COLLECTION",
    )
    agent_default_recursion_limit: int = 25
    embedding_provider: Literal["sentence-transformers", "hash"] = Field(
        default="sentence-transformers",
        alias="EMBEDDING_PROVIDER",
    )
    embedding_model_name: str = Field(
        default="sentence-transformers/all-MiniLM-L6-v2",
        alias="EMBEDDING_MODEL_NAME",
    )
    embedding_dimensions: int = Field(default=384, alias="EMBEDDING_DIMENSIONS")
    document_max_upload_bytes: int = Field(
        default=10 * 1024 * 1024,
        alias="DOCUMENT_MAX_UPLOAD_BYTES",
    )
    document_chunk_size: int = Field(default=1200, alias="DOCUMENT_CHUNK_SIZE")
    document_chunk_overlap: int = Field(default=180, alias="DOCUMENT_CHUNK_OVERLAP")
    jwt_secret_key: str = Field(
        default="change-me-in-production-with-32-plus-chars",
        alias="JWT_SECRET_KEY",
    )
    jwt_issuer: str = Field(default="jarvis-ai-os", alias="JWT_ISSUER")
    jwt_algorithm: str = Field(default="HS256", alias="JWT_ALGORITHM")
    access_token_expire_minutes: int = Field(default=15, alias="ACCESS_TOKEN_EXPIRE_MINUTES")
    refresh_token_expire_days: int = Field(default=14, alias="REFRESH_TOKEN_EXPIRE_DAYS")
    access_cookie_name: str = Field(default="jarvis_access_token", alias="ACCESS_COOKIE_NAME")
    refresh_cookie_name: str = Field(default="jarvis_refresh_token", alias="REFRESH_COOKIE_NAME")
    auth_cookie_secure: bool = Field(default=False, alias="AUTH_COOKIE_SECURE")
    auth_cookie_samesite: Literal["lax", "strict", "none"] = Field(
        default="lax",
        alias="AUTH_COOKIE_SAMESITE",
    )
    password_min_length: int = Field(default=12, alias="PASSWORD_MIN_LENGTH")
    password_max_length: int = Field(default=128, alias="PASSWORD_MAX_LENGTH")
    short_term_memory_default_ttl_hours: int = Field(
        default=24,
        alias="SHORT_TERM_MEMORY_DEFAULT_TTL_HOURS",
    )

    @field_validator("jwt_secret_key")
    @classmethod
    def validate_jwt_secret_key(cls, value: str) -> str:
        if len(value) < 32:
            raise ValueError("JWT_SECRET_KEY must be at least 32 characters")
        return value

    @computed_field
    @property
    def cors_origins(self) -> list[str]:
        return [origin.strip() for origin in self.backend_cors_origins.split(",") if origin.strip()]

    @computed_field
    @property
    def chroma_url(self) -> str:
        return f"http://{self.chroma_host}:{self.chroma_port}"

    @computed_field
    @property
    def chroma_document_collection_name(self) -> str:
        return f"{self.chroma_collection_prefix}_{self.chroma_documents_collection}"


@lru_cache
def get_settings() -> Settings:
    return Settings()
