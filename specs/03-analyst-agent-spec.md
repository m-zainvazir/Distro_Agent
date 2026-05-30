markdown# Plan: Phase 1 — Analyst / Lead Scoring Agent

## Context
This agent receives a list of `StoreCandidate` objects from the Scout Agent and returns
a ranked list of `ScoredStore` objects. It implements a two-pass scoring architecture:
a cheap text-only pass first, then an expensive Claude vision pass only for stores that
clear the 8.0 threshold. This preserves an 85%+ gross margin at scale.

The agent depends on:
- `app/models/brand_profile.py` — `BrandProfile` (already built in Phase 1.1)
- `app/tools/google_maps.py` — store metadata (already built in Scout Agent)

---

## Scoring Algorithm
Total Score = Weighted Average of 5 dimensions (all scored 0.0–10.0)
┌─────────────────────────┬────────┬─────────────────────────────────────────┐
│ Dimension               │ Weight │ Data Source                             │
├─────────────────────────┼────────┼─────────────────────────────────────────┤
│ Visual Vibe Match       │  35%   │ Claude vision — storefront images        │
│ Category Alignment      │  25%   │ Google Maps categories + store website   │
│ Price Point Match       │  20%   │ Store price signals vs brand price_range │
│ Engagement Quality      │  10%   │ Instagram followers + posting frequency  │
│ Wholesale History       │  10%   │ Website signals, LinkedIn, review text   │
└─────────────────────────┴────────┴─────────────────────────────────────────┘
Two-Pass Cost Optimization:
Pass 1 (text-only):  Category + Price + Engagement + Wholesale  → text_score
Pass 2 (vision):     Visual Vibe Match                          → vision_score
if text_score < 8.0  → final_score = text_score (vision skipped)
if text_score >= 8.0 → run vision, then:
final_score = (vision_score × 0.35) + (text_score × 0.65)
This skips vision for ~80% of leads, cutting LLM costs by ~70%.

---

## Step 0 — New Files to Create

| File | Purpose |
|---|---|
| `app/models/store_candidate.py` | `StoreCandidate` + `ScoredStore` Pydantic models |
| `app/tools/category_scorer.py` | Category alignment scoring tool |
| `app/tools/price_scorer.py` | Price point match scoring tool |
| `app/tools/engagement_scorer.py` | Instagram engagement scoring tool |
| `app/tools/wholesale_scorer.py` | Wholesale history signal detection |
| `app/tools/vision_scorer.py` | Claude vision vibe match scoring tool |
| `app/agents/analyst_agent.py` | State + all nodes + compiled StateGraph |
| `app/services/analyst_service.py` | `score_stores()` service function |
| `app/api/v1/scoring.py` | POST /api/v1/scoring/score-batch endpoint |
| `tests/agents/test_analyst_agent.py` | All 8 tests |

---

## Step 1 — Pydantic Models

**File:** `app/models/store_candidate.py`

```python
class StoreCandidate(BaseModel):
    model_config = ConfigDict(frozen=True)

    place_id: str                        # Google Maps unique ID
    name: str
    address: str
    city: str
    state: str
    country: str = "US"
    google_categories: list[str]         # e.g. ["Gift Shop", "Boutique"]
    website_url: str | None
    instagram_handle: str | None
    instagram_followers: int | None
    instagram_posts_last_30_days: int | None
    storefront_image_urls: list[str]     # Google Street View or Instagram images
    price_tier: str | None               # "$" | "$$" | "$$$" | "$$$$" from Google
    review_snippets: list[str]           # top 3-5 Google review texts
    is_chain: bool = False               # True = Sephora, Ulta, etc → already filtered by Scout


class DimensionScore(BaseModel):
    score: float                         # 0.0–10.0
    reasoning: str                       # 1-2 sentence explanation
    data_used: list[str]                 # which fields drove this score


class ScoredStore(BaseModel):
    model_config = ConfigDict(frozen=True)

    store: StoreCandidate
    
    # Individual dimension scores
    visual_vibe_score: DimensionScore | None   # None if text_score < 8.0
    category_score: DimensionScore
    price_score: DimensionScore
    engagement_score: DimensionScore
    wholesale_score: DimensionScore

    # Computed totals
    text_score: float                    # weighted avg of 4 text dimensions (normalized to 10)
    final_score: float                   # with or without vision, 0.0–10.0
    vision_was_run: bool                 # True if vision pass executed
    
    # Explainability
    match_summary: str                   # 2-sentence human-readable summary
    why_matched: str                     # e.g. "Minimalist packaging aligns with their clean beauty curation"
    outreach_priority: str               # "HIGH" | "MEDIUM" | "LOW" based on final_score
```

