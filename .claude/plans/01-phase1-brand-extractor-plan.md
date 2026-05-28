# Plan: Phase 1 — Brand Intelligence Extractor

## Context
This is a greenfield implementation. No `app/`, `tests/`, or dependency files exist yet.
The goal is to build a LangGraph agent that accepts a Shopify or Etsy URL and returns a
structured `BrandProfile` within 60 seconds — including product catalog extraction, image
aesthetic analysis via Claude vision, and an OpenAI embedding for downstream similarity search.

---

## Step 0 — Project Scaffolding

Create the base directory structure and shared infrastructure before any agent code.

### Files to create

| File | Purpose |
|---|---|
| `app/__init__.py` | Package root |
| `app/core/__init__.py` | |
| `app/core/config.py` | Pydantic `Settings` class reading from `.env` |
| `app/core/logging.py` | Structured logger (structlog or standard logging) |
| `app/core/errors.py` | `BrandExtractionError`, `UnsupportedPlatformError` |
| `app/core/database.py` | Async SQLAlchemy engine + session factory |
| `app/agents/__init__.py` | |
| `app/tools/__init__.py` | |
| `app/services/__init__.py` | |
| `app/models/__init__.py` | |
| `app/workflows/__init__.py` | |
| `app/workflows/registry.py` | Agent registry dict |
| `app/api/__init__.py` | |
| `app/api/v1/__init__.py` | |
| `tests/__init__.py` | |
| `tests/agents/__init__.py` | |
| `requirements.txt` | All dependencies |
| `.env.example` | Template for required env vars |
| `Makefile` | `dev`, `test`, `lint`, `db-migrate`, `agent-test` targets |

### Key env vars (`.env.example`)
```
ANTHROPIC_API_KEY=
OPENAI_API_KEY=
DATABASE_URL=postgresql+asyncpg://...
REDIS_URL=redis://localhost:6379
QDRANT_URL=http://localhost:6333
CLAUDE_MODEL=claude-sonnet-4-20250514
LANGSMITH_API_KEY=
LANGSMITH_PROJECT=distroagent
```

### `app/core/config.py` shape
```python
class Settings(BaseSettings):
    anthropic_api_key: str
    openai_api_key: str
    claude_model: str = "claude-sonnet-4-20250514"
    database_url: str
    ...
settings = Settings()
```

---

## Step 1 — Pydantic Output Model

**File:** `app/models/brand_profile.py`

Define the `BrandProfile` Pydantic v2 model exactly matching the spec:

```
BrandProfile:
  brand_name: str
  tagline: str
  primary_colors: list[str]          # hex codes
  aesthetic_keywords: list[str]
  product_categories: list[str]
  price_range: tuple[float, float]   # (min_usd, max_usd)
  brand_voice_description: str
  wholesale_readiness_score: float   # 0-10
  raw_product_images: list[str]      # image URLs
  embedding_vector: list[float]      # 1536-dim
```

Use `model_config = ConfigDict(frozen=True)` — profiles are immutable value objects.

---

## Step 2 — Custom Errors

**File:** `app/core/errors.py`

```
BrandExtractionError(message: str, retry_suggestion: str)
UnsupportedPlatformError(url: str, supported: list[str])
```

---

## Step 3 — LangGraph Agent State

**File:** `app/agents/brand_extractor.py`

### State TypedDict

```python
class BrandExtractorState(TypedDict):
    # Inputs
    brand_url: str
    vertical_tag: str
    # Derived
    platform: str               # "shopify" | "etsy"
    raw_catalog: list[dict]     # raw product dicts from platform API
    about_text: str
    image_urls: list[str]       # candidate image URLs (pre-download)
    downloaded_images: list[str]  # base64 or local paths of downloaded images
    # Outputs
    brand_profile: BrandProfile | None
    token_usage: dict[str, int]
    error: str | None
```

---

## Step 4 — Tool Functions

### `app/tools/platform_detector.py`
- `detect_platform(url: str) -> str` — returns `"shopify"` or `"etsy"`, raises `UnsupportedPlatformError` otherwise
- Shopify: domain contains `myshopify.com` OR site responds to `/products.json`
- Etsy: domain contains `etsy.com/shop/`

### `app/tools/catalog_fetcher.py`
- `fetch_shopify_catalog(url: str) -> tuple[list[dict], str]` — hits `{url}/products.json`, also fetches `/pages/about` for about text
- `fetch_etsy_catalog(url: str) -> tuple[list[dict], str]` — scrapes Etsy shop listing page with httpx + BeautifulSoup
- Returns `(products, about_text)`
- On HTTP error → raise `BrandExtractionError` with retry suggestion

### `app/tools/image_downloader.py`
- `download_images(image_urls: list[str], max_images: int = 5) -> list[str]` — downloads up to 5 images as base64 strings
- On failure → logs warning, returns whatever downloaded (partial OK per spec)

