FROM python:3.11-slim

# Set working directory
WORKDIR /app

# Install system dependencies
RUN apt-get update && \
    apt-get install -y --no-install-recommends \
    gcc \
    && rm -rf /var/lib/apt/lists/*

# Copy project files
COPY pyproject.toml ./

# Install the package with dependencies
# First install build dependencies
RUN pip install --no-cache-dir --upgrade pip setuptools wheel

# Install the package in editable mode with dependencies
COPY . .
RUN pip install --no-cache-dir -e .

# Create directory for workflow data
RUN mkdir -p /app/workflows_data

# Set environment variables
ENV PYTHONUNBUFFERED=1
ENV WORKFLOWS_STORAGE_PATH=/app/workflows_data

# Default command (can be overridden)
CMD ["celery", "-A", "pyworkflow.celery.app", "worker", "--loglevel=info"]
