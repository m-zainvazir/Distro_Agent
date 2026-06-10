# syntax=docker/dockerfile:1
FROM python:3.11-slim

WORKDIR /app

# System deps: libpq for asyncpg, gcc for bcrypt build, curl for healthchecks
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc \
    libpq-dev \
    curl \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Playwright Chromium for brand scraping
RUN playwright install chromium --with-deps

COPY . .

EXPOSE 8000

# Default: API server. Override CMD in docker-compose for worker / beat.
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
