# syntax=docker/dockerfile:1
FROM python:3.11-slim

WORKDIR /app

# System deps: build-essential for any C-ext wheel builds, curl for healthchecks
# psycopg[binary] ships its own libpq — no libpq-dev needed
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    curl \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
# Install CPU-only torch first to avoid downloading the 532 MB GPU wheel
RUN pip install --no-cache-dir --timeout 300 \
    torch --index-url https://download.pytorch.org/whl/cpu
# Pre-install psycopg binary wheel so langgraph-checkpoint-postgres
# doesn't trigger psycopg-c compilation (which fails on slim images)
RUN pip install --no-cache-dir "psycopg[binary]>=3.1" psycopg-binary
RUN pip install --no-cache-dir --timeout 300 -r requirements.txt

# Playwright Chromium for brand scraping
RUN playwright install chromium --with-deps

COPY . .

EXPOSE 8000

# Default: API server. Override CMD in docker-compose for worker / beat.
CMD ["sh", "-c", "alembic upgrade head && uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-8000}"]
