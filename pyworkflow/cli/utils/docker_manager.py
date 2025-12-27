"""
Docker infrastructure management utilities.

This module provides functions for managing Docker Compose services,
generating docker-compose.yml files, and checking service health.
"""

import shutil
import socket
import subprocess
import time
from pathlib import Path
from typing import Any

import httpx

from pyworkflow.cli.output.formatters import print_error, print_info


def check_docker_available() -> tuple[bool, str | None]:
    """
    Check if Docker and Docker Compose are available and running.

    Returns:
        Tuple of (available, error_message)
        - (True, None) if Docker is available
        - (False, error_message) if not available

    Example:
        >>> available, error = check_docker_available()
        >>> if not available:
        ...     print(f"Docker error: {error}")
    """
    # Check if docker command exists
    if not shutil.which("docker"):
        return False, "Docker is not installed. Install from: https://docs.docker.com/get-docker/"

    # Check if docker daemon is running
    try:
        result = subprocess.run(
            ["docker", "info"],
            capture_output=True,
            text=True,
            timeout=5,
        )
        if result.returncode != 0:
            return False, "Docker daemon is not running. Please start Docker."
    except subprocess.TimeoutExpired:
        return False, "Docker daemon is not responding"
    except Exception as e:
        return False, f"Error checking Docker: {str(e)}"

    # Check docker compose command (modern: 'docker compose')
    try:
        result = subprocess.run(
            ["docker", "compose", "version"],
            capture_output=True,
            text=True,
            timeout=5,
        )
        if result.returncode == 0:
            return True, None
    except:
        pass

    # Fallback: check legacy docker-compose
    if shutil.which("docker-compose"):
        return True, None

    return False, "Docker Compose is not available. Upgrade Docker to get 'docker compose'."


def get_pyworkflow_root() -> str:
    """
    Find the PyWorkflow project root directory.

    Returns:
        Absolute path to pyworkflow project root
    """
    import pyworkflow
    from pathlib import Path

    # Get the pyworkflow package location
    pyworkflow_init = Path(pyworkflow.__file__)
    # Go up from pyworkflow/__init__.py to project root
    project_root = pyworkflow_init.parent.parent

    return str(project_root.absolute())


def generate_docker_compose_content(
    storage_type: str,
    storage_path: str | None = None,
) -> str:
    """
    Generate docker-compose.yml content for PyWorkflow services.

    Args:
        storage_type: Storage backend type ("sqlite", "file", "memory")
        storage_path: Path to storage (for file/sqlite backends)

    Returns:
        docker-compose.yml content as string

    Example:
        >>> compose_content = generate_docker_compose_content(
        ...     storage_type="sqlite",
        ...     storage_path="./pyworkflow_data/pyworkflow.db"
        ... )
    """
    # Get the PyWorkflow project root for build context
    pyworkflow_root = get_pyworkflow_root()

    # Normalize storage path - extract directory for volume mapping
    if not storage_path:
        volume_mapping = "./pyworkflow_data"
    else:
        # For SQLite, storage_path is a file (e.g., ./pyworkflow_data/pyworkflow.db)
        # We need to mount the directory, not the file
        from pathlib import Path
        path_obj = Path(storage_path)
        if storage_type == "sqlite" and path_obj.suffix == ".db":
            # Mount the parent directory
            volume_mapping = str(path_obj.parent)
        else:
            # For file storage, it's already a directory
            volume_mapping = storage_path

    # Ensure volume_mapping is a proper path (starts with ./ or / for bind mount)
    if not volume_mapping.startswith(('./', '/', '~')):
        volume_mapping = f"./{volume_mapping}"

    template = f"""services:
  redis:
    image: redis:7-alpine
    container_name: pyworkflow-redis
    ports:
      - "6379:6379"
    volumes:
      - redis_data:/data
    healthcheck:
      test: ["CMD", "redis-cli", "ping"]
      interval: 5s
      timeout: 3s
      retries: 5
    restart: unless-stopped

  dashboard-backend:
    build:
      context: {pyworkflow_root}
      dockerfile: dashboard.backend.Dockerfile
    container_name: pyworkflow-dashboard-backend
    ports:
      - "8585:8585"
    environment:
      - DASHBOARD_STORAGE_TYPE={storage_type}
      - DASHBOARD_STORAGE_PATH=/app/pyworkflow_data
      - DASHBOARD_HOST=0.0.0.0
      - DASHBOARD_PORT=8585
      - DASHBOARD_CORS_ORIGINS=["http://localhost:5173","http://localhost:3000"]
    volumes:
      - ./pyworkflow.config.yaml:/app/pyworkflow.config.yaml:ro
      - {volume_mapping}:/app/pyworkflow_data
    depends_on:
      redis:
        condition: service_healthy
    restart: unless-stopped

  dashboard-frontend:
    build:
      context: {pyworkflow_root}
      dockerfile: dashboard.frontend.Dockerfile
    container_name: pyworkflow-dashboard-frontend
    ports:
      - "5173:80"
    environment:
      - VITE_API_URL=http://localhost:8585
    depends_on:
      - dashboard-backend
    restart: unless-stopped

volumes:
  redis_data:
    driver: local
"""

    return template


