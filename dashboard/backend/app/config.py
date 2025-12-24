"""Dashboard configuration using pydantic-settings."""

from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    """Dashboard settings loaded from environment variables."""

    # Storage configuration
    storage_type: str = "file"
    storage_path: str = "./pyworkflow_data"

    # Server configuration
    host: str = "0.0.0.0"
    port: int = 8585

    # CORS configuration
    cors_origins: list[str] = ["http://localhost:5173", "http://localhost:3000"]

    # Debug mode
    debug: bool = False

    class Config:
        env_prefix = "DASHBOARD_"
        env_file = ".env"
        env_file_encoding = "utf-8"


settings = Settings()
