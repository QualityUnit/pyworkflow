"""Interactive setup command for PyWorkflow."""

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
    display_config_summary,
    find_yaml_config,
    generate_yaml_config,
    load_yaml_config,
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
    filepath,
    input_text,
    select,
    validate_module_path,
)


def _flatten_yaml_config(nested_config: dict) -> dict:
    """
    Convert nested YAML config to flat format expected by setup internals.

    Nested format (from YAML):
        {
            "module": "workflows",
            "runtime": "celery",
            "storage": {"type": "sqlite", "base_path": "..."},
            "celery": {"broker": "...", "result_backend": "..."}
        }

    Flat format (for setup):
        {
            "module": "workflows",
            "runtime": "celery",
            "storage_type": "sqlite",
            "storage_path": "...",
            "broker_url": "...",
            "result_backend": "..."
        }
    """
    storage = nested_config.get("storage", {})
    celery = nested_config.get("celery", {})

    return {
        "module": nested_config.get("module"),
        "runtime": nested_config.get("runtime", "celery"),
        "storage_type": storage.get("type", "file"),
        "storage_path": storage.get("base_path") or storage.get("path"),
        "broker_url": celery.get("broker", "redis://localhost:6379/0"),
        "result_backend": celery.get("result_backend", "redis://localhost:6379/1"),
    }


@click.command(name="setup")
@click.option(
    "--non-interactive",
    is_flag=True,
    help="Run without prompts (use defaults)",
)
@click.option(
    "--skip-docker",
    is_flag=True,
    help="Skip Docker infrastructure setup",
)
@click.option(
    "--module",
    help="Workflow module path (e.g., myapp.workflows)",
)
@click.option(
    "--storage",
    type=click.Choice(["file", "memory", "sqlite"], case_sensitive=False),
    help="Storage backend type",
)
@click.option(
    "--storage-path",
    help="Storage path for file/sqlite backends",
)
@click.pass_context
def setup(
    ctx: click.Context,
    non_interactive: bool,
    skip_docker: bool,
    module: str | None,
    storage: str | None,
    storage_path: str | None,
) -> None:
    """
    Interactive setup for PyWorkflow environment.

    This command will:
      1. Detect or create pyworkflow.config.yaml
      2. Generate docker-compose.yml and Dockerfiles
      3. Start Redis and Dashboard services via Docker
      4. Validate the complete setup

    Examples:

        # Interactive setup (recommended)
        $ pyworkflow setup

        # Non-interactive with defaults
        $ pyworkflow setup --non-interactive

        # Skip Docker setup
        $ pyworkflow setup --skip-docker

        # Specify options directly
        $ pyworkflow setup --module myapp.workflows --storage sqlite
    """
    try:
        _run_setup(
            ctx=ctx,
            non_interactive=non_interactive,
            skip_docker=skip_docker,
            module_override=module,
            storage_override=storage,
            storage_path_override=storage_path,
        )
    except click.Abort:
        print_warning("\nSetup cancelled by user")
        sys.exit(1)
    except Exception as e:
        print_error(f"\nSetup failed: {str(e)}")
        if ctx.obj.get("verbose"):
            raise
        sys.exit(1)


