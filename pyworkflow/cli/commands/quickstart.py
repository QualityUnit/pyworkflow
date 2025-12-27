"""Quickstart command to scaffold a new PyWorkflow project."""

import sys
from pathlib import Path

import click

from pyworkflow.cli.output.formatters import (
    print_error,
    print_info,
    print_success,
    print_warning,
)
from pyworkflow.cli.utils.config_generator import (
    generate_yaml_config,
    write_yaml_config,
)
from pyworkflow.cli.utils.docker_manager import (
    check_docker_available,
    check_service_health,
    generate_docker_compose_content,
    run_docker_command,
    write_docker_compose,
)
from pyworkflow.cli.utils.interactive import (
    confirm,
    select,
)

# Template content for sample workflows
WORKFLOWS_INIT_TEMPLATE = '''"""Project workflows."""
from .orders import process_order
from .notifications import send_notification

__all__ = [
    "process_order",
    "send_notification",
]
'''

ORDERS_WORKFLOW_TEMPLATE = '''"""Order processing workflow example."""
from pyworkflow import workflow, step


@step()
async def validate_order(order_id: str) -> dict:
    """Validate the order exists and is valid."""
    # In a real app, check database or external service
    return {"order_id": order_id, "valid": True}


@step()
async def process_payment(order_id: str, amount: float) -> dict:
    """Process payment for the order."""
    # In a real app, integrate with payment provider
    return {"order_id": order_id, "payment_status": "completed", "amount": amount}


@step()
async def update_inventory(order_id: str) -> dict:
    """Update inventory after order."""
    # In a real app, update inventory database
    return {"order_id": order_id, "inventory_updated": True}


@workflow()
async def process_order(order_id: str, amount: float = 99.99) -> dict:
    """
    Process an order through validation, payment, and inventory update.

    This is a sample workflow demonstrating:
    - Multiple steps executed in sequence
    - Data passing between steps
    - Automatic retry on failures

    Run with:
        pyworkflow workflows run process_order --input '{"order_id": "123", "amount": 49.99}'
    """
    validation = await validate_order(order_id)
    if not validation["valid"]:
        raise ValueError(f"Order {order_id} is not valid")

    payment = await process_payment(order_id, amount)
    inventory = await update_inventory(order_id)

    return {
        "order_id": order_id,
        "status": "completed",
        "payment": payment,
        "inventory": inventory,
    }
'''

NOTIFICATIONS_WORKFLOW_TEMPLATE = '''"""Notification workflow example."""
from pyworkflow import workflow, step, sleep


@step()
async def send_email(to: str, subject: str, body: str) -> dict:
    """Send an email notification."""
    # In a real app, integrate with email service (SendGrid, SES, etc.)
    return {"sent": True, "to": to, "subject": subject}


@step()
async def send_sms(phone: str, message: str) -> dict:
    """Send an SMS notification."""
    # In a real app, integrate with SMS service (Twilio, etc.)
    return {"sent": True, "phone": phone}


@workflow()
async def send_notification(
    user_id: str,
    message: str,
    channels: list[str] | None = None,
) -> dict:
    """
    Send notifications through multiple channels.

    This workflow demonstrates:
    - Conditional step execution
    - Sleep/delay functionality
    - Multiple notification channels

    Run with:
        pyworkflow workflows run send_notification --input '{"user_id": "user-123", "message": "Hello!"}'
    """
    if channels is None:
        channels = ["email"]

    results = {"user_id": user_id, "notifications": []}

    if "email" in channels:
        email_result = await send_email(
            to=f"{user_id}@example.com",
            subject="Notification",
            body=message,
        )
        results["notifications"].append({"channel": "email", **email_result})

    if "sms" in channels:
        # Add small delay between channels
        await sleep("1s")
        sms_result = await send_sms(
            phone="+1234567890",
            message=message,
        )
        results["notifications"].append({"channel": "sms", **sms_result})

    return results
'''


def _check_sqlite_available() -> bool:
    """Check if SQLite is available in the Python build."""
    try:
        import sqlite3  # noqa: F401

        return True
    except ImportError:
        return False


