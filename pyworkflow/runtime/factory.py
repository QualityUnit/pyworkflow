"""
Runtime factory and registration.

This module provides:
- Runtime registration and lookup
- Validation of runtime + durable combinations
"""

from pyworkflow.runtime.base import Runtime

# Runtime registry
_runtimes: dict[str, type[Runtime]] = {}


def register_runtime(name: str, runtime_class: type[Runtime]) -> None:
    """
    Register a runtime implementation.

    Args:
        name: Runtime identifier (e.g., "local", "celery")
        runtime_class: Runtime class to register

    Example:
        >>> from pyworkflow.runtime import register_runtime
        >>> from myapp.runtime import CustomRuntime
        >>> register_runtime("custom", CustomRuntime)
    """
    _runtimes[name] = runtime_class


def get_runtime(name: str) -> Runtime:
    """
    Get a runtime instance by name.

    Args:
        name: Runtime identifier

    Returns:
        Runtime instance

    Raises:
        ValueError: If runtime is not registered
    """
    if name not in _runtimes:
        available = ", ".join(sorted(_runtimes.keys())) or "(none registered)"
        raise ValueError(f"Unknown runtime: '{name}'. Available runtimes: {available}")
    return _runtimes[name]()


def validate_runtime_durable(runtime: Runtime, durable: bool) -> None:
    """
    Validate that a runtime supports the requested durability mode.

    Args:
        runtime: Runtime instance
        durable: Whether durable mode is requested

    Raises:
        ValueError: If the combination is not supported
    """
    if durable and not runtime.supports_durable:
        raise ValueError(
            f"Runtime '{runtime.name}' does not support durable workflows. "
            f"Use durable=False or choose a different runtime."
        )
    if not durable and not runtime.supports_transient:
        raise ValueError(
            f"Runtime '{runtime.name}' requires durable=True. "
            f"This runtime does not support transient workflows."
        )


def list_runtimes() -> dict[str, type[Runtime]]:
    """
    List all registered runtimes.

    Returns:
        Dictionary of runtime name -> runtime class
    """
    return dict(_runtimes)


# Register built-in runtimes
def _register_builtin_runtimes() -> None:
    """Register built-in runtimes."""
    from pyworkflow.runtime.local import LocalRuntime

    register_runtime("local", LocalRuntime)

    # Register Celery runtime (lazy import to avoid circular deps)
    try:
        from pyworkflow.runtime.celery import CeleryRuntime

        register_runtime("celery", CeleryRuntime)
    except ImportError:
        # Celery not installed, skip registration
        pass


# Auto-register on import
_register_builtin_runtimes()