def _run_setup(
    ctx: click.Context,
    non_interactive: bool,
    skip_docker: bool,
    module_override: str | None,
    storage_override: str | None,
    storage_path_override: str | None,
) -> None:
    """Main setup workflow."""
    # 1. Welcome & Banner
    _print_welcome()

    # 2. Pre-flight checks
    docker_available, docker_error = check_docker_available()
    if not docker_available:
        print_warning(f"Docker: {docker_error}")
        if not skip_docker:
            if non_interactive:
                print_info("Continuing without Docker (--non-interactive mode)")
                skip_docker = True
            else:
                if not confirm("Continue without Docker?", default=False):
                    print_info("\nPlease install Docker and try again:")
                    print_info("  https://docs.docker.com/get-docker/")
                    raise click.Abort()
                skip_docker = True

    # 3. Detect existing config
    config_path = Path.cwd() / "pyworkflow.config.yaml"
    config_data = None

    existing_config = find_yaml_config()
    if existing_config and not non_interactive:
        print_info(f"\nFound existing config: {existing_config}")

        choice = select(
            "What would you like to do?",
            choices=[
                {"name": "Use existing configuration", "value": "use"},
                {"name": "View configuration first", "value": "view"},
                {"name": "Create new configuration", "value": "new"},
            ],
        )

        if choice == "use":
            config_data = _flatten_yaml_config(load_yaml_config(existing_config))
            print_success("Using existing configuration")

        elif choice == "view":
            # Display config
            print_info("\nCurrent configuration:")
            print_info("-" * 50)
            with open(existing_config) as f:
                for line in f:
                    print_info(f"  {line.rstrip()}")
            print_info("-" * 50)

            if confirm("\nUse this configuration?"):
                config_data = _flatten_yaml_config(load_yaml_config(existing_config))

    # 4. Interactive configuration (if needed)
    if not config_data:
        config_data = _run_interactive_configuration(
            non_interactive=non_interactive,
            module_override=module_override,
            storage_override=storage_override,
            storage_path_override=storage_path_override,
        )

    # 5. Display summary
    print_info("")
    # Convert flat config_data to nested structure for display
    display_config = {
        "module": config_data.get("module"),
        "runtime": config_data["runtime"],
        "storage": {
            "type": config_data["storage_type"],
            "base_path": config_data.get("storage_path"),
        },
        "celery": {
            "broker": config_data["broker_url"],
            "result_backend": config_data["result_backend"],
        },
    }
    for line in display_config_summary(display_config):
        print_info(line)

    if not non_interactive:
        if not confirm("\nProceed with this configuration?"):
            print_warning("Setup cancelled")
            raise click.Abort()

    # 6. Write configuration file
    print_info("\nGenerating configuration...")
    yaml_content = generate_yaml_config(
        module=config_data.get("module"),
        runtime=config_data["runtime"],
        storage_type=config_data["storage_type"],
        storage_path=config_data.get("storage_path"),
        broker_url=config_data["broker_url"],
        result_backend=config_data["result_backend"],
    )

    config_file_path = write_yaml_config(yaml_content, config_path, backup=True)
    print_success(f"Configuration saved: {config_file_path}")

    # 7. Docker setup (if enabled)
    dashboard_available = False
    if not skip_docker:
        dashboard_available = _setup_docker_infrastructure(
            config_data=config_data,
            non_interactive=non_interactive,
        )

    # 8. Final validation
    _validate_setup(config_data, skip_docker)

    # 9. Show next steps
    _show_next_steps(config_data, skip_docker, dashboard_available)


def _print_welcome() -> None:
    """Print welcome banner."""
    print_info("")
    print_info("=" * 60)
    print_info("  PyWorkflow Interactive Setup")
    print_info("=" * 60)
    print_info("")


def _check_sqlite_available() -> bool:
    """
    Check if SQLite is available in the Python build.

    Returns:
        True if SQLite is available, False otherwise
    """
    try:
        import sqlite3  # noqa: F401
        return True
    except ImportError:
        return False


