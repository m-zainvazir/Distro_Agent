# Final Backend Testing — Session Notes

## What Was Fixed This Session

| Bug | Root Cause | Fix Applied |
|-----|-----------|-------------|
| `TypeError: connect() got unexpected keyword argument 'sslmode'` | asyncpg doesn't accept `sslmode` — it uses `ssl=True` | `app/core/database.py`: strip `sslmode=` from URL, pass `connect_args={"ssl": True}` |
| `asyncpg InterfaceError: connection is closed` | Neon closes idle connections after ~5 min; pool held dead connections | Added `pool_pre_ping=True` and `pool_recycle=300` to the async engine |
| `can't subtract offset-naive and offset-aware datetimes` | KPI query compared tz-aware Python datetime against `TIMESTAMP WITHOUT TIME ZONE` DB column | `app/services/metrics_service.py`: `.replace(tzinfo=None)` on the lookback threshold |
| Brand extract → 500 | `upsert_brand_embedding` hard-crashed when Qdrant unreachable | `app/services/brand_service.py`: wrapped Qdrant upsert in `try/except`, logs warning only |

## Infrastructure

- **App**: Railway → `https://distroagent-production.up.railway.app`
- **Database**: Neon PostgreSQL (free tier, 0.5 GB)
  - Connection string in Railway env var `DATABASE_URL`
  - Format: `postgresql+asyncpg://neondb_owner:<pass>@ep-plain-shape-aoj7m3pa-pooler.c-2.ap-southeast-1.aws.neon.tech/neondb?sslmode=require`
- **Qdrant**: Not connected (Railway free plan limit) — embedding steps gracefully skipped
- **Redis**: Connected via Railway internal (`redis://...`)

---

## Complete Test Walkthrough

### 1. Open Swagger UI
Go to: `https://distroagent-production.up.railway.app/docs`

### 2. Create Account
- Find `POST /api/v1/auth/signup` → **Try it out**
- Body:
  ```json
  {"email": "you@example.com", "password": "YourPassword123", "brand_name": "YourBrand"}
  ```
- Copy the `access_token` from the response

### 3. Authorize All Requests
- Click the green **Authorize** button (top right of Swagger)
- Paste the token → click **Authorize** → **Close**

### 4. Login (verify data persisted in Neon)
- `POST /api/v1/auth/login`
- Body: `{"email": "you@example.com", "password": "YourPassword123"}`
- Same `tenant_id` returned = data is in Neon ✅

### 5. KPI Dashboard
- `GET /api/v1/metrics/kpis`
- Set `lookback_days` = `30` → Execute
- Returns zeros on a fresh account — confirms DB queries work ✅

### 6. Change Automation Level
- `PATCH /api/v1/tenant/autonomy-mode`
- Body:
  ```json
  {"autonomy_mode": "full_auto"}
  ```
- Options: `assist` | `semi_auto` | `full_auto`
- Returns your tenant ID + updated mode ✅

### 7. Extract a Brand Profile (AI runs here)
- `POST /api/v1/brands/extract`
- Body:
  ```json
  {"brand_url": "https://glossier.com", "vertical_tag": "beauty"}
  ```
- Other `vertical_tag` options: `fashion`, `wellness`, `home_goods`, `food_beverage`
- Returns: aesthetic keywords, tone, price range, target market, product categories ✅

### 8. Simulate a Buyer Reply (Negotiator Agent)
- `POST /api/v1/campaigns/simulate-reply`
- Body:
  ```json
  {
    "reply_text": "Your prices are too high for us",
    "sender_email": "buyer@boutique.com",
    "email_id": "email-002",
    "tenant_id": "<your-tenant-id-from-signup>"
  }
  ```
- Example intents the AI classifies:
  - `"not interested right now, maybe next quarter"` → `NOT_INTERESTED` / `mark_lead_lost`
  - `"prices are too high"` → `PRICE_OBJECTION` / counter-offer
  - `"send me more info"` → `INTERESTED` / escalate
- Returns: `intent`, `routing_action`, `notes` ✅

---

## If Neon Goes Temporarily Disabled (Free Tier Auto-Suspend)

Neon free tier suspends the compute after **5 minutes of zero database activity**. This is different from a lost connection — the entire DB compute pauses.

### What happens
- Railway app stays online, health checks pass
- First DB query after suspension gets a `connection refused` or `connection closed` error
- Neon auto-resumes in **~1–3 seconds** when a new connection arrives

### What to do

**Option A — Just retry the request (easiest)**
Wait 5 seconds and hit the endpoint again. Neon will have woken up by then.

**Option B — Hit the health check first to wake Neon**
Add a DB ping to `/health`. Currently `/health` doesn't touch the DB so it stays green even when Neon is suspended. To wake it proactively, call:
```
GET https://distroagent-production.up.railway.app/health
```
...then wait 3 seconds and make your real request. (This only works once we add a DB ping to the health endpoint — see below.)

**Option C — Add a DB-aware health endpoint (recommended long-term)**

In `app/api/health.py`, add a `SELECT 1` check:
```python
@router.get("/health/db")
async def db_health(db: AsyncSession = Depends(get_db)):
    await db.execute(text("SELECT 1"))
    return {"db": "ok"}
```
Then set up a Railway cron or UptimeRobot to ping `/health/db` every **4 minutes** — keeps Neon from ever suspending during business hours.

**Option D — Disable auto-suspend in Neon dashboard (free tier allows this)**
1. Go to `console.neon.tech`
2. Your project → **Settings** → **Compute**
3. Set **Suspend compute after** to `disabled` or max value
- Note: on free tier this uses your 191 compute hours/month faster, but for a low-traffic app it's fine

### Current mitigation already in place
`pool_pre_ping=True` in `database.py` handles **stale connections** (Neon suspended mid-session), but cannot handle the initial cold-start connection attempt when the compute is fully off. That first attempt needs a retry.

---

## What's NOT Yet Wired to API Routes

These services exist in the backend but have no HTTP endpoints yet:
- `GET /api/v1/leads/{lead_id}/budget` — per-lead token/cost tracking (Spec 303)
- `POST /api/v1/domains/provision` — auto domain provisioning (Spec 304)
- `POST /api/v1/campaigns/start` — currently a stub (accepts request, returns "queued", doesn't execute)

Next session: wire these service functions to actual routes so the full pipeline is testable end-to-end.
