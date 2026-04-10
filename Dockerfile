# ---- GIF Studio ----
# Multi-stage build: dependencies → app
#
# NOTE: Apple Vision background removal (swiftc) is macOS-only and
# won't work in this container. All other features work fine.

# ============================================================
# Stage 1: Base with system dependencies
# ============================================================
FROM python:3.12-slim AS base

# Install system tools:
#   ffmpeg/ffprobe — video processing
#   gifsicle      — lossy GIF compression
RUN apt-get update && \
    apt-get install -y --no-install-recommends \
        ffmpeg \
        gifsicle \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# ============================================================
# Stage 2: Python dependencies (cached layer)
# ============================================================
FROM base AS deps

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# ============================================================
# Stage 3: Application
# ============================================================
FROM deps AS app

# Copy application code
COPY app.py .
COPY templates/ templates/
COPY scripts/ scripts/

# Don't run as root in production
RUN useradd --create-home appuser
USER appuser

# Flask listens on this port
EXPOSE 5001

# Use gunicorn for production (more robust than Flask dev server)
# Install gunicorn in this stage
USER root
RUN pip install --no-cache-dir gunicorn
USER appuser

# Health check
HEALTHCHECK --interval=30s --timeout=5s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:5001/')" || exit 1

# Run with gunicorn: 4 workers, bind to all interfaces
CMD ["gunicorn", "--bind", "0.0.0.0:5001", "--workers", "4", "--timeout", "300", "app:app"]
