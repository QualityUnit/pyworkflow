"""Dashboard configuration using pydantic-settings."""

from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    """Dashboard settings loaded from environment variables."""

    # PyWorkflow configuration
    pyworkflow_config_path: str | None = None  # Path to pyworkflow.config.yaml

    # Storage configuration (fallback if pyworkflow config not set)
    storage_type: str = "file"
    storage_path: str = "./pyworkflow_data"

    # Server configuration
    host: str = "0.0.0.0"
    port: int = 8585

    # CORS configuration
    cors_origins: list[str] = ["http://localhost:5173", "http://localhost:3000"]

    # Debug mode
    debug: bool = False

    # Metrics configuration
    metrics_cache_ttl_seconds: int = 15  # How long to cache metrics
    metrics_lookback_hours: int = 24  # How far back to look for metrics
    metrics_enabled: bool = True  # Enable /metrics endpoint

    class Config:
        env_prefix = "DASHBOARD_"
        env_file = ".env"
        env_file_encoding = "utf-8"


settings = Settings()
