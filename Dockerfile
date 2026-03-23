FROM python:3.13-slim AS base

WORKDIR /app

# Install system deps (none needed for now, but layer is cached)
RUN apt-get update && apt-get install -y --no-install-recommends \
    && rm -rf /var/lib/apt/lists/*

# Install Python dependencies
COPY pyproject.toml .
RUN pip install --no-cache-dir -e "." 2>/dev/null || true

# Copy source
COPY . .
RUN pip install --no-cache-dir -e "."

# Non-root user
RUN useradd --create-home appuser
USER appuser

EXPOSE 8000

# Default: run the dashboard
CMD ["uvicorn", "src.dashboard.app:app", "--host", "0.0.0.0", "--port", "8000"]