Priority thresholds:
- `final_score >= 8.0` → `"HIGH"` (meeting candidate, vision always ran)
- `6.0 <= final_score < 8.0` → `"MEDIUM"` (standard outreach)
- `final_score < 6.0` → `"LOW"` (deprioritise, only contact if batch not full)

---

## Step 2 — Tool Functions

### `app/tools/category_scorer.py`

**Function:** `score_category_alignment(store: StoreCandidate, brand: BrandProfile) -> DimensionScore`

Logic (no LLM — pure rule-based + keyword match):
1. Build a set of `brand_keywords` from `brand.product_categories` + `brand.aesthetic_keywords`
2. Build a set of `store_keywords` from `store.google_categories` + `store.review_snippets` (lowercased)
3. Compute Jaccard-style overlap: `overlap = len(brand_keywords ∩ store_keywords)`
4. Score mapping:
   - `overlap >= 5` → 9.0–10.0
   - `overlap 3–4` → 7.0–8.9
   - `overlap 1–2` → 4.0–6.9
   - `overlap 0` → 1.0–3.9
5. Return `DimensionScore` with reasoning citing which keywords matched

**No external API calls. Must complete in < 50ms per store.**

---

### `app/tools/price_scorer.py`

**Function:** `score_price_alignment(store: StoreCandidate, brand: BrandProfile) -> DimensionScore`

Logic:
1. Map `store.price_tier` to an estimated USD retail range:
   - `"$"` → (5, 30)
   - `"$$"` → (25, 80)
   - `"$$$"` → (70, 200)
   - `"$$$$"` → (180, 600)
   - `None` → use mid-range default (25, 80), flag as low-confidence
2. Compare against `brand.price_range` (min, max):
   - Full overlap → 9.5
   - Partial overlap (≥ 50%) → 7.0–8.5
   - Adjacent tier (store is 1 tier above/below) → 5.0–6.5
   - No overlap → 2.0–3.5
3. Reasoning must state: "Brand sells $X–$Y; store carries $A–$B products"

**No external API calls.**

---

### `app/tools/engagement_scorer.py`

**Function:** `score_engagement(store: StoreCandidate) -> DimensionScore`

Logic:
1. If `instagram_followers` is None → score = 4.0, reasoning = "No Instagram data available"
2. Follower score (60% weight within this dimension):
   - `>= 10,000` → 10.0
   - `5,000–9,999` → 8.0
   - `1,000–4,999` → 6.0
   - `500–999` → 4.0
   - `< 500` → 2.0
3. Activity score (40% weight): `posts_last_30_days`
   - `>= 12` (≥3/week) → 10.0
   - `8–11` → 7.5
   - `4–7` → 5.0
   - `1–3` → 3.0
   - `0` or None → 1.0
4. `score = (follower_score × 0.6) + (activity_score × 0.4)`

**No external API calls.**

---

### `app/tools/wholesale_scorer.py`

**Function:** `score_wholesale_signals(store: StoreCandidate) -> DimensionScore`

Logic — keyword detection across `review_snippets` + `website_url` content (fetched with httpx, timeout=5s):

Signal keywords (each hit adds points):
```python
STRONG_SIGNALS = ["wholesale", "wholesale inquiry", "carry our brand", "stockist",
                  "buy wholesale", "minimum order", "trade account"]        # +2.5 each, max 10
MEDIUM_SIGNALS = ["curated", "independent brands", "small batch", "locally sourced",
                  "handmade", "artisan", "boutique brands"]                 # +1.5 each, max 7
WEAK_SIGNALS   = ["new arrivals", "exclusive", "limited edition"]           # +0.5 each, max 4
```

Score = min(sum of all signal points, 10.0)

If website fetch fails → score from review_snippets only, note in reasoning.

**May make 1 HTTP call (website_url). Timeout: 5 seconds. Failure is non-blocking.**

---

### `app/tools/vision_scorer.py`

