# ── Stage 1: Base ──────────────────────────────────────────────────────────────
FROM python:3.11-slim AS base

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /app

# System deps for pdfplumber, playwright
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc g++ libpq-dev curl git \
    && rm -rf /var/lib/apt/lists/*

# ── Stage 2: Dependencies ──────────────────────────────────────────────────────
FROM base AS deps

COPY pyproject.toml ./
RUN pip install --upgrade pip && \
    pip install ".[prod]"

# ── Stage 3: Production image ──────────────────────────────────────────────────
FROM deps AS production

# Copy application code
COPY app/ ./app/
COPY ai/ ./ai/
COPY scrapers/ ./scrapers/
COPY alerts/ ./alerts/
COPY database/ ./database/
COPY integrations/ ./integrations/
COPY observability/ ./observability/
COPY scripts/ ./scripts/
COPY config.yaml ./

# Create non-root user
RUN addgroup --system jobagent && adduser --system --group jobagent
RUN chown -R jobagent:jobagent /app
USER jobagent

# Data directories
RUN mkdir -p /app/data/raw /app/data/processed /app/resumes

EXPOSE 8080

HEALTHCHECK --interval=30s --timeout=10s --start-period=30s --retries=3 \
    CMD python scripts/healthcheck.py || exit 1

CMD ["python", "-m", "app.main"]

# ── Stage 4: Development ───────────────────────────────────────────────────────
FROM deps AS development

COPY . .
RUN pip install ".[dev]"

CMD ["python", "main.py", "--once"]
