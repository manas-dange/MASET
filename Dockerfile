# Production Dockerfile for MA-SET Lab 2.0
FROM python:3.11-slim

# Install system build dependencies (required for tree-sitter C extensions and git tools)
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    git \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Set working directory
WORKDIR /app

# Install Python dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir --upgrade pip && \
    pip install --no-cache-dir -r requirements.txt

# Copy application source code
COPY . .

# Ensure directory structure for runtime logs and caches
RUN mkdir -p /app/runs /app/.ma_set_cache

# Expose the visualizer & API port
EXPOSE 8765

# Configure environment defaults
ENV PYTHONUNBUFFERED=1 \
    DASHBOARD_HOST=0.0.0.0 \
    DASHBOARD_PORT=8765

# Start visualizer server
CMD ["python", "-m", "ma_set.cli", "serve", "--host", "0.0.0.0", "--port", "8765"]