**Function:** `async score_visual_vibe(store: StoreCandidate, brand: BrandProfile) -> DimensionScore`

This is the EXPENSIVE tool — only called when `text_score >= 8.0`.

Steps:
1. Download up to 3 `store.storefront_image_urls` as base64 (reuse `image_downloader.py`)
2. If no images available → return `DimensionScore(score=5.0, reasoning="No storefront images available — defaulted to neutral score", data_used=[])`
3. Build a structured prompt:
You are a wholesale distribution analyst. Your job is to assess whether this retail
store's aesthetic is a strong match for a specific brand.
BRAND PROFILE:

Aesthetic keywords: {brand.aesthetic_keywords}
Brand voice: {brand.brand_voice_description}
Primary colors: {brand.primary_colors}

Examine the attached store images and respond with a JSON object ONLY:
{
"vibe_score": <float 0.0-10.0>,
"reasoning": "<1-2 sentences on why the score was given>",
"matching_signals": ["<list of specific visual elements that matched>"],
"mismatching_signals": ["<list of specific visual elements that clashed>"]
}
Scoring guide:
9.0–10.0 = Perfect aesthetic match, brand would look native on their shelves
7.0–8.9  = Strong match, minor aesthetic differences
5.0–6.9  = Moderate match, some alignment
3.0–4.9  = Weak match, aesthetic clash likely
0.0–2.9  = No match, brand would look out of place

4. Parse JSON response. If malformed → score = 5.0, log warning.
5. Log token usage: `{"input_tokens": int, "output_tokens": int, "model": settings.CLAUDE_MODEL}`

**Uses Claude vision. Budget: max 3 images per store. Estimated cost: $0.015–$0.04 per store.**

---

## Step 3 — LangGraph Agent State

**File:** `app/agents/analyst_agent.py`

```python
class AnalystState(TypedDict):
    # Inputs
    brand_profile: BrandProfile
    store_candidates: list[StoreCandidate]
    
    # Processing
    current_index: int                         # which store we are scoring
    scores_in_progress: list[ScoredStore]      # accumulator
    
    # Cost tracking
    vision_calls_made: int
    total_token_usage: dict[str, int]          # {"input": N, "output": N}
    total_cost_usd: float
    
    # Outputs
    scored_stores: list[ScoredStore]           # sorted by final_score desc
    errors: list[str]
```

---

## Step 4 — LangGraph Node Functions

All nodes are `async` functions: `(state: AnalystState) -> dict`

| Node | Responsibility |
|---|---|
| `validate_inputs_node` | Check `brand_profile` is not None, `store_candidates` is non-empty. Set error if not. |
| `score_text_dimensions_node` | For each store: run category + price + engagement + wholesale scorers. Compute `text_score` = weighted avg of those 4 (normalised to 10). Store intermediate results. |
| `route_vision_node` | Router only. For each store with `text_score >= 8.0`, flag for vision. Return routing decision. |
| `score_vision_node` | For flagged stores: call `score_visual_vibe()`. Accumulate token usage + cost. |
| `compute_final_scores_node` | Merge text + vision scores per store. Compute `final_score`. Assign `outreach_priority`. Generate `match_summary` and `why_matched` using a lightweight Claude call (text-only, cheap). |
| `sort_and_package_node` | Sort `scored_stores` by `final_score` descending. Verify no store has missing required fields. Set final state. |
| `error_node` | Log errors. Return whatever partial scores exist. Never crash the pipeline. |

**`compute_final_scores_node` Claude call — match summary generation:**

Use `claude-haiku` (cheapest model) for this, not Sonnet. Prompt:
Given this scoring data for a retail store, write:

match_summary: 2-sentence summary of why this store is or isn't a match
why_matched: 1 specific sentence citing the strongest alignment signal

Store: {store.name}, {store.city}
Category score: {category_score.score}/10 — {category_score.reasoning}
Price score: {price_score.score}/10 — {price_score.reasoning}
Engagement score: {engagement_score.score}/10
Wholesale score: {wholesale_score.score}/10
Visual score: {visual_vibe_score.score}/10 (if available)
Respond in JSON: {"match_summary": "...", "why_matched": "..."}

---