@click.command(name="quickstart")
@click.option(
    "--non-interactive",
    is_flag=True,
    help="Run without prompts (use defaults)",
)
@click.option(
    "--skip-docker",
    is_flag=True,
    help="Skip Docker services setup",
)
@click.option(
    "--template",
    type=click.Choice(["basic"]),
    default="basic",
    help="Project template to use",
)
@click.option(
    "--storage",
    type=click.Choice(["sqlite", "file"], case_sensitive=False),
    help="Storage backend type",
)
@click.pass_context
def quickstart(
    ctx: click.Context,
    non_interactive: bool,
    skip_docker: bool,
    template: str,
    storage: str | None,
) -> None:
    """
    Create a new PyWorkflow project with sample workflows.

    This command will:
      1. Create a workflows/ package with sample workflows
      2. Generate pyworkflow.config.yaml
      3. Optionally start Docker services (Redis + Dashboard)

    Examples:

        # Interactive quickstart
        $ pyworkflow quickstart

        # Non-interactive with defaults
        $ pyworkflow quickstart --non-interactive

        # Without Docker
        $ pyworkflow quickstart --skip-docker
    """
    try:
        _run_quickstart(
            ctx=ctx,
            non_interactive=non_interactive,
            skip_docker=skip_docker,
            template=template,
            storage_override=storage,
        )
    except click.Abort:
        print_warning("\nQuickstart cancelled by user")
        sys.exit(1)
    except Exception as e:
        print_error(f"\nQuickstart failed: {str(e)}")
        if ctx.obj and ctx.obj.get("verbose"):
            raise
        sys.exit(1)


def _run_quickstart(
    ctx: click.Context,
    non_interactive: bool,
    skip_docker: bool,
    template: str,
    storage_override: str | None,
) -> None:
    """Main quickstart workflow."""
    # 1. Welcome banner
    _print_welcome()

    # 2. Check for existing files
    cwd = Path.cwd()
    workflows_dir = cwd / "workflows"
    config_path = cwd / "pyworkflow.config.yaml"

    if workflows_dir.exists():
        print_warning(f"Directory already exists: {workflows_dir}")
        if not non_interactive:
            if not confirm("Overwrite existing workflows directory?", default=False):
                raise click.Abort()
        print_info("")

    if config_path.exists():
        print_warning(f"Config already exists: {config_path}")
        if not non_interactive:
            if not confirm("Overwrite existing config?", default=False):
                raise click.Abort()
        print_info("")

    # 3. Template selection (currently only basic)
    if not non_interactive:
        print_info("Select a project template:\n")
        template = select(
            "Template:",
            choices=[
                {
                    "name": "Basic - Order processing and notifications (2 workflows)",
                    "value": "basic",
                },
            ],
        )

    # 4. Storage backend selection
    sqlite_available = _check_sqlite_available()
    if storage_override:
        storage_type = storage_override.lower()
        if storage_type == "sqlite" and not sqlite_available:
            print_error("SQLite is not available in your Python build")
            print_info("Use --storage file or install libsqlite3-dev and rebuild Python")
            raise click.Abort()
    elif non_interactive:
        storage_type = "sqlite" if sqlite_available else "file"
    else:
        print_info("")
        choices = []
        if sqlite_available:
            choices.append(
                {"name": "SQLite - Single file database (recommended)", "value": "sqlite"}
            )
        choices.append(
            {
                "name": "File - JSON files on disk"
                + (" (recommended)" if not sqlite_available else ""),
                "value": "file",
            }
        )

        storage_type = select("Storage backend:", choices=choices)

    # 5. Docker prompt
    docker_available, docker_error = check_docker_available()
    start_docker = False

    if not skip_docker:
        if not docker_available:
            print_warning(f"\nDocker: {docker_error}")
            print_info("Skipping Docker setup. You can run 'pyworkflow setup' later.\n")
        elif non_interactive:
            start_docker = True
        else:
            print_info("")
            start_docker = confirm("Start Docker services (Redis + Dashboard)?", default=True)

    # 6. Create project structure
    print_info("\nCreating project structure...")
    _create_project_files(cwd, template)

    # 7. Generate config
    storage_path = (
        "pyworkflow_data/pyworkflow.db" if storage_type == "sqlite" else "pyworkflow_data"
    )

    yaml_content = generate_yaml_config(
        module="workflows",
        runtime="celery",
        storage_type=storage_type,
        storage_path=storage_path,
        broker_url="redis://localhost:6379/0",
        result_backend="redis://localhost:6379/1",
    )

    write_yaml_config(yaml_content, config_path, backup=True)
    print_success(f"  Created: {config_path.name}")

    # 8. Docker setup
    dashboard_available = False
    if start_docker:
        dashboard_available = _setup_docker(cwd, storage_type, storage_path)

    # 9. Show next steps
    _show_next_steps(start_docker, dashboard_available)


