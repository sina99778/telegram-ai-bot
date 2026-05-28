# ──────────────────────────────────────────────
#  Multi-stage build for the Telegram AI Bot
# ──────────────────────────────────────────────
FROM python:3.12-slim AS base

# Prevent .pyc files and ensure real-time log output
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app

# Install curl (web healthcheck) and procps (worker healthcheck via pgrep)
RUN apt-get update && apt-get install -y --no-install-recommends curl procps \
 && rm -rf /var/lib/apt/lists/*

# ── Install dependencies first (cached layer) ──
COPY requirements.txt .
RUN pip install --no-cache-dir --upgrade pip \
 && pip install --no-cache-dir -r requirements.txt

# ── Copy project source ──
COPY . .

# ── Create unprivileged runtime user ──
# Running as root inside the container is unnecessary for this workload
# and broadens the blast radius of any container-escape vulnerability.
RUN groupadd --system app && useradd --system --gid app --no-create-home --home /app appuser \
 && chown -R appuser:app /app
USER appuser

EXPOSE 8000

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