## Step 5 — StateGraph Definition
START
└─→ validate_inputs_node
├─ [error] ──→ error_node ──→ END
└─ [OK] ──→ score_text_dimensions_node
└─→ route_vision_node
├─ [any stores with text_score >= 8.0] ──→ score_vision_node
│                                                └─→ compute_final_scores_node
└─ [all stores text_score < 8.0] ─────────────→ compute_final_scores_node
└─→ sort_and_package_node
└─→ END

Conditional edge logic:
```python
def route_after_text_scoring(state: AnalystState) -> str:
    vision_candidates = [
        s for s in state["scores_in_progress"]
        if s.text_score >= settings.VISION_SCORE_THRESHOLD  # default 8.0
    ]
    return "score_vision_node" if vision_candidates else "compute_final_scores_node"
```

Compile with `checkpointer=None`. Add LangSmith `@traceable` on the graph invocation wrapper.

---

## Step 6 — Service Layer

**File:** `app/services/analyst_service.py`

```python
async def score_stores(
    brand_profile: BrandProfile,
    store_candidates: list[StoreCandidate],
    max_stores: int = 50,
) -> list[ScoredStore]:
```

- Caps input at `max_stores` to control cost
- Initialises `AnalystState` with inputs
- Invokes compiled graph: `await graph.ainvoke(initial_state)`
- Logs summary: `f"Scored {len(results)} stores. Vision ran on {vision_count}. Total cost: ${total_cost:.4f}"`
- Returns `state["scored_stores"]` (already sorted by `final_score` desc)
- Raises `ValueError` if `state["errors"]` is non-empty and `scored_stores` is also empty

---

## Step 7 — API Endpoint

**File:** `app/api/v1/scoring.py`
POST /api/v1/scoring/score-batch
Body: {
"brand_profile": BrandProfile,
"store_candidates": list[StoreCandidate],
"max_stores": int  (optional, default 50, max 100)
}
Response 200: {
"scored_stores": list[ScoredStore],
"vision_ran_on": int,
"total_cost_usd": float,
"high_priority_count": int,
"medium_priority_count": int
}
Response 400: validation or scoring error

Register in `app/main.py` under prefix `/api/v1`.

---

## Step 8 — Register Agent

**File:** `app/workflows/registry.py`

Add to `AGENT_REGISTRY`:
```python
"analyst": analyst_agent_graph,
```

---

## Step 9 — Tests

**File:** `tests/agents/test_analyst_agent.py`

| Test | What it verifies |
|---|---|
| `test_full_pipeline_high_scorer` | Store with strong category + price + engagement match gets `final_score >= 8.0`, vision is triggered, `outreach_priority == "HIGH"` |
| `test_text_only_path_low_scorer` | Store with `text_score < 8.0` does NOT trigger vision. `vision_was_run == False`. |
| `test_scoring_threshold_boundary` | Store with `text_score == 7.99` skips vision. Store with `text_score == 8.0` triggers it. |
| `test_no_instagram_data` | `instagram_followers = None` → engagement score = 4.0, pipeline completes without error |
| `test_no_storefront_images` | Vision triggered but no images → score defaults to 5.0, `data_used == []` |
| `test_website_fetch_failure` | `wholesale_scorer` httpx timeout → pipeline continues, score from review snippets only |
| `test_sorted_output_order` | Final list is sorted by `final_score` descending (highest first) |
| `test_cost_tracking` | `total_cost_usd > 0` after vision runs. `vision_calls_made` matches number of HIGH stores. |

Use `pytest-asyncio` for all tests.
Mock `anthropic.AsyncAnthropic` with `pytest-mock`.
Mock `httpx.AsyncClient` with `respx` for website fetches.
Mock `score_visual_vibe` with a fixture that returns a fixed `DimensionScore`.

---

## Dependencies (additions to existing requirements.txt)

No new packages needed. All tools use:
- `anthropic` — already installed (vision scoring)
- `httpx` — already installed (wholesale website fetch)
- `langsmith` — already installed (tracing)

---

## Cost Budget Reference

| Scenario | Vision Calls | Estimated Cost / 50 stores |
|---|---|---|
| All stores text_score < 8.0 | 0 | ~$0.002 (text LLM only) |
| 20% stores clear threshold | 10 | ~$0.45 |
| 50% stores clear threshold | 25 | ~$1.10 |
| All stores clear threshold | 50 | ~$2.20 |