def _print_welcome() -> None:
    """Print welcome banner."""
    print_info("")
    print_info("=" * 60)
    print_info("  PyWorkflow Quickstart")
    print_info("=" * 60)
    print_info("")


def _create_project_files(cwd: Path, template: str) -> None:
    """Create project structure based on template."""
    workflows_dir = cwd / "workflows"
    workflows_dir.mkdir(exist_ok=True)

    # Write template files
    files = {
        workflows_dir / "__init__.py": WORKFLOWS_INIT_TEMPLATE,
        workflows_dir / "orders.py": ORDERS_WORKFLOW_TEMPLATE,
        workflows_dir / "notifications.py": NOTIFICATIONS_WORKFLOW_TEMPLATE,
    }

    for file_path, content in files.items():
        file_path.write_text(content)
        print_success(f"  Created: {file_path.relative_to(cwd)}")


def _setup_docker(
    cwd: Path,
    storage_type: str,
    storage_path: str,
) -> bool:
    """Set up Docker infrastructure.

    Returns:
        True if dashboard is available, False otherwise
    """
    print_info("\nSetting up Docker services...")

    # Generate docker-compose.yml
    compose_content = generate_docker_compose_content(
        storage_type=storage_type,
        storage_path=storage_path,
    )

    compose_path = cwd / "docker-compose.yml"
    write_docker_compose(compose_content, compose_path)
    print_success(f"  Created: {compose_path.name}")

    # Pull images
    print_info("\n  Pulling Docker images...")
    print_info("")
    pull_success, _ = run_docker_command(
        ["pull"],
        compose_file=compose_path,
        stream_output=True,
    )

    dashboard_available = pull_success
    if not pull_success:
        print_warning("\n  Failed to pull dashboard images")
        print_info("  Continuing with Redis setup only...")

    # Start services
    print_info("\n  Starting services...")
    print_info("")

    services_to_start = ["redis"]
    if dashboard_available:
        services_to_start.extend(["dashboard-backend", "dashboard-frontend"])

    success, _ = run_docker_command(
        ["up", "-d"] + services_to_start,
        compose_file=compose_path,
        stream_output=True,
    )

    if not success:
        print_error("\n  Failed to start services")
        print_info("  Try: docker compose down && docker compose up -d")
        return False

    print_success("\n  Services started")

    # Health checks
    print_info("\n  Checking service health...")
    health_checks = {
        "Redis": {"type": "tcp", "host": "localhost", "port": 6379},
    }

    if dashboard_available:
        health_checks["Dashboard Backend"] = {
            "type": "http",
            "url": "http://localhost:8585/api/v1/health",
        }
        health_checks["Dashboard Frontend"] = {
            "type": "http",
            "url": "http://localhost:5173",
        }

    health_results = check_service_health(health_checks)

    for service_name, healthy in health_results.items():
        if healthy:
            print_success(f"  {service_name}: Ready")
        else:
            print_warning(f"  {service_name}: Not responding (may still be starting)")

    return dashboard_available


def _show_next_steps(docker_started: bool, dashboard_available: bool) -> None:
    """Display next steps."""
    print_info("\n" + "=" * 60)
    print_success("Project Created!")
    print_info("=" * 60)

    print_info("\nProject structure:")
    print_info("  workflows/")
    print_info("    __init__.py")
    print_info("    orders.py          (process_order workflow)")
    print_info("    notifications.py   (send_notification workflow)")
    print_info("  pyworkflow.config.yaml")

    if docker_started:
        print_info("\nServices running:")
        print_info("  Redis:              redis://localhost:6379")
        if dashboard_available:
            print_info("  Dashboard:          http://localhost:5173")
            print_info("  Dashboard API:      http://localhost:8585/docs")

    print_info("\nNext steps:")
    print_info("")
    print_info("  1. Start a worker:")
    print_info("     $ pyworkflow worker start")
    print_info("")
    print_info("  2. Run a workflow:")
    print_info("     $ pyworkflow workflows run process_order \\")
    print_info('         --input \'{"order_id": "123", "amount": 49.99}\'')

    if docker_started and dashboard_available:
        print_info("")
        print_info("  3. View the dashboard:")
        print_info("     Open http://localhost:5173 in your browser")

    if docker_started:
        print_info("")
        print_info("To stop services:")
        print_info("  $ docker compose down")

    print_info("")