def write_docker_compose(content: str, path: Path) -> None:
    """
    Write docker-compose.yml to file.

    Args:
        content: docker-compose.yml content
        path: Target file path

    Example:
        >>> compose_content = generate_docker_compose_content("sqlite")
        >>> write_docker_compose(compose_content, Path("./docker-compose.yml"))
    """
    path.write_text(content)


def get_docker_compose_command() -> list[str]:
    """
    Get the appropriate docker compose command for the platform.

    Returns:
        Command as list (e.g., ["docker", "compose"] or ["docker-compose"])

    Example:
        >>> cmd = get_docker_compose_command()
        >>> # Use in subprocess: subprocess.run(cmd + ["up", "-d"])
    """
    # Try modern 'docker compose' first
    try:
        result = subprocess.run(
            ["docker", "compose", "version"],
            capture_output=True,
            timeout=2,
        )
        if result.returncode == 0:
            return ["docker", "compose"]
    except:
        pass

    # Fall back to legacy 'docker-compose'
    if shutil.which("docker-compose"):
        return ["docker-compose"]

    # Default to modern syntax
    return ["docker", "compose"]


def run_docker_command(
    args: list[str],
    compose_file: Path | None = None,
    capture_output: bool = False,
    stream_output: bool = False,
) -> tuple[bool, str]:
    """
    Run a docker compose command.

    Args:
        args: Command arguments (e.g., ["up", "-d"])
        compose_file: Path to docker-compose.yml (default: ./docker-compose.yml)
        capture_output: If True, capture and return output
        stream_output: If True, stream output to console in real-time

    Returns:
        Tuple of (success, output_or_error_message)

    Example:
        >>> success, output = run_docker_command(["up", "-d"])
        >>> if not success:
        ...     print(f"Error: {output}")
    """
    cmd = get_docker_compose_command()

    if compose_file:
        cmd.extend(["-f", str(compose_file)])

    cmd.extend(args)

    try:
        if stream_output:
            # Stream output in real-time with spinner
            import sys
            import threading

            # ANSI codes
            GRAY = "\033[90m"
            RESET = "\033[0m"
            CLEAR_LINE = "\033[K"
            SAVE_CURSOR = "\033[s"
            RESTORE_CURSOR = "\033[u"

            spinner_frames = ["⠋", "⠙", "⠹", "⠸", "⠼", "⠴", "⠦", "⠧", "⠇", "⠏"]
            spinner_running = True
            current_frame = [0]

            def spinner_thread():
                """Background thread for spinner animation."""
                while spinner_running:
                    frame = spinner_frames[current_frame[0] % len(spinner_frames)]
                    # Print spinner at current position
                    sys.stdout.write(f"{GRAY}{frame} Working...{RESET}{CLEAR_LINE}\r")
                    sys.stdout.flush()
                    current_frame[0] += 1
                    import time
                    time.sleep(0.1)
                # Clear spinner when done
                sys.stdout.write(f"{CLEAR_LINE}\r")
                sys.stdout.flush()

            # Start spinner in background
            spinner = threading.Thread(target=spinner_thread, daemon=True)
            spinner.start()

            process = subprocess.Popen(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                bufsize=1,
            )

            output_lines = []
            if process.stdout:
                for line in process.stdout:
                    # Clear spinner line, print log in gray, restore spinner
                    sys.stdout.write(f"{CLEAR_LINE}\r")
                    print(f"{GRAY}    {line.rstrip()}{RESET}")
                    output_lines.append(line)

            process.wait(timeout=600)  # 10 minute timeout for builds
            spinner_running = False
            spinner.join(timeout=0.5)

            output = "".join(output_lines)

            if process.returncode == 0:
                return True, output if capture_output else "Success"
            else:
                return False, output

        else:
            # Capture output
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=300,  # 5 minute timeout
            )

            if result.returncode == 0:
                return True, result.stdout if capture_output else "Success"
            else:
                error_msg = result.stderr or result.stdout or "Unknown error"
                return False, error_msg

    except subprocess.TimeoutExpired:
        return False, "Command timed out"
    except Exception as e:
        return False, f"Error running docker command: {str(e)}"


