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
    generate_cassandra_docker_compose_content,
    generate_docker_compose_content,
    generate_mysql_docker_compose_content,
    generate_postgres_docker_compose_content,
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
    type=click.Choice(
        ["file", "memory", "sqlite", "postgres", "mysql", "dynamodb", "cassandra"],
        case_sensitive=False,
    ),
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
        if ctx.obj and ctx.obj.get("verbose"):
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

    # Parse Cassandra contact points from comma-separated string to list
    cassandra_contact_points = None
    if config_data.get("cassandra_contact_points"):
        contact_points_str = config_data["cassandra_contact_points"]
        cassandra_contact_points = [cp.strip() for cp in contact_points_str.split(",")]

    yaml_content = generate_yaml_config(
        module=config_data.get("module"),
        runtime=config_data["runtime"],
        storage_type=config_data["storage_type"],
        storage_path=config_data.get("storage_path"),
        broker_url=config_data["broker_url"],
        result_backend=config_data["result_backend"],
        postgres_host=config_data.get("postgres_host"),
        postgres_port=config_data.get("postgres_port"),
        postgres_user=config_data.get("postgres_user"),
        postgres_password=config_data.get("postgres_password"),
        postgres_database=config_data.get("postgres_database"),
        mysql_host=config_data.get("mysql_host"),
        mysql_port=config_data.get("mysql_port"),
        mysql_user=config_data.get("mysql_user"),
        mysql_password=config_data.get("mysql_password"),
        mysql_database=config_data.get("mysql_database"),
        dynamodb_table_name=config_data.get("dynamodb_table_name"),
        dynamodb_region=config_data.get("dynamodb_region"),
        dynamodb_endpoint_url=config_data.get("dynamodb_endpoint_url"),
        cassandra_contact_points=cassandra_contact_points,
        cassandra_port=config_data.get("cassandra_port"),
        cassandra_keyspace=config_data.get("cassandra_keyspace"),
        cassandra_user=config_data.get("cassandra_user"),
        cassandra_password=config_data.get("cassandra_password"),
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


def _check_postgres_available() -> bool:
    """
    Check if asyncpg is installed for PostgreSQL support.

    Returns:
        True if asyncpg is available, False otherwise
    """
    try:
        import asyncpg  # noqa: F401

        return True
    except ImportError:
        return False


def _check_cassandra_available() -> bool:
    """
    Check if cassandra-driver is installed for Cassandra support.

    Returns:
        True if cassandra-driver is available, False otherwise
    """
    try:
        from cassandra.cluster import Cluster  # noqa: F401

        return True
    except ImportError:
        return False


def _check_mysql_available() -> bool:
    """
    Check if aiomysql is installed for MySQL support.

    Returns:
        True if aiomysql is available, False otherwise
    """
    try:
        import aiomysql  # noqa: F401

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

    # Check if SQLite, PostgreSQL, Cassandra and MySQL are available
    sqlite_available = _check_sqlite_available()
    postgres_available = _check_postgres_available()
    cassandra_available = _check_cassandra_available()
    mysql_available = _check_mysql_available()

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
        # Validate if postgres was requested but not available
        if storage_type == "postgres" and not postgres_available:
            print_error("\nPostgreSQL storage backend is not available!")
            print_info("\nasyncpg package is not installed.")
            print_info("To fix this, install asyncpg:")
            print_info("")
            print_info("  pip install asyncpg")
            print_info("")
            print_info("Or choose a different storage backend: --storage sqlite")
            raise click.Abort()
        # Validate if cassandra was requested but not available
        if storage_type == "cassandra" and not cassandra_available:
            print_error("\nCassandra storage backend is not available!")
            print_info("\ncassandra-driver package is not installed.")
            print_info("To fix this, install cassandra-driver:")
            print_info("")
            print_info("  pip install cassandra-driver")
            print_info("")
            print_info("Or choose a different storage backend: --storage sqlite")
            raise click.Abort()
        # Validate if mysql was requested but not available
        mysql_available = _check_mysql_available()
        if storage_type == "mysql" and not mysql_available:
            print_error("\nMySQL storage backend is not available!")
            print_info("\naiomysql package is not installed.")
            print_info("To fix this, install aiomysql:")
            print_info("")
            print_info("  pip install aiomysql")
            print_info("")
            print_info("Or choose a different storage backend: --storage sqlite")
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
        # Build choices based on available backends
        choices = []
        if sqlite_available:
            choices.append(
                {"name": "SQLite - Single file database (recommended)", "value": "sqlite"}
            )
        if postgres_available:
            choices.append(
                {"name": "PostgreSQL - Scalable production database", "value": "postgres"}
            )
        if cassandra_available:
            choices.append(
                {"name": "Cassandra - Distributed NoSQL database (scalable)", "value": "cassandra"}
            )
        if mysql_available:
            choices.append(
                {"name": "MySQL - Popular open-source relational database", "value": "mysql"}
            )
        choices.extend(
            [
                {
                    "name": "File - JSON files on disk"
                    + (" (recommended)" if not sqlite_available else ""),
                    "value": "file",
                },
                {"name": "Memory - In-memory only (dev/testing)", "value": "memory"},
                {"name": "DynamoDB - AWS serverless storage (cloud)", "value": "dynamodb"},
            ]
        )

        if not sqlite_available:
            print_warning("\nNote: SQLite is not available in your Python build")
            print_info("To enable SQLite, install libsqlite3-dev and rebuild Python")
            print_info("")

        if not postgres_available:
            print_info("Note: PostgreSQL backend available after: pip install asyncpg")
            print_info("")

        if not cassandra_available:
            print_info("Note: Cassandra backend available after: pip install cassandra-driver")
            print_info("")

        if not mysql_available:
            print_info("Note: MySQL backend available after: pip install aiomysql")
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

    # PostgreSQL connection (for postgres backend)
    if storage_type == "postgres":
        if non_interactive:
            # Use default connection settings for non-interactive mode
            config_data["postgres_host"] = "localhost"
            config_data["postgres_port"] = "5432"
            config_data["postgres_user"] = "pyworkflow"
            config_data["postgres_password"] = "pyworkflow"
            config_data["postgres_database"] = "pyworkflow"
        else:
            print_info("\nConfigure PostgreSQL connection:")
            config_data["postgres_host"] = input_text(
                "PostgreSQL host:",
                default="localhost",
            )
            config_data["postgres_port"] = input_text(
                "PostgreSQL port:",
                default="5432",
            )
            config_data["postgres_database"] = input_text(
                "Database name:",
                default="pyworkflow",
            )
            config_data["postgres_user"] = input_text(
                "Database user:",
                default="pyworkflow",
            )
            config_data["postgres_password"] = input_text(
                "Database password:",
                default="pyworkflow",
            )

    # MySQL connection (for mysql backend)
    elif storage_type == "mysql":
        if non_interactive:
            # Use default connection settings for non-interactive mode
            config_data["mysql_host"] = "localhost"
            config_data["mysql_port"] = "3306"
            config_data["mysql_user"] = "pyworkflow"
            config_data["mysql_password"] = "pyworkflow"
            config_data["mysql_database"] = "pyworkflow"
        else:
            print_info("\nConfigure MySQL connection:")
            config_data["mysql_host"] = input_text(
                "MySQL host:",
                default="localhost",
            )
            config_data["mysql_port"] = input_text(
                "MySQL port:",
                default="3306",
            )
            config_data["mysql_database"] = input_text(
                "Database name:",
                default="pyworkflow",
            )
            config_data["mysql_user"] = input_text(
                "Database user:",
                default="pyworkflow",
            )
            config_data["mysql_password"] = input_text(
                "Database password:",
                default="pyworkflow",
            )

    # DynamoDB configuration
    elif storage_type == "dynamodb":
        if non_interactive:
            config_data["dynamodb_table_name"] = "pyworkflow"
            config_data["dynamodb_region"] = "us-east-1"
        else:
            table_name = input_text(
                "DynamoDB table name:",
                default="pyworkflow",
            )
            config_data["dynamodb_table_name"] = table_name

            region = input_text(
                "AWS region:",
                default="us-east-1",
            )
            config_data["dynamodb_region"] = region

            # Optional local endpoint for development
            if confirm("Use local DynamoDB endpoint (for development)?", default=False):
                endpoint = input_text(
                    "Local endpoint URL:",
                    default="http://localhost:8000",
                )
                config_data["dynamodb_endpoint_url"] = endpoint

    # Cassandra configuration
    elif storage_type == "cassandra":
        if non_interactive:
            config_data["cassandra_contact_points"] = "localhost"
            config_data["cassandra_port"] = "9042"
            config_data["cassandra_keyspace"] = "pyworkflow"
        else:
            print_info("\nConfigure Cassandra connection:")
            contact_points = input_text(
                "Cassandra contact points (comma-separated):",
                default="localhost",
            )
            config_data["cassandra_contact_points"] = contact_points

            config_data["cassandra_port"] = input_text(
                "Cassandra port:",
                default="9042",
            )
            config_data["cassandra_keyspace"] = input_text(
                "Keyspace name:",
                default="pyworkflow",
            )

            # Optional authentication
            if confirm("Use Cassandra authentication?", default=False):
                config_data["cassandra_user"] = input_text(
                    "Cassandra user:",
                    default="cassandra",
                )
                config_data["cassandra_password"] = input_text(
                    "Cassandra password:",
                    default="cassandra",
                )

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

    # Generate docker-compose.yml based on storage type
    print_info("  Generating docker-compose.yml...")
    storage_type = config_data["storage_type"]

    if storage_type == "postgres":
        compose_content = generate_postgres_docker_compose_content(
            postgres_host="postgres",
            postgres_port=int(config_data.get("postgres_port", "5432")),
            postgres_user=config_data.get("postgres_user", "pyworkflow"),
            postgres_password=config_data.get("postgres_password", "pyworkflow"),
            postgres_database=config_data.get("postgres_database", "pyworkflow"),
        )
    elif storage_type == "cassandra":
        compose_content = generate_cassandra_docker_compose_content(
            cassandra_host="cassandra",
            cassandra_port=int(config_data.get("cassandra_port", "9042")),
            cassandra_keyspace=config_data.get("cassandra_keyspace", "pyworkflow"),
            cassandra_user=config_data.get("cassandra_user"),
            cassandra_password=config_data.get("cassandra_password"),
        )
    elif storage_type == "mysql":
        compose_content = generate_mysql_docker_compose_content(
            mysql_host="mysql",
            mysql_port=int(config_data.get("mysql_port", "3306")),
            mysql_user=config_data.get("mysql_user", "pyworkflow"),
            mysql_password=config_data.get("mysql_password", "pyworkflow"),
            mysql_database=config_data.get("mysql_database", "pyworkflow"),
        )
    else:
        compose_content = generate_docker_compose_content(
            storage_type=storage_type,
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

    # Include postgres/cassandra/mysql in services to start if using those storage types
    services_to_start = ["redis"]
    if storage_type == "postgres":
        services_to_start.insert(0, "postgres")
    elif storage_type == "cassandra":
        services_to_start.insert(0, "cassandra")
    elif storage_type == "mysql":
        services_to_start.insert(0, "mysql")
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
        ports_in_use = "6379, 8585, 5173"
        if storage_type == "postgres":
            postgres_port = config_data.get("postgres_port", "5432")
            ports_in_use = f"{postgres_port}, {ports_in_use}"
        elif storage_type == "cassandra":
            cassandra_port = config_data.get("cassandra_port", "9042")
            ports_in_use = f"{cassandra_port}, {ports_in_use}"
        elif storage_type == "mysql":
            mysql_port = config_data.get("mysql_port", "3306")
            ports_in_use = f"{mysql_port}, {ports_in_use}"
        print_info(f"    • Check if ports {ports_in_use} are already in use")
        print_info("    • View logs: docker compose logs")
        print_info("    • Try: docker compose down && docker compose up -d")
        return False

    print_success("\n  Services started")

    # Health checks
    print_info("\n  Checking service health...")
    health_checks = {
        "Redis": {"type": "tcp", "host": "localhost", "port": 6379},
    }

    # Add PostgreSQL health check if using postgres storage
    if storage_type == "postgres":
        pg_port = int(config_data.get("postgres_port", "5432"))
        health_checks["PostgreSQL"] = {"type": "tcp", "host": "localhost", "port": pg_port}

    # Add Cassandra health check if using cassandra storage
    if storage_type == "cassandra":
        cass_port = int(config_data.get("cassandra_port", "9042"))
        health_checks["Cassandra"] = {"type": "tcp", "host": "localhost", "port": cass_port}

    # Add MySQL health check if using mysql storage
    if storage_type == "mysql":
        mysql_port_num = int(config_data.get("mysql_port", "3306"))
        health_checks["MySQL"] = {"type": "tcp", "host": "localhost", "port": mysql_port_num}

    # Only check dashboard health if it was started
    if dashboard_available:
        health_checks["Dashboard Backend"] = {
            "type": "http",
            "url": "http://localhost:8585/api/v1/health",
        }
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


def _show_next_steps(
    config_data: dict[str, str], skip_docker: bool, dashboard_available: bool = False
) -> None:
    """Display next steps to the user."""
    print_info("\n" + "=" * 60)
    print_success("Setup Complete!")
    print_info("=" * 60)

    if not skip_docker:
        print_info("\nServices running:")
        if config_data.get("storage_type") == "postgres":
            postgres_port = config_data.get("postgres_port", "5432")
            print_info(f"  • PostgreSQL:         localhost:{postgres_port}")
        elif config_data.get("storage_type") == "cassandra":
            cassandra_port = config_data.get("cassandra_port", "9042")
            print_info(f"  • Cassandra:          localhost:{cassandra_port}")
        elif config_data.get("storage_type") == "mysql":
            mysql_port = config_data.get("mysql_port", "3306")
            print_info(f"  • MySQL:              localhost:{mysql_port}")
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
