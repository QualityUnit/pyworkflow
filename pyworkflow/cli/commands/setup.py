"""Environment setup command for PyWorkflow."""

import os
import click
from typing import Optional

from pyworkflow.cli.output.formatters import (
    format_key_value,
    format_json,
    print_success,
    print_error,
    print_info,
    print_warning,
)


@click.command(name="setup")
@click.option(
    "--broker",
    type=click.Choice(["redis", "rabbitmq"], case_sensitive=False),
    default="redis",
    help="Broker type to use (default: redis)",
)
@click.option(
    "--broker-url",
    help="Full broker URL (overrides --broker defaults)",
)
@click.option(
    "--check",
    is_flag=True,
    help="Only check if environment is ready (no modifications)",
)
@click.pass_context
def setup(
    ctx: click.Context,
    broker: str,
    broker_url: Optional[str],
    check: bool,
) -> None:
    """
    Setup and verify the PyWorkflow environment.

    This command checks broker connectivity and displays configuration
    information for running Celery workers.

    Examples:

        # Check Redis broker (default)
        pyworkflow setup --check

        # Check RabbitMQ broker
        pyworkflow setup --broker rabbitmq --check

        # Check custom broker URL
        pyworkflow setup --broker-url redis://myredis:6379/0 --check

        # Show full setup information
        pyworkflow setup
    """
    config = ctx.obj.get("config", {})
    output = ctx.obj.get("output", "table")

    # Get broker configuration
    celery_config = config.get("celery", {})

    if broker_url:
        final_broker_url = broker_url
    elif "broker" in celery_config:
        final_broker_url = celery_config["broker"]
    elif broker == "rabbitmq":
        final_broker_url = os.getenv(
            "PYWORKFLOW_CELERY_BROKER",
            "amqp://guest:guest@localhost:5672//",
        )
    else:  # redis
        final_broker_url = os.getenv(
            "PYWORKFLOW_CELERY_BROKER",
            "redis://localhost:6379/0",
        )

    # Result backend
    if "result_backend" in celery_config:
        result_backend = celery_config["result_backend"]
    else:
        result_backend = os.getenv(
            "PYWORKFLOW_CELERY_RESULT_BACKEND",
            "redis://localhost:6379/1",
        )

    print_info("PyWorkflow Environment Setup")
    print_info("=" * 40)
    print_info("")

    # Check broker connectivity
    broker_ok = _check_broker(final_broker_url)

    # Check result backend connectivity
    backend_ok = _check_result_backend(result_backend)

    # Show configuration
    config_data = {
        "Broker Type": broker.upper(),
        "Broker URL": final_broker_url,
        "Broker Status": "Connected" if broker_ok else "Not Connected",
        "Result Backend": result_backend,
        "Backend Status": "Connected" if backend_ok else "Not Connected",
    }

    # Get storage config
    storage_type = ctx.obj.get("storage_type") or config.get("storage", {}).get("type", "file")
    storage_path = ctx.obj.get("storage_path") or config.get("storage", {}).get("base_path", "./workflow_data")
    config_data["Storage Backend"] = storage_type
    if storage_type == "file":
        config_data["Storage Path"] = storage_path

    # Check if Celery is installed
    celery_installed = _check_celery_installed()
    config_data["Celery"] = "Installed" if celery_installed else "Not Installed"

    if output == "json":
        json_data = {
            "broker": {
                "type": broker,
                "url": final_broker_url,
                "connected": broker_ok,
            },
            "result_backend": {
                "url": result_backend,
                "connected": backend_ok,
            },
            "storage": {
                "type": storage_type,
                "path": storage_path if storage_type == "file" else None,
            },
            "celery_installed": celery_installed,
            "ready": broker_ok and backend_ok and celery_installed,
        }
        format_json(json_data)
    else:
        format_key_value(config_data, title="Configuration")

    # Status summary
    print_info("")

    if broker_ok and backend_ok and celery_installed:
        print_success("Environment is ready!")
        print_info("")
        print_info("Next steps:")
        print_info("  1. Start a worker:  pyworkflow worker run")
        print_info("  2. Run a workflow:  pyworkflow workflows run <workflow_name>")
    else:
        print_warning("Environment has issues:")

        if not celery_installed:
            print_error("  - Celery is not installed")
            print_info("    Fix: pip install celery[redis]")

        if not broker_ok:
            print_error(f"  - Cannot connect to broker: {final_broker_url}")
            if broker == "redis":
                print_info("    Fix: docker run -d -p 6379:6379 redis:7-alpine")
            else:
                print_info("    Fix: docker run -d -p 5672:5672 rabbitmq:3-management")

        if not backend_ok:
            print_error(f"  - Cannot connect to result backend: {result_backend}")
            print_info("    Fix: Ensure Redis is running for result storage")


def _check_celery_installed() -> bool:
    """Check if Celery is installed."""
    try:
        import celery

        return True
    except ImportError:
        return False


def _check_broker(broker_url: str) -> bool:
    """Check if the broker is accessible."""
    try:
        if broker_url.startswith("redis://"):
            return _check_redis(broker_url)
        elif broker_url.startswith("amqp://"):
            return _check_rabbitmq(broker_url)
        else:
            # Unknown broker type, assume it works
            return True
    except Exception:
        return False


def _check_redis(url: str) -> bool:
    """Check Redis connectivity."""
    try:
        import redis

        # Parse URL
        client = redis.from_url(url, socket_timeout=2)
        client.ping()
        return True
    except ImportError:
        # redis-py not installed, try with socket
        return _check_redis_socket(url)
    except Exception:
        return False


def _check_redis_socket(url: str) -> bool:
    """Check Redis connectivity using raw socket."""
    import socket
    from urllib.parse import urlparse

    try:
        parsed = urlparse(url)
        host = parsed.hostname or "localhost"
        port = parsed.port or 6379

        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.settimeout(2)
        result = sock.connect_ex((host, port))
        sock.close()
        return result == 0
    except Exception:
        return False


def _check_rabbitmq(url: str) -> bool:
    """Check RabbitMQ connectivity."""
    import socket
    from urllib.parse import urlparse

    try:
        parsed = urlparse(url)
        host = parsed.hostname or "localhost"
        port = parsed.port or 5672

        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.settimeout(2)
        result = sock.connect_ex((host, port))
        sock.close()
        return result == 0
    except Exception:
        return False


def _check_result_backend(url: str) -> bool:
    """Check result backend connectivity."""
    if url.startswith("redis://"):
        return _check_redis(url)
    elif url.startswith("rpc://"):
        # RPC backend uses the broker, assume it works
        return True
    else:
        # Unknown backend, assume it works
        return True
