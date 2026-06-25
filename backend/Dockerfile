# =============================================================================
# Stage 1 — builder
# =============================================================================
FROM python:3.11-slim AS builder

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    VIRTUAL_ENV=/opt/venv

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
        build-essential libpq-dev libffi-dev libssl-dev gcc curl \
    && rm -rf /var/lib/apt/lists/*

RUN python -m venv $VIRTUAL_ENV
ENV PATH="$VIRTUAL_ENV/bin:$PATH"

COPY requirements.txt .
RUN pip install --upgrade pip && pip install -r requirements.txt

# =============================================================================
# Stage 2 — production
# =============================================================================
FROM python:3.11-slim AS production

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    VIRTUAL_ENV=/opt/venv \
    PATH="/opt/venv/bin:$PATH"

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
        libpq5 libmagic1 tesseract-ocr tesseract-ocr-eng curl \
        libglib2.0-0 libgl1 libgomp1 \
    && rm -rf /var/lib/apt/lists/*

COPY --from=builder /opt/venv /opt/venv

# Pre-download PaddleOCR models during build so the container starts instantly.
# Falls back gracefully if the build host has no internet (models download on first use).
RUN python -c "\
from paddleocr import PaddleOCR; \
PaddleOCR(use_angle_cls=True, lang='en', use_gpu=False, show_log=False, enable_mkldnn=False)" \
    || echo '[warn] PaddleOCR model pre-download skipped — will download on first use'

# Copy application source
COPY . .

# Pre-create writable runtime directories (bind-mounts will overlay these
# but this ensures they exist and have the right mode if not mounted)
RUN mkdir -p /app/uploads /app/reports /app/logs \
    && chmod -R 777 /app/uploads /app/reports /app/logs

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=10s --start-period=20s --retries=3 \
    CMD curl -f http://localhost:8000/health || exit 1

# Runs as root — acceptable for a private factory LAN deployment.
# The network boundary provides the security isolation.
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "4"]
