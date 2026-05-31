from pathlib import Path

from pydantic import AliasChoices, Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        populate_by_name=True,
    )

    app_name: str = "AI Question Paper Generator API"
    app_env: str = "development"
    database_url: str = "sqlite:///./qpgen.db"
    jwt_secret_key: str = Field(
        "change-this-in-production-please-use-32-plus-chars",
        validation_alias=AliasChoices("JWT_SECRET_KEY", "SECRET_KEY"),
    )
    access_token_expire_minutes: int = 60
    refresh_token_expire_minutes: int | None = Field(
        None,
        validation_alias=AliasChoices("REFRESH_TOKEN_EXPIRE_MINUTES", "refresh_token_expire_minutes"),
    )
    refresh_token_expire_days: int = 7
    ollama_base_url: str = "http://localhost:11434"
    ollama_model: str = Field(
        "phi4-mini",
        validation_alias=AliasChoices("OLLAMA_MODEL", "OLLAMA_PRIMARY_MODEL"),
    )
    ollama_vision_model: str = Field(
        "llava",
        validation_alias=AliasChoices("OLLAMA_VISION_MODEL", "OLLAMA_VISION_MODEL_NAME"),
    )
    ollama_request_timeout_seconds: float = Field(
        120.0,
        validation_alias=AliasChoices("OLLAMA_REQUEST_TIMEOUT_SECONDS", "OLLAMA_TIMEOUT_SECONDS"),
    )
    ollama_generation_timeout_seconds: float = 45.0
    ollama_health_timeout_seconds: float = 2.5
    prewarm_embeddings_on_startup: bool = False
    academic_sync_processing_limit_bytes: int = 2 * 1024 * 1024
    storage_root: str = "./storage"
    allow_demo_seed: bool = True
    db_pool_size: int = 8
    db_max_overflow: int = 16
    db_pool_timeout_seconds: int = 30
    db_pool_recycle_seconds: int = 1800

    @property
    def storage_path(self) -> Path:
        path = Path(self.storage_root).resolve()
        path.mkdir(parents=True, exist_ok=True)
        return path

    @property
    def refresh_token_expire_minutes_effective(self) -> int:
        if self.refresh_token_expire_minutes is not None:
            return self.refresh_token_expire_minutes
        return self.refresh_token_expire_days * 24 * 60


settings = Settings()
