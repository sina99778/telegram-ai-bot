# ──────────────────────────────────────────────
#  Multi-stage build for the Telegram AI Bot
# ──────────────────────────────────────────────
FROM python:3.12-slim AS base

# Prevent .pyc files and ensure real-time log output
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app

# ── Install dependencies first (cached layer) ──
COPY requirements.txt .
RUN pip install --no-cache-dir --upgrade pip \
 && pip install --no-cache-dir -r requirements.txt

# ── Copy project source ──
COPY . .

EXPOSE 8000

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
