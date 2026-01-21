"""Application configuration using pydantic-settings."""
from functools import lru_cache
from typing import Optional
from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    """Application settings loaded from environment variables."""
    
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
    JWT_ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_HOURS: int = 24
    REFRESH_TOKEN_EXPIRE_DAYS: int = 7
    
    # MinIO/S3
    MINIO_ENDPOINT: str = "localhost:9000"
    MINIO_ACCESS_KEY: str = "minioadmin"
    MINIO_SECRET_KEY: str = "minioadmin"
    MINIO_BUCKET: str = "aerial-survey"
    MINIO_SECURE: bool = False
    # Browser-accessible endpoint for presigned URLs (e.g., localhost:9002 for host machine)
    MINIO_PUBLIC_ENDPOINT: Optional[str] = "localhost:9002"
    
    # Processing Engines
    EXTERNAL_ENGINE_URL: str = ""
    EXTERNAL_ENGINE_API_KEY: str = ""
    ODM_DOCKER_IMAGE: str = "opendronemap/odm:latest"
    
    # Upload / Data
    TUS_ENDPOINT: str = "http://localhost:1080/files/"
    MAX_UPLOAD_SIZE_GB: int = 500
    LOCAL_DATA_PATH: str = "/data"
    
    # CORS
    CORS_ORIGINS: list[str] = ["http://localhost:3000", "http://localhost:5173", "http://localhost:8081"]
    
    class Config:
        env_file = ".env"
        case_sensitive = True


@lru_cache()
def get_settings() -> Settings:
    """Get cached settings instance."""
    return Settings()