def wait_for_tcp_port(
    host: str,
    port: int,
    timeout: int = 30,
) -> bool:
    """
    Wait for a TCP port to become available.

    Args:
        host: Hostname or IP address
        port: Port number
        timeout: Maximum wait time in seconds

    Returns:
        True if port is available, False if timeout

    Example:
        >>> if wait_for_tcp_port("localhost", 6379, timeout=10):
        ...     print("Redis is ready!")
    """
    start_time = time.time()

    while time.time() - start_time < timeout:
        try:
            sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            sock.settimeout(1)
            result = sock.connect_ex((host, port))
            sock.close()

            if result == 0:
                return True

        except Exception:
            pass

        time.sleep(0.5)

    return False


def wait_for_http_service(
    url: str,
    timeout: int = 30,
    expected_status: int = 200,
) -> bool:
    """
    Wait for an HTTP service to become available.

    Args:
        url: Service URL to check
        timeout: Maximum wait time in seconds
        expected_status: Expected HTTP status code

    Returns:
        True if service responds with expected status, False if timeout

    Example:
        >>> if wait_for_http_service("http://localhost:8585/api/v1/health"):
        ...     print("Dashboard backend is ready!")
    """
    start_time = time.time()

    while time.time() - start_time < timeout:
        try:
            response = httpx.get(url, timeout=2.0)
            if response.status_code == expected_status or response.status_code < 500:
                return True
        except (httpx.ConnectError, httpx.TimeoutException):
            pass
        except Exception:
            # Other errors might indicate the service is up but returning an error
            return True

        time.sleep(1)

    return False


def create_backend_dockerfile(target_path: Path) -> None:
    """
    Create Dockerfile for dashboard backend.

    Args:
        target_path: Where to write the Dockerfile
    """
    dockerfile_content = """FROM python:3.11-slim

WORKDIR /app

# Install system dependencies
RUN apt-get update && \\
    apt-get install -y --no-install-recommends gcc git && \\
    rm -rf /var/lib/apt/lists/*

# Copy entire project for pyworkflow installation
COPY . /pyworkflow_source

# Install pyworkflow from source
RUN pip install --no-cache-dir /pyworkflow_source

# Install dashboard-specific dependencies
RUN pip install --no-cache-dir \\
    fastapi==0.109.0 \\
    uvicorn==0.27.0 \\
    pydantic-settings==2.0.0

# Copy dashboard backend code
COPY dashboard/backend /app/dashboard

WORKDIR /app/dashboard

EXPOSE 8585

CMD ["python", "main.py"]
"""
    target_path.write_text(dockerfile_content)


def create_frontend_dockerfile(target_path: Path) -> None:
    """
    Create Dockerfile for dashboard frontend.

    Args:
        target_path: Where to write the Dockerfile
    """
    dockerfile_content = """FROM node:20-alpine AS builder

WORKDIR /app

# Copy package files
COPY dashboard/frontend/package*.json ./

# Install dependencies
RUN npm ci

# Copy source code
COPY dashboard/frontend .

# Build for production
RUN npm run build

# Production stage with nginx
FROM nginx:alpine

# Copy built assets
COPY --from=builder /app/dist /usr/share/nginx/html

# Create nginx configuration
RUN echo 'server { \\
    listen 80; \\
    server_name localhost; \\
    root /usr/share/nginx/html; \\
    index index.html; \\
    location / { \\
        try_files $uri $uri/ /index.html; \\
    } \\
    # Enable gzip compression \\
    gzip on; \\
    gzip_types text/plain text/css application/json application/javascript text/xml application/xml application/xml+rss text/javascript; \\
}' > /etc/nginx/conf.d/default.conf

EXPOSE 80

CMD ["nginx", "-g", "daemon off;"]
"""
    target_path.write_text(dockerfile_content)


