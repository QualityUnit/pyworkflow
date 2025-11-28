FROM python:3.11-slim

# Set working directory
WORKDIR /app

# Install system dependencies
RUN apt-get update && \
    apt-get install -y --no-install-recommends \
    gcc \
    && rm -rf /var/lib/apt/lists/*

# Install Poetry
RUN pip install --no-cache-dir poetry==1.7.1

# Copy poetry files
COPY pyproject.toml poetry.lock* ./

# Configure poetry to not create virtual env (we're in a container)
RUN poetry config virtualenvs.create false

# Install dependencies
RUN poetry install --no-root --no-dev

# Copy application code
COPY . .

# Install the package
RUN poetry install --no-dev

# Create directory for workflow data
RUN mkdir -p /app/workflows_data

# Set environment variables
ENV PYTHONUNBUFFERED=1
ENV WORKFLOWS_STORAGE_PATH=/app/workflows_data

# Default command (can be overridden)
CMD ["celery", "-A", "pyworkflow.celery.app", "worker", "--loglevel=info"]
