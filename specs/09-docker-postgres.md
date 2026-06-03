# Spec: Docker Infrastructure — Postgres + Qdrant

## Overview
Stand up the two persistence services DistroAgent requires to run end-to-end:
- **PostgreSQL 15** — multi-tenant relational storage (tenants, brand profiles, store candidates, outreach campaigns)
- **Qdrant** — vector database for brand embedding storage and similarity search

Redis is already running. This spec covers only Postgres and Qdrant.

---

## Services

### PostgreSQL 15
| Setting | Value |
|---|---|
| Image | `postgres:15-alpine` |
| Port | `5432` |
| Database | `distroagent` |
| User | `postgres` |
| Password | from `POSTGRES_PASSWORD` env var |
| Volume | `postgres_data` (named volume, persisted across restarts) |

**Tables (from existing SQLAlchemy models):**
- `tenants` — one row per customer account
- `brand_profiles` — extracted brand intelligence, scoped by `tenant_id`
- `store_candidates` — discovered retail stores, scoped by `tenant_id`
- `outreach_campaigns` — campaign records, scoped by `tenant_id`
- `outreach_emails` — individual email records per campaign

All tables except `outreach_emails` inherit `TenantMixin` — every query must filter by `tenant_id`.

**Connection string (`.env`):**
```
DATABASE_URL=postgresql+asyncpg://postgres:postgres@localhost:5432/distroagent
```

### Qdrant
| Setting | Value |
|---|---|
| Image | `qdrant/qdrant` |
| HTTP port | `6333` |
| gRPC port | `6334` |
| Volume | `qdrant_data` (named volume, persisted across restarts) |

**Collections:**
- `brand_embeddings` — 384-dim vectors (sentence-transformers `all-MiniLM-L6-v2`)
  - Payload fields: `tenant_id`, `brand_url`, `brand_name`, `aesthetic_keywords`
  - Distance metric: `Cosine`
  - Used for: "find brands similar to this one" queries in Phase 2

**Connection string (`.env`):**
```
QDRANT_URL=http://localhost:6333
```

---

## Docker Compose

**File:** `docker-compose.yml` at project root.

```yaml
services:
  postgres:
    image: postgres:15-alpine
    environment:
      POSTGRES_DB: distroagent
      POSTGRES_USER: postgres
      POSTGRES_PASSWORD: postgres
    ports:
      - "5432:5432"
    volumes:
      - postgres_data:/var/lib/postgresql/data
    healthcheck:
      test: ["CMD-SHELL", "pg_isready -U postgres"]
      interval: 5s
      timeout: 5s
      retries: 5

  qdrant:
    image: qdrant/qdrant
    ports:
      - "6333:6333"
      - "6334:6334"
    volumes:
      - qdrant_data:/qdrant/storage

volumes:
  postgres_data:
  qdrant_data:
```

---

## Migrations

Alembic is already installed. Run after containers are up:
```bash
alembic upgrade head
```

Alembic config must be initialised first if `alembic/` directory does not exist:
```bash
alembic init -t async alembic
```
Then set `sqlalchemy.url` in `alembic.ini` to match `DATABASE_URL`.

---

## Startup Order

```
docker compose up -d          # start Postgres + Qdrant
alembic upgrade head          # apply schema migrations
uvicorn app.main:app --reload # start FastAPI (connects to both)
```

---

## Acceptance Criteria

- [ ] `docker compose up -d` starts both containers with no errors
- [ ] Postgres healthcheck passes: `docker compose ps` shows `healthy`
- [ ] `alembic upgrade head` creates all 5 tables with no errors
- [ ] FastAPI `/health` endpoint returns `200 {"status": "ok"}` with Postgres connected
- [ ] Qdrant UI reachable at `http://localhost:6333/dashboard`
- [ ] Brand extraction run writes a `BrandProfileRecord` row to Postgres (verify via psql or MCP)
- [ ] Embedding vector stored in Qdrant `brand_embeddings` collection after extraction
- [ ] Data persists after `docker compose restart` (volumes survive)
- [ ] All queries include `tenant_id` filter — no cross-tenant data leakage