def create_dockerfiles() -> tuple[Path, Path]:
    """
    Create both backend and frontend Dockerfiles in PyWorkflow project root.

    Returns:
        Tuple of (backend_dockerfile_path, frontend_dockerfile_path)

    Example:
        >>> backend_df, frontend_df = create_dockerfiles()
        >>> print(f"Created {backend_df} and {frontend_df}")
    """
    # Use project root for Dockerfiles (where docker-compose will build)
    project_root = Path(get_pyworkflow_root())

    backend_dockerfile = project_root / "dashboard.backend.Dockerfile"
    frontend_dockerfile = project_root / "dashboard.frontend.Dockerfile"

    create_backend_dockerfile(backend_dockerfile)
    create_frontend_dockerfile(frontend_dockerfile)

    return backend_dockerfile, frontend_dockerfile


def check_service_health(service_checks: dict[str, dict[str, Any]]) -> dict[str, bool]:
    """
    Check health of multiple services.

    Args:
        service_checks: Dict mapping service names to check configs
            Example:
            {
                "redis": {"type": "tcp", "host": "localhost", "port": 6379},
                "backend": {"type": "http", "url": "http://localhost:8585/api/v1/health"}
            }

    Returns:
        Dict mapping service names to health status (True/False)

    Example:
        >>> checks = {
        ...     "Redis": {"type": "tcp", "host": "localhost", "port": 6379},
        ...     "Dashboard": {"type": "http", "url": "http://localhost:8585/api/v1/health"}
        ... }
        >>> results = check_service_health(checks)
        >>> for service, healthy in results.items():
        ...     print(f"{service}: {'✓' if healthy else '✗'}")
    """
    results = {}

    for service_name, check_config in service_checks.items():
        check_type = check_config.get("type")

        if check_type == "tcp":
            host = check_config.get("host", "localhost")
            port = check_config["port"]
            results[service_name] = wait_for_tcp_port(host, port, timeout=5)

        elif check_type == "http":
            url = check_config["url"]
            expected_status = check_config.get("expected_status", 200)
            results[service_name] = wait_for_http_service(url, timeout=5, expected_status=expected_status)

        else:
            results[service_name] = False

    return results


def get_service_logs(
    service_name: str,
    compose_file: Path | None = None,
    lines: int = 50,
) -> str:
    """
    Get logs from a docker compose service.

    Args:
        service_name: Name of the service
        compose_file: Path to docker-compose.yml
        lines: Number of log lines to retrieve

    Returns:
        Service logs as string

    Example:
        >>> logs = get_service_logs("dashboard-backend", lines=20)
        >>> print(logs)
    """
    success, output = run_docker_command(
        ["logs", "--tail", str(lines), service_name],
        compose_file=compose_file,
        capture_output=True,
    )

    return output if success else f"Error getting logs: {output}"


def stop_services(compose_file: Path | None = None) -> tuple[bool, str]:
    """
    Stop all docker compose services.

    Args:
        compose_file: Path to docker-compose.yml

    Returns:
        Tuple of (success, message)

    Example:
        >>> success, msg = stop_services()
        >>> if success:
        ...     print("Services stopped successfully")
    """
    return run_docker_command(["down"], compose_file=compose_file)


def restart_service(
    service_name: str,
    compose_file: Path | None = None,
) -> tuple[bool, str]:
    """
    Restart a specific docker compose service.

    Args:
        service_name: Name of the service to restart
        compose_file: Path to docker-compose.yml

    Returns:
        Tuple of (success, message)

    Example:
        >>> success, msg = restart_service("dashboard-backend")
    """
    return run_docker_command(["restart", service_name], compose_file=compose_file)
