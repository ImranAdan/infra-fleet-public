# Multi-stage build for production optimization
FROM python:3.13-slim AS builder

# Install build dependencies for packages that need compilation (e.g., psutil)
# Also run upgrade to get latest security patches
RUN apt-get update && apt-get upgrade -y && apt-get install -y --no-install-recommends \
    gcc \
    python3-dev \
    && rm -rf /var/lib/apt/lists/*

# Upgrade pip toolchain to fix CVE-2026-23949 (jaraco.context) and CVE-2026-24049 (wheel)
RUN pip install --no-cache-dir --upgrade pip setuptools wheel

WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir --user -r requirements.txt

FROM python:3.13-slim AS runtime

# Apply security patches for CVE-2025-15467 and CVE-2025-69419 (openssl)
RUN apt-get update && apt-get upgrade -y && rm -rf /var/lib/apt/lists/*

# Create non-root user for security
RUN useradd --create-home --shell /bin/bash app

WORKDIR /app

# Copy Python packages from builder stage
COPY --from=builder /root/.local /home/app/.local

# Copy application code
COPY src/ ./src/

# Switch to non-root user
USER app

# Add local Python packages to PATH and set PYTHONPATH
ENV PATH=/home/app/.local/bin:$PATH
ENV PYTHONPATH=/app/src

# Application version - injected at build time from release tag
ARG APP_VERSION=dev
ENV APP_VERSION=${APP_VERSION}

EXPOSE 8080

# Use environment variable for port, defaulting to 8080
# --timeout 120: Required for cluster distributed load tests. The /partials/cluster-result
# endpoint uses ThreadPoolExecutor to send concurrent requests to /load/cpu/work. With only
# 2 sync workers, Worker 1 blocks waiting for responses while Worker 2 processes requests
# sequentially. Default 30s timeout causes Worker 1 to be killed before all requests complete.
CMD ["sh", "-c", "gunicorn --bind 0.0.0.0:${PORT:-8080} --workers 2 --timeout 120 load_harness.wsgi:app"]