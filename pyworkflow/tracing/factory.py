"""
Tracing provider factory.

Creates the appropriate tracing provider based on config.
"""

from __future__ import annotations

from typing import Any

from loguru import logger

from pyworkflow.tracing.base import BaseTracingProvider


def create_tracing_provider(
    tracing_config: dict[str, Any] | None = None,
) -> BaseTracingProvider | None:
    """Create a tracing provider from a config dict.

    Supported providers:
    - ``"langfuse"`` (default if public_key/secret_key are present)

    Returns None if no credentials are available.
    """
    if not tracing_config:
        return None

    provider = tracing_config.get("provider", "langfuse")
    public_key = tracing_config.get("public_key", "")
    secret_key = tracing_config.get("secret_key", "")

    if not public_key or not secret_key:
        return None

    if provider == "langfuse":
        from pyworkflow.tracing.langfuse import LangfuseTracingProvider

        return LangfuseTracingProvider(
            public_key=public_key,
            secret_key=secret_key,
            host=tracing_config.get("host", "https://app.langfuse.com"),
        )

    logger.debug(f"Unknown tracing provider: {provider}")
    return None