### `app/tools/vision_analyzer.py`
- `analyze_brand_aesthetics(images: list[str], about_text: str, products: list[dict], vertical_tag: str) -> dict`
- Sends images + structured prompt to `settings.CLAUDE_MODEL` (Claude vision)
- Prompt instructs Claude to return JSON with: `brand_name`, `tagline`, `primary_colors`, `aesthetic_keywords`, `brand_voice_description`, `wholesale_readiness_score`
- Logs token usage via the app logger

### `app/tools/embedding_generator.py`
- `generate_brand_embedding(brand_profile_text: str) -> list[float]`
- Uses OpenAI `text-embedding-3-small` → returns 1536-dim vector

---

## Step 5 — LangGraph Node Functions

All nodes are `async` functions with signature `(state: BrandExtractorState) -> dict`.

| Node | Responsibility |
|---|---|
| `detect_platform_node` | Call `detect_platform()`, set `state["platform"]` |
| `fetch_catalog_node` | Dispatch to Shopify or Etsy fetcher, set `raw_catalog` + `about_text` + `image_urls` |
| `download_images_node` | Call `download_images()`, set `downloaded_images` |
| `analyze_aesthetics_node` | Call `analyze_brand_aesthetics()`, collect partial brand fields + token usage |
| `generate_embedding_node` | Call `generate_brand_embedding()`, set `embedding_vector` |
| `build_profile_node` | Assemble `BrandProfile` from all state fields, set `brand_profile` |
| `error_node` | Log error, set `brand_profile = None` with best partial data |

---

## Step 6 — StateGraph Definition

```
detect_platform_node
    ├─ [UnsupportedPlatformError] ──→ error_node ──→ END
    └─ [OK] ──→ fetch_catalog_node
                    ├─ [no products] ──→ build_profile_node (partial) ──→ END
                    └─ [OK] ──→ download_images_node
                                    └─ analyze_aesthetics_node
                                            └─ generate_embedding_node
                                                    └─ build_profile_node ──→ END
```

Conditional edges use a router function that inspects `state["error"]` and `state["raw_catalog"]`.

Compile with `checkpointer=None` for now (stateless per-request execution).
Add `@traceable` (LangSmith) decorator on the compiled graph invocation wrapper.

**File:** `app/agents/brand_extractor.py` (single file containing State + all nodes + graph)

---

## Step 7 — Service Layer

**File:** `app/services/brand_service.py`

```python
async def extract_brand(brand_url: str, vertical_tag: str) -> BrandProfile:
    ...
```

- Initialises `BrandExtractorState` with inputs
- Invokes the compiled graph: `await graph.ainvoke(initial_state)`
- Returns `state["brand_profile"]` or re-raises the error from `state["error"]`
- Logs total token usage at INFO level

---

## Step 8 — API Endpoint

**File:** `app/api/v1/brands.py`

```
POST /api/v1/brands/extract
Body: { "brand_url": str, "vertical_tag": str }
Response 200: BrandProfile JSON
Response 422: validation error
Response 400: BrandExtractionError / UnsupportedPlatformError (with error code)
```

Register router in `app/main.py` under prefix `/api/v1`.

---

## Step 9 — Register Agent

**File:** `app/workflows/registry.py`

```python
AGENT_REGISTRY: dict[str, CompiledGraph] = {
    "brand_extractor": brand_extractor_graph,
}
```

---

## Step 10 — Tests

**File:** `tests/agents/test_brand_extractor.py`

| Test | Description |
|---|---|
| `test_shopify_happy_path` | Mock httpx + Claude + OpenAI; assert BrandProfile fields populated |
| `test_etsy_happy_path` | Same for Etsy URL |
| `test_invalid_url_raises` | Non-Shopify/Etsy URL → `UnsupportedPlatformError` |
| `test_unreachable_url_raises` | httpx timeout → `BrandExtractionError` with retry suggestion |
| `test_no_products_partial_profile` | Empty catalog → profile returned with `wholesale_readiness_score` low |
| `test_image_failure_text_only` | Image download fails → analysis proceeds with text only |
| `test_token_usage_logged` | Assert token usage dict is non-empty after extraction |

Use `pytest-asyncio` for all async tests. Mock external HTTP calls with `respx` (httpx mock library).

---

## Dependencies (`requirements.txt`)

```
langgraph>=0.2
langsmith
anthropic>=0.30
openai>=1.40
httpx
beautifulsoup4
fastapi
uvicorn[standard]
sqlalchemy[asyncio]
asyncpg
alembic
pydantic>=2.0
pydantic-settings
redis
structlog
pytest
pytest-asyncio
respx
mypy
ruff
```

---

## Verification

1. `make lint` — ruff + mypy pass with zero errors
2. `make test` — all 7 tests pass
3. `make agent-test` — invoke against a known Shopify store (e.g., `gymshark.com`) and verify:
   - `brand_name` is populated
   - `product_categories` is non-empty
   - `price_range` has valid min < max floats
   - `embedding_vector` has length 1536
   - Completion time < 30 seconds
4. `make agent-test` — invoke against a real Etsy shop URL, same checks
5. Manual: POST to `http://localhost:8000/api/v1/brands/extract` and confirm JSON response matches `BrandProfile` schema