def _run_interactive_configuration(
    non_interactive: bool,
    module_override: str | None,
    storage_override: str | None,
    storage_path_override: str | None,
) -> dict[str, str]:
    """Run interactive configuration prompts."""
    print_info("Let's configure PyWorkflow for your project...\n")

    config_data: dict[str, str] = {}

    # Module (optional)
    if module_override:
        config_data["module"] = module_override
    elif not non_interactive:
        if confirm("Do you want to specify a workflow module now?", default=False):
            module = input_text(
                "Workflow module path (e.g., myapp.workflows):",
                default="",
                validate=validate_module_path,
            )
            if module:
                config_data["module"] = module

    # Runtime (currently only Celery)
    config_data["runtime"] = "celery"
    print_info("✓ Runtime: Celery (distributed workers)")

    # Broker (currently only Redis)
    config_data["broker_url"] = "redis://localhost:6379/0"
    config_data["result_backend"] = "redis://localhost:6379/1"
    print_info("✓ Broker: Redis (will be started via Docker)")

    # Check if SQLite is available
    sqlite_available = _check_sqlite_available()

    # Storage backend
    if storage_override:
        storage_type = storage_override.lower()
        # Validate if sqlite was requested but not available
        if storage_type == "sqlite" and not sqlite_available:
            print_error("\nSQLite storage backend is not available!")
            print_info("\nYour Python installation was built without SQLite support.")
            print_info("To fix this, install SQLite development libraries and rebuild Python:")
            print_info("")
            print_info("  # On Ubuntu/Debian:")
            print_info("  sudo apt-get install libsqlite3-dev")
            print_info("")
            print_info("  # Then rebuild Python:")
            print_info("  pyenv uninstall 3.13.5")
            print_info("  pyenv install 3.13.5")
            print_info("")
            print_info("Or choose a different storage backend: --storage file")
            raise click.Abort()
    elif non_interactive:
        if sqlite_available:
            storage_type = "sqlite"
        else:
            print_error("\nSQLite storage backend is not available!")
            print_info("\nYour Python installation was built without SQLite support.")
            print_info("To fix this, install SQLite development libraries and rebuild Python:")
            print_info("")
            print_info("  # On Ubuntu/Debian:")
            print_info("  sudo apt-get install libsqlite3-dev")
            print_info("")
            print_info("  # Then rebuild Python:")
            print_info("  pyenv uninstall 3.13.5")
            print_info("  pyenv install 3.13.5")
            print_info("")
            print_info("To use setup in non-interactive mode, specify: --storage file")
            raise click.Abort()
    else:
        print_info("")
        # Build choices based on SQLite availability
        choices = []
        if sqlite_available:
            choices.append({"name": "SQLite - Single file database (recommended)", "value": "sqlite"})
        choices.extend([
            {"name": "File - JSON files on disk" + (" (recommended)" if not sqlite_available else ""), "value": "file"},
            {"name": "Memory - In-memory only (dev/testing)", "value": "memory"},
        ])

        if not sqlite_available:
            print_warning("\nNote: SQLite is not available in your Python build")
            print_info("To enable SQLite, install libsqlite3-dev and rebuild Python")
            print_info("")

        storage_type = select(
            "Choose storage backend:",
            choices=choices,
        )

    config_data["storage_type"] = storage_type

    # Storage path (for file/sqlite)
    if storage_type in ["file", "sqlite"]:
        if storage_path_override:
            final_storage_path = storage_path_override
        elif non_interactive:
            final_storage_path = (
                "./pyworkflow_data/pyworkflow.db"
                if storage_type == "sqlite"
                else "./pyworkflow_data"
            )
        else:
            default_path = (
                "./pyworkflow_data/pyworkflow.db"
                if storage_type == "sqlite"
                else "./pyworkflow_data"
            )
            final_storage_path = filepath(
                "Storage path:",
                default=default_path,
                only_directories=(storage_type == "file"),
            )

        config_data["storage_path"] = final_storage_path

    return config_data