Target: keep average campaign cost under $0.50 for 50 stores by tuning quality of Scout output.

---

## Verification

1. `make lint` — ruff + mypy pass with zero errors
2. `make test` — all 8 tests pass
3. Manual integration test: pass 10 `StoreCandidate` fixtures through the service, confirm:
   - Output is sorted by `final_score` descending
   - Stores with `text_score < 8.0` have `vision_was_run == False`
   - All `ScoredStore` objects have `match_summary` and `why_matched` populated
   - `total_cost_usd` is non-zero and logged
4. POST to `http://localhost:8000/api/v1/scoring/score-batch` with 5 stores, confirm JSON matches `ScoredStore` schema

---

## Implementation Checklist

### Step 0 — New Files
- [ ] `app/models/store_candidate.py` — `StoreCandidate`, `DimensionScore`, `ScoredStore` models created
- [ ] All new tool files created (empty, ready to fill)
- [ ] `app/agents/analyst_agent.py` file created (empty)
- [ ] `app/services/analyst_service.py` file created (empty)
- [ ] `app/api/v1/scoring.py` file created (empty)
- [ ] `tests/agents/test_analyst_agent.py` file created (empty)

### Step 1 — Models
- [ ] `StoreCandidate` has all 12 fields with correct types
- [ ] `DimensionScore` has score, reasoning, data_used
- [ ] `ScoredStore` has all dimension scores + text_score + final_score + priority fields
- [ ] Priority threshold constants defined (8.0 = HIGH, 6.0 = MEDIUM)
- [ ] `model_config = ConfigDict(frozen=True)` on all models

### Step 2 — Tool Functions
- [ ] `score_category_alignment()` — pure keyword logic, no API calls, < 50ms
- [ ] `score_price_alignment()` — price tier mapping complete, all 4 tiers handled
- [ ] `score_engagement()` — handles None instagram data gracefully
- [ ] `score_wholesale_signals()` — httpx fetch with 5s timeout, non-blocking on failure
- [ ] `score_visual_vibe()` — Claude vision call with structured JSON prompt, token usage logged
- [ ] Vision tool returns default DimensionScore(5.0) when no images available

### Step 3-4 — Agent State + Nodes
- [ ] `AnalystState` TypedDict defined with all fields
- [ ] `validate_inputs_node` — blocks on empty store list
- [ ] `score_text_dimensions_node` — runs all 4 text scorers, computes text_score
- [ ] `route_vision_node` — correctly identifies stores >= 8.0 threshold
- [ ] `score_vision_node` — only runs on flagged stores, accumulates token usage
- [ ] `compute_final_scores_node` — merges scores, calls Haiku for match_summary
- [ ] `sort_and_package_node` — sorted desc, no missing fields
- [ ] `error_node` — handles partial results, never crashes

### Step 5 — StateGraph
- [ ] Conditional edge `route_after_text_scoring` implemented correctly
- [ ] Both paths (vision / no-vision) reach `compute_final_scores_node`
- [ ] Graph compiles without errors
- [ ] LangSmith `@traceable` added on invocation wrapper

### Step 6 — Service Layer
- [ ] `score_stores()` caps input at `max_stores`
- [ ] Summary log line printed at INFO level
- [ ] Returns sorted `ScoredStore` list
- [ ] Raises `ValueError` only when both errors AND empty results

### Step 7-8 — API + Registry
- [ ] POST `/api/v1/scoring/score-batch` endpoint works
- [ ] Response includes `vision_ran_on` count and `total_cost_usd`
- [ ] Router registered in `app/main.py`
- [ ] `"analyst"` added to `AGENT_REGISTRY`

### Step 9 — Tests
- [ ] `test_full_pipeline_high_scorer` passes
- [ ] `test_text_only_path_low_scorer` passes
- [ ] `test_scoring_threshold_boundary` passes
- [ ] `test_no_instagram_data` passes
- [ ] `test_no_storefront_images` passes
- [ ] `test_website_fetch_failure` passes
- [ ] `test_sorted_output_order` passes
- [ ] `test_cost_tracking` passes

### Final Verification
- [ ] `make lint` — zero errors
- [ ] `make test` — all 8 tests green
- [ ] 10-store manual test — sorted output, vision_was_run correct, cost logged
- [ ] POST to localhost:8000 returns valid JSON matching ScoredStore schema