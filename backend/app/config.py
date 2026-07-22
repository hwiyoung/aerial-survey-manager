"""Application configuration using pydantic-settings."""
from functools import lru_cache
from typing import Optional
from pydantic import model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Application settings loaded from environment variables."""

    model_config = SettingsConfigDict(
        env_file=".env",
        case_sensitive=True,
        extra="ignore",
    )

    # Application
    APP_NAME: str = "Aerial Survey Manager"
    DEBUG: bool = False
    API_V1_PREFIX: str = "/api/v1"
    
    # Database
    DATABASE_URL: str = "postgresql+asyncpg://postgres:postgres@localhost:5432/aerial_survey"
    
    # Redis
    REDIS_URL: str = "redis://localhost:6379/0"
    
    # JWT Auth
    JWT_SECRET_KEY: str = "your-super-secret-key-change-in-production"
    ALLOW_WEAK_JWT_SECRET: bool = True
    JWT_ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_HOURS: int = 24
    REFRESH_TOKEN_EXPIRE_DAYS: int = 7
    
    # Storage Backend: "minio" (multi-server) or "local" (single server, no MinIO)
    STORAGE_BACKEND: str = "minio"
    LOCAL_STORAGE_PATH: str = "/data/storage"
    PROCESSING_DATA_PATH: str = "/data/processing"
    EXPORT_ROOT_PATH: str = "/data/exports"
    MEDIA_STORAGE_ROOT: str = "/media"
    SYSTEM_STORAGE_PATH: str = "/"
    FILESYSTEM_ALLOWED_ROOTS: Optional[str] = None
    AUTO_EXPORT_ENABLED: bool = False
    AUTO_EXPORT_TARGET_CRS: str = "EPSG:5186"
    PROCESSING_LOG_MAX_BYTES: int = 50 * 1024 * 1024
    PROCESSING_LOG_BACKUP_COUNT: int = 3
    PROCESSING_ERROR_BUNDLE_RETENTION_DAYS: int = 30
    PROCESSING_ERROR_BUNDLE_PROJECT_LIMIT: int = 20
    PROCESSING_ERROR_BUNDLE_TOTAL_MAX_BYTES: int = 20 * 1024 * 1024 * 1024
    PROCESSING_ERROR_BUNDLE_LOG_TAIL_BYTES: int = 5 * 1024 * 1024
    CAMERA_IO_SOURCE_PATH: str = "/app/data/io.csv"
    CAMERA_IO_CONFIG_PATH: str = "/data/config/io.csv"
    CAMERA_IO_BACKUP_COUNT: int = 20
    IMAGE_PREVIEW_CACHE_PATH: str = "/data/config/image-previews"
    IMAGE_PREVIEW_CACHE_RETENTION_DAYS: int = 7
    IMAGE_PREVIEW_CACHE_MAX_BYTES: int = 1024 * 1024 * 1024

    # MinIO/S3 (only used when STORAGE_BACKEND=minio)
    MINIO_ENDPOINT: str = "localhost:9000"
    MINIO_ACCESS_KEY: str = "minioadmin"
    MINIO_SECRET_KEY: str = "minioadmin"
    MINIO_BUCKET: str = "aerial-survey"
    MINIO_SECURE: bool = False
    TITILER_INTERNAL_URL: str = "http://titiler:80"
    
    # Processing Engines
    ENABLE_METASHAPE_ENGINE: bool = True
    METASHAPE_LICENSE_KEY: str = ""
    
    # Upload / Data
    MAX_UPLOAD_SIZE_GB: int = 500
    LOCAL_DATA_PATH: str = "/data"
    
    # CORS
    CORS_ORIGINS: list[str] = [
        "http://localhost:3000",
        "http://localhost:5173",
        "http://localhost:18110",
        "http://127.0.0.1:18110",
    ]

    @model_validator(mode="after")
    def validate_jwt_secret(self):
        if self.ALLOW_WEAK_JWT_SECRET:
            return self

        normalized = self.JWT_SECRET_KEY.strip().lower()
        placeholder_markers = (
            "change-this",
            "change_this",
            "your-super-secret",
            "placeholder",
        )
        if len(self.JWT_SECRET_KEY.encode("utf-8")) < 32:
            raise ValueError("JWT_SECRET_KEY must be at least 32 bytes in deployment mode")
        if any(marker in normalized for marker in placeholder_markers):
            raise ValueError("JWT_SECRET_KEY must not use a packaged placeholder")
        return self

@lru_cache()
def get_settings() -> Settings:
    """Get cached settings instance."""
    return Settings()
