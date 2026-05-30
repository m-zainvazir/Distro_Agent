"""
Validation tests for the FastAPI discovery endpoints.

Covers:
  1.  GET  /health                         — returns 200 + {"status": "ok"}
  2.  POST /api/v1/discovery/start         — returns 202 + task_id
  3.  POST /api/v1/discovery/start         — missing fields returns 422
  4.  GET  /api/v1/discovery/{id}/status   — PENDING → processing / 0
  5.  GET  /api/v1/discovery/{id}/status   — STARTED → processing / 10
  6.  GET  /api/v1/discovery/{id}/status   — PROGRESS (meta) → processing / custom %
  7.  GET  /api/v1/discovery/{id}/status   — SUCCESS → complete / 100
  8.  GET  /api/v1/discovery/{id}/status   — FAILURE → error / 0
  9.  GET  /api/v1/discovery/{id}/report   — SUCCESS with stores → 200 + HTML
  10. GET  /api/v1/discovery/{id}/report   — task still PENDING → 409
  11. GET  /api/v1/discovery/{id}/report   — task FAILURE → 500
  12. CORS — OPTIONS preflight returns Access-Control-Allow-Origin: *

Patch targets:
  - app.api.v1.endpoints.discovery.run_phase1_discovery   (Celery task)
  - app.api.v1.endpoints.discovery.AsyncResult            (Celery result)

Run:
  pytest app/tests/fastapi_test.py -v
"""
from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.models.store_candidate import DimensionScore, ScoredStore, StoreCandidate

# ---------------------------------------------------------------------------
# Patch targets
# ---------------------------------------------------------------------------

_TASK   = "app.api.v1.endpoints.discovery.run_phase1_discovery"
_RESULT = "app.api.v1.endpoints.discovery.AsyncResult"

# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------

client = TestClient(app)

_START_BODY = {
    "brand_url": "https://example.com",
    "vertical_tag": "beauty",
    "location": "Brooklyn, NY",
}


def _make_async_result(state: str, result: dict | None = None, info: dict | None = None) -> MagicMock:
    """Build a mock AsyncResult with the given Celery state."""
    mock = MagicMock()
    mock.state  = state
    mock.result = result or {}
    mock.info   = info or {}
    return mock


def _make_task_mock(task_id: str = "fake-task-uuid-1234") -> MagicMock:
    """Build a mock for run_phase1_discovery.delay()."""
    task = MagicMock()
    task.id = task_id
    mock_fn = MagicMock()
    mock_fn.delay.return_value = task
    return mock_fn


def _fake_scored_store_dict() -> dict:
    """Minimal serialised ScoredStore dict (as Celery would store it)."""
    dim = {"score": 8.0, "reasoning": "good", "data_used": []}
    store = {
        "place_id": "ChIJ001", "name": "Botanica", "address": "1 Main St",
        "city": "Brooklyn", "state": "NY", "google_categories": [],
        "website_url": None, "instagram_handle": None, "instagram_followers": None,
        "instagram_posts_last_30_days": None, "storefront_image_urls": [],
        "price_tier": None, "review_snippets": [], "is_chain": False,
    }
    return {
        "store": store,
        "visual_vibe_score": None,
        "category_score": dim, "price_score": dim,
        "engagement_score": dim, "wholesale_score": dim,
        "text_score": 8.0, "final_score": 8.0,
        "vision_was_run": False,
        "match_summary": "Good match.", "why_matched": "Strong categories.",
        "outreach_priority": "HIGH",
    }


# ---------------------------------------------------------------------------
# 1. Health check
# ---------------------------------------------------------------------------

def test_health_check():
    response = client.get("/health")
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ok"
    assert "langsmith" in body


# ---------------------------------------------------------------------------
# 2. POST /start — happy path returns 202 + task_id
# ---------------------------------------------------------------------------

def test_start_discovery_returns_202():
    mock_task = _make_task_mock("abc-123")

    with patch(_TASK, new=mock_task):
        response = client.post("/api/v1/discovery/start", json=_START_BODY)

    assert response.status_code == 202
    body = response.json()
    assert body["task_id"] == "abc-123"
    assert body["status"] == "processing"
    mock_task.delay.assert_called_once_with(
        brand_url="https://example.com",
        vertical_tag="beauty",
        location="Brooklyn, NY",
        tenant_id="default",
    )


