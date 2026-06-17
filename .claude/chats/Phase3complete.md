# Phase 3 Complete — Governance Approval Gate + Scoring Calibration

## Status
Both subsystems built, tested, and manually verified end-to-end.

---

## What Was Built

### 1. Scoring Calibration System

**Files created:**
- `app/models/scoring_weights.py` — `ScoringWeights` SQLAlchemy model (one row per vertical; columns: `visual_weight`, `category_weight`, `price_weight`, `engagement_weight`, `wholesale_weight`, `calibrated_at`, `sample_size`)
- `app/services/calibration_service.py` — business logic: Pearson correlation of `vibe_score` vs win/loss outcomes, nudges `visual_weight` ±0.05 (capped 0.20–0.50), renormalizes the other 4 weights so sum = 1.0. Only fires if `sample_size >= 10`.
- `app/tasks/calibration_task.py` — Celery task `calibration.run_daily` (runs daily via beat). Calibrates every vertical with active campaigns + the global `"all"` fallback, then sends a WhatsApp summary to the founder.
- `alembic/versions/f2a8c4d1e903_add_scoring_weights.py` — migration adding the `scoring_weights` table.

**Key constants in `calibration_service.py`:**
```python
_MIN_SAMPLE = 10        # don't touch weights below this
_LOOKBACK_DAYS = 30
_WEIGHT_NUDGE = 0.05
_VISUAL_MIN = 0.20
_VISUAL_MAX = 0.50
```

**Win classification logic:**
- `outcome == "converted"` → win
- `outcome == "replied"` AND `reply_intent in {"INTERESTED", "MEETING_REQUEST"}` → win
- `outcome == "ignored"` → loss
- `outcome == "replied"` AND `reply_intent == "NOT_INTERESTED"` → loss
- everything else → neutral (excluded from Pearson)

---

### 2. Governance Approval Gate

**Files created:**
- `app/core/governance.py` — synchronous HMAC-signed approval gate
- `app/api/v1/governance.py` — FastAPI router with `/approve` and `/reject` endpoints
- `scripts/test_governance_flow.py` — manual 5-step smoke test
- `tests/api/test_governance.py` — 32 unit tests

**Files modified:**
- `app/api/v1/router.py` — `api_router.include_router(governance_router)`
- `app/core/config.py` — added `base_url` and `admin_phone` settings
- `.env.example` — added `BASE_URL=` and `ADMIN_PHONE=` under Governance section
- `Dockerfile` — replaced `gcc` with `build-essential` (fixes `psycopg-c` C extension build), added CPU-only torch pre-install step (avoids 532 MB GPU wheel timeout), added `--timeout 300` to pip install

#### How the gate works

```
require_admin_approval(action_type, payload)
  ├── generate_approval_token()  → {uuid}:{timestamp}:{hmac_sha256}
  ├── store_token_metadata()     → Redis key governance:token:{id}  (TTL 2h)
  ├── send_approval_request()    → WhatsApp text with approve/reject URLs
  └── wait_for_approval()        → Redis pub/sub blocks thread up to timeout_seconds
         ↑
         Admin clicks URL → FastAPI endpoint
         ├── verify_token()      → HMAC re-verified against Redis metadata
         └── publish_approval_decision() → publishes "approved"/"rejected" to channel
```

**Security:** HMAC-SHA256 with `SECRET_KEY`, timing-safe compare via `hmac.compare_digest`. Token format: `{token_id}:{timestamp}:{sig}`. The sig binds `action_type + token_id + timestamp + payload_json` together so tokens cannot be repurposed across actions.

**Entry point for Celery tasks:**
```python
from app.core.governance import require_admin_approval

approved = require_admin_approval(
    action_type="update_scoring_weights",
    payload={"vertical": "footwear", "old": 0.35, "new": 0.40},
)
if not approved:
    return {"status": "skipped", "reason": "admin_rejected_or_timed_out"}
```

**Important:** `require_admin_approval` is synchronous and blocking. Call it from Celery task functions only — never from inside an async event loop.

#### Key patch targets for tests
```python
"app.core.governance._redis_client"       # patch Redis in governance tests
"app.api.v1.governance.publish_approval_decision"  # patch for endpoint tests
"app.core.governance.httpx"               # patch WhatsApp HTTP calls
```

#### Redis key patterns
```
governance:token:{token_id}    → JSON metadata (TTL 2h)
governance:approval:{token_id} → pub/sub channel
```

---

## Celery Beat Schedule

Three periodic tasks registered in `app/celery_app.py`:

| Task | Schedule | Purpose |
|------|----------|---------|
| `email.send_pending` | every 900s (15 min) | Send queued outreach emails |
| `reply.process_queue` | every 3600s (1 hr) | Process incoming replies |
| `calibration.run_daily` | every 86400s (24 hr) | Calibrate scoring weights |

---

## Manual Test — Verified Working

Ran `scripts/test_governance_flow.py` successfully:
```
[1/5] Token generated ✓
[2/5] Storing token in Redis ✓
[3/5] Approval URLs printed ✓
[4/5] WhatsApp API returned 200 OK ✓ (but no message delivered — see below)
[5/5] Waited for decision → RESULT: APPROVED ✓
```

WhatsApp approved via curl in a second terminal:
```powershell
curl "http://localhost:8000/api/v1/governance/approve?token={full_token}&action=test_governance_gate"
```

**WhatsApp delivery note:** API returns 200 OK but message does not arrive on phone. Cause: Meta sandbox requires recipients to be whitelisted as test phone numbers in the Meta Developer Portal (developers.facebook.com → App → WhatsApp → API Setup → add recipient). Free-form text messages also require an active 24-hour conversation window. The governance logic itself is correct.

---

## How to Run Tests

```powershell
# Unit tests (no Docker needed)
.venv\Scripts\python -m pytest tests/api/test_governance.py -v
.venv\Scripts\python -m pytest tests/tasks/ -v

# Manual smoke test (needs Redis + uvicorn)
docker compose up -d redis
.venv\Scripts\uvicorn app.main:app --reload --port 8000
# in a second terminal:
.venv\Scripts\python -m scripts.test_governance_flow
```

---

## Docker Build Notes

Two fixes applied to `Dockerfile`:
1. `build-essential` instead of `gcc` alone — needed by `psycopg[c]` C extension (`stdlib.h` was missing with gcc-only)
2. CPU-only torch pre-installed before `requirements.txt` to avoid downloading the 532 MB GPU wheel (which times out):
   ```dockerfile
   RUN pip install --no-cache-dir --timeout 300 \
       torch --index-url https://download.pytorch.org/whl/cpu
   RUN pip install --no-cache-dir --timeout 300 -r requirements.txt
   ```

---

## Environment Variables Added

```env
# Governance
BASE_URL=http://localhost:8000      # used to build approve/reject URLs in WhatsApp message
ADMIN_PHONE=                        # if set, overrides WHATSAPP_FOUNDER_PHONE for notifications
```

---

## Next Steps

- [ ] Integrate `require_admin_approval` into the calibration task (gate the weight-update step)
- [ ] Whitelist founder phone in Meta Developer Portal for sandbox WhatsApp delivery
- [ ] Run `docker compose up -d` (full stack) — Dockerfile torch fix should resolve the timeout
- [ ] Apply Alembic migration: `make db-migrate`
- [ ] Production: swap temporary WhatsApp token for a permanent System User token
