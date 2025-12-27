FROM python:3.11-slim

WORKDIR /app

# Install system dependencies
RUN apt-get update && \
    apt-get install -y --no-install-recommends gcc git && \
    rm -rf /var/lib/apt/lists/*

# Copy entire project for pyworkflow installation
COPY . /pyworkflow_source

# Install pyworkflow from source (force reinstall to avoid cache issues)
RUN pip install --no-cache-dir --force-reinstall /pyworkflow_source

# Install dashboard-specific dependencies
RUN pip install --no-cache-dir \
    fastapi==0.109.0 \
    uvicorn==0.27.0 \
    pydantic-settings==2.0.0

# Copy dashboard backend code
COPY dashboard/backend /app/dashboard

EXPOSE 8585

# Use absolute path since docker-compose may override working_dir
CMD ["python", "/app/dashboard/main.py"]