# ---------------------------------------------------------------------------
# 3. POST /start — missing required fields returns 422
# ---------------------------------------------------------------------------

def test_start_discovery_missing_fields_returns_422():
    response = client.post("/api/v1/discovery/start", json={"brand_url": "https://example.com"})
    assert response.status_code == 422


# ---------------------------------------------------------------------------
# 4. Status — PENDING → processing / 0
# ---------------------------------------------------------------------------

def test_status_pending():
    with patch(_RESULT, return_value=_make_async_result("PENDING")):
        response = client.get("/api/v1/discovery/fake-id/status")

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "processing"
    assert body["progress"] == 0


# ---------------------------------------------------------------------------
# 5. Status — STARTED → processing / 10
# ---------------------------------------------------------------------------

def test_status_started():
    with patch(_RESULT, return_value=_make_async_result("STARTED")):
        response = client.get("/api/v1/discovery/fake-id/status")

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "processing"
    assert body["progress"] == 10


# ---------------------------------------------------------------------------
# 6. Status — PROGRESS with custom meta progress value
# ---------------------------------------------------------------------------

def test_status_progress_custom_meta():
    mock_result = _make_async_result("PROGRESS", info={"progress": 73, "step": "scoring"})

    with patch(_RESULT, return_value=mock_result):
        response = client.get("/api/v1/discovery/fake-id/status")

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "processing"
    assert body["progress"] == 73


# ---------------------------------------------------------------------------
# 7. Status — SUCCESS → complete / 100
# ---------------------------------------------------------------------------

def test_status_success():
    with patch(_RESULT, return_value=_make_async_result("SUCCESS")):
        response = client.get("/api/v1/discovery/fake-id/status")

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "complete"
    assert body["progress"] == 100


# ---------------------------------------------------------------------------
# 8. Status — FAILURE → error / 0
# ---------------------------------------------------------------------------

def test_status_failure():
    with patch(_RESULT, return_value=_make_async_result("FAILURE")):
        response = client.get("/api/v1/discovery/fake-id/status")

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "error"
    assert body["progress"] == 0


# ---------------------------------------------------------------------------
# 9. Report — SUCCESS with stores → 200 + HTML + stores list
# ---------------------------------------------------------------------------

def test_report_success_with_stores():
    payload = {
        "scored_stores": [_fake_scored_store_dict()],
        "report_url": "",          # empty → _build_report_html returns fallback
        "errors": [],
    }
    mock_result = _make_async_result("SUCCESS", result=payload)

    with patch(_RESULT, return_value=mock_result):
        response = client.get("/api/v1/discovery/fake-id/report")

    assert response.status_code == 200
    body = response.json()
    assert len(body["stores"]) == 1
    assert body["stores"][0]["store"]["name"] == "Botanica"
    assert body["stores"][0]["outreach_priority"] == "HIGH"
    assert isinstance(body["report_html"], str)
    assert len(body["report_html"]) > 0


# ---------------------------------------------------------------------------
# 10. Report — task still PENDING → 409
# ---------------------------------------------------------------------------

def test_report_task_not_complete_returns_409():
    with patch(_RESULT, return_value=_make_async_result("PENDING")):
        response = client.get("/api/v1/discovery/fake-id/report")

    assert response.status_code == 409
    assert "Poll /status" in response.json()["detail"]


# ---------------------------------------------------------------------------
# 11. Report — task FAILURE → 500
# ---------------------------------------------------------------------------

def test_report_task_failed_returns_500():
    with patch(_RESULT, return_value=_make_async_result("FAILURE")):
        response = client.get("/api/v1/discovery/fake-id/report")

    assert response.status_code == 500
    assert "failed" in response.json()["detail"]


# ---------------------------------------------------------------------------
# 12. CORS — preflight returns allow-all origin header
# ---------------------------------------------------------------------------

def test_cors_preflight():
    response = client.options(
        "/api/v1/discovery/start",
        headers={
            "Origin": "http://localhost:3000",
            "Access-Control-Request-Method": "POST",
        },
    )
    assert response.headers.get("access-control-allow-origin") == "*"
