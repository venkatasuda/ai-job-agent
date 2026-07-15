# frontend/Dockerfile — Streamlit dashboard container
# Separate from the main agent for independent scaling/deployment.

FROM python:3.11-slim AS base

WORKDIR /app

# System deps
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Python deps (dashboard-only subset)
COPY pyproject.toml .
RUN pip install --no-cache-dir \
    streamlit>=1.36.0 \
    plotly>=5.22.0 \
    pyyaml>=6.0.1 \
    pydantic>=2.7.0 \
    rich>=13.7.0 \
    requests>=2.31.0

# Copy app code
COPY dashboard/ ./dashboard/
COPY app/ ./app/
COPY database/ ./database/
COPY observability/ ./observability/
COPY config.yaml .

# Non-root user
RUN useradd -m -u 1001 dashboard && chown -R dashboard:dashboard /app
USER dashboard

EXPOSE 8501

HEALTHCHECK --interval=30s --timeout=10s --retries=3 \
    CMD curl -f http://localhost:8501/_stcore/health || exit 1

CMD ["streamlit", "run", "dashboard/app.py", \
     "--server.port=8501", \
     "--server.address=0.0.0.0", \
     "--server.headless=true", \
     "--browser.gatherUsageStats=false"]