def _setup_docker_infrastructure(
    config_data: dict[str, str],
    non_interactive: bool,
) -> bool:
    """Set up Docker infrastructure.

    Returns:
        True if dashboard is available, False otherwise
    """
    print_info("\nSetting up Docker infrastructure...")

    # Generate docker-compose.yml
    print_info("  Generating docker-compose.yml...")
    compose_content = generate_docker_compose_content(
        storage_type=config_data["storage_type"],
        storage_path=config_data.get("storage_path"),
    )

    compose_path = Path.cwd() / "docker-compose.yml"
    write_docker_compose(compose_content, compose_path)
    print_success(f"  Created: {compose_path}")

    # Pull images
    print_info("\n  Pulling Docker images...")
    print_info("")
    pull_success, output = run_docker_command(
        ["pull"],
        compose_file=compose_path,
        stream_output=True,
    )

    dashboard_available = pull_success
    if not pull_success:
        print_warning("\n  Failed to pull dashboard images")
        print_info("  Continuing with Redis setup only...")
        print_info("  You can still use PyWorkflow without the dashboard.")
    else:
        print_success("\n  Images pulled successfully")

    # Start services
    print_info("\n  Starting services...")
    print_info("")

    services_to_start = ["redis"]
    if dashboard_available:
        services_to_start.extend(["dashboard-backend", "dashboard-frontend"])

    success, output = run_docker_command(
        ["up", "-d"] + services_to_start,
        compose_file=compose_path,
        stream_output=True,
    )

    if not success:
        print_error("\n  Failed to start services")
        print_info("\n  Troubleshooting:")
        print_info("    • Check if ports 6379, 8585, 5173 are already in use")
        print_info("    • View logs: docker compose logs")
        print_info("    • Try: docker compose down && docker compose up -d")
        return False

    print_success("\n  Services started")

    # Health checks
    print_info("\n  Checking service health...")
    health_checks = {
        "Redis": {"type": "tcp", "host": "localhost", "port": 6379},
    }

    # Only check dashboard health if it was started
    if dashboard_available:
        health_checks["Dashboard Backend"] = {"type": "http", "url": "http://localhost:8585/api/v1/health"}
        health_checks["Dashboard Frontend"] = {"type": "http", "url": "http://localhost:5173"}

    health_results = check_service_health(health_checks)

    for service_name, healthy in health_results.items():
        if healthy:
            print_success(f"  {service_name}: Ready")
        else:
            print_warning(f"  {service_name}: Not responding (may still be starting)")

    return dashboard_available


def _validate_setup(config_data: dict[str, str], skip_docker: bool) -> None:
    """Validate the setup."""
    print_info("\nValidating setup...")

    checks_passed = True

    # Check config file exists
    config_path = Path.cwd() / "pyworkflow.config.yaml"
    if config_path.exists():
        print_success("  Configuration file: OK")
    else:
        print_error("  Configuration file: Missing")
        checks_passed = False

    # Check docker compose file (if docker enabled)
    if not skip_docker:
        compose_path = Path.cwd() / "docker-compose.yml"
        if compose_path.exists():
            print_success("  Docker Compose file: OK")
        else:
            print_warning("  Docker Compose file: Missing")

    if checks_passed:
        print_success("\nValidation passed!")
    else:
        print_warning("\nValidation completed with warnings")


def _show_next_steps(config_data: dict[str, str], skip_docker: bool, dashboard_available: bool = False) -> None:
    """Display next steps to the user."""
    print_info("\n" + "=" * 60)
    print_success("Setup Complete!")
    print_info("=" * 60)

    if not skip_docker:
        print_info("\nServices running:")
        print_info("  • Redis:              redis://localhost:6379")
        if dashboard_available:
            print_info("  • Dashboard:          http://localhost:5173")
            print_info("  • Dashboard API:      http://localhost:8585/docs")

    print_info("\nNext steps:")
    print_info("")
    print_info("  1. Start a Celery worker:")
    print_info("     $ pyworkflow worker run")
    print_info("")
    print_info("  2. Run a workflow:")
    print_info("     $ pyworkflow workflows run <workflow_name>")

    if not skip_docker and dashboard_available:
        print_info("")
        print_info("  3. View the dashboard:")
        print_info("     Open http://localhost:5173 in your browser")

    if not config_data.get("module"):
        print_info("")
        print_warning("  Note: No workflow module configured yet")
        print_info("        Add 'module: your.workflows' to pyworkflow.config.yaml")

    if not skip_docker:
        print_info("")
        print_info("To stop services:")
        print_info("  $ docker compose down")

    print_info("")
