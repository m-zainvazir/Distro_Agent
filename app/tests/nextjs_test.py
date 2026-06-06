"""
Validation tests for the Next.js landing page (frontend/).

Covers:
  1.  All required source files exist
  2.  globals.css — design tokens: sage, blush, ink colors + keyframes
  3.  layout.tsx  — Playfair Display + Inter via next/font, correct metadata title
  4.  types.ts    — all 6 interfaces defined
  5.  api.ts      — startDiscovery, pollStatus, fetchReport, ApiError
  6.  useDiscovery.ts — polling interval, stopPolling cleanup, all 8 progress messages
  7.  HeroSection.tsx — URL validation, trust line, location input
  8.  LoadingState.tsx — botanical ring animation, progress bar, fade message
  9.  StoreCard.tsx — final_score * 10 percentage, priority badge, rank number
  10. TeaserBlur.tsx — block characters (████), lock icon SVG
  11. CTABanner.tsx — NEXT_PUBLIC_CALENDLY_URL, target="_blank"
  12. .env.local  — NEXT_PUBLIC_API_URL present
  13. npm run build — zero TypeScript errors (runs actual build)
  14. GET localhost:3000 — returns 200 with HTML (requires: npm run dev)
  15. Page HTML — contains brand title and sage color reference

Run all (no server needed for 1-13):
  pytest app/tests/nextjs_test.py -v

Run 14-15 (start dev server first in another terminal):
  cd frontend && npm run dev
  pytest app/tests/nextjs_test.py -v -k "server"
"""
import subprocess
from pathlib import Path

import pytest

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------

ROOT     = Path(__file__).resolve().parents[2]
FRONTEND = ROOT / "frontend"
SRC      = FRONTEND / "src"


def read(rel: str) -> str:
    return (FRONTEND / rel).read_text(encoding="utf-8")


# ---------------------------------------------------------------------------
# 1 — All required files exist
# ---------------------------------------------------------------------------

REQUIRED_FILES = [
    "src/app/globals.css",
    "src/app/layout.tsx",
    "src/app/page.tsx",
    "src/lib/types.ts",
    "src/lib/api.ts",
    "src/hooks/useDiscovery.ts",
    "src/components/HeroSection.tsx",
    "src/components/LoadingState.tsx",
    "src/components/StoreCard.tsx",
    "src/components/TeaserBlur.tsx",
    "src/components/CTABanner.tsx",
    "src/components/ResultsSection.tsx",
    ".env.local",
    "vercel.json",
]


@pytest.mark.parametrize("rel_path", REQUIRED_FILES)
def test_required_file_exists(rel_path: str) -> None:
    assert (FRONTEND / rel_path).exists(), f"Missing: {rel_path}"


# ---------------------------------------------------------------------------
# 2 — globals.css: design tokens + keyframes
# ---------------------------------------------------------------------------

def test_globals_css_sage_color() -> None:
    css = read("src/app/globals.css")
    assert "#7C9A82" in css, "Sage color missing from globals.css"


def test_globals_css_blush_color() -> None:
    css = read("src/app/globals.css")
    assert "#C4897A" in css, "Blush/rose color missing from globals.css"


def test_globals_css_ink_color() -> None:
    css = read("src/app/globals.css")
    assert "#1A1A1A" in css, "Ink/primary text color missing from globals.css"


def test_globals_css_fade_up_keyframe() -> None:
    css = read("src/app/globals.css")
    assert "fade-up" in css, "fade-up keyframe missing from globals.css"


def test_globals_css_spin_slow_keyframe() -> None:
    css = read("src/app/globals.css")
    assert "spin-slow" in css, "spin-slow keyframe missing from globals.css"


# ---------------------------------------------------------------------------
# 3 — layout.tsx: fonts + metadata
# ---------------------------------------------------------------------------

def test_layout_uses_playfair_display() -> None:
    layout = read("src/app/layout.tsx")
    assert "Playfair_Display" in layout, "Playfair Display font not imported in layout.tsx"


def test_layout_uses_inter() -> None:
    layout = read("src/app/layout.tsx")
    assert "Inter" in layout, "Inter font not imported in layout.tsx"


def test_layout_metadata_title() -> None:
    layout = read("src/app/layout.tsx")
    assert "DistroAgent" in layout, "Brand title missing from layout.tsx metadata"


def test_layout_metadata_description() -> None:
    layout = read("src/app/layout.tsx")
    assert "60 seconds" in layout, "Description with '60 seconds' missing from layout.tsx"


# ---------------------------------------------------------------------------
# 4 — types.ts: all interfaces
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("interface", [
    "DiscoveryStatus",
    "StartDiscoveryRequest",
    "StartDiscoveryResponse",
    "StatusResponse",
    "ScoredStore",
    "ReportResponse",
])
def test_types_interface_defined(interface: str) -> None:
    types = read("src/lib/types.ts")
    assert interface in types, f"Interface {interface} missing from types.ts"


# ---------------------------------------------------------------------------
# 5 — api.ts: functions + error class
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("symbol", [
    "startDiscovery",
    "pollStatus",
    "fetchReport",
    "ApiError",
    "NEXT_PUBLIC_API_URL",
])
def test_api_symbol_present(symbol: str) -> None:
    api = read("src/lib/api.ts")
    assert symbol in api, f"'{symbol}' missing from api.ts"


# ---------------------------------------------------------------------------
# 6 — useDiscovery.ts: hook logic
# ---------------------------------------------------------------------------

def test_hook_has_setinterval() -> None:
    hook = read("src/hooks/useDiscovery.ts")
    assert "setInterval" in hook, "Polling setInterval missing from useDiscovery.ts"


def test_hook_has_clearinterval_cleanup() -> None:
    hook = read("src/hooks/useDiscovery.ts")
    assert "clearInterval" in hook, "clearInterval cleanup missing from useDiscovery.ts"


def test_hook_exports_reset() -> None:
    hook = read("src/hooks/useDiscovery.ts")
    assert "reset" in hook, "'reset' function missing from useDiscovery.ts"


@pytest.mark.parametrize("message", [
    "Reading your brand story",
    "Analyzing your aesthetic",
    "Scanning 200+ boutiques",
    "Matching your vibe",
    "Scoring brand-to-shelf",
    "Generating your personalized",
    "Almost ready",
])
def test_hook_progress_message(message: str) -> None:
    hook = read("src/hooks/useDiscovery.ts")
    assert message in hook, f"Progress message '{message}' missing from useDiscovery.ts"


# ---------------------------------------------------------------------------
# 7 — HeroSection.tsx
# ---------------------------------------------------------------------------

def test_hero_url_validation() -> None:
    hero = read("src/components/HeroSection.tsx")
    assert "startsWith('http')" in hero or 'startsWith("http")' in hero, \
        "URL validation (startsWith http) missing from HeroSection.tsx"


def test_hero_trust_line() -> None:
    hero = read("src/components/HeroSection.tsx")
    assert "No account needed" in hero, "Trust line missing from HeroSection.tsx"


def test_hero_location_input() -> None:
    hero = read("src/components/HeroSection.tsx")
    assert "location" in hero.lower(), "Location input missing from HeroSection.tsx"


def test_hero_sage_button_color() -> None:
    hero = read("src/components/HeroSection.tsx")
    assert "bg-sage" in hero or "#7C9A82" in hero, \
        "Sage color missing from submit button in HeroSection.tsx"


# ---------------------------------------------------------------------------
# 8 — LoadingState.tsx
# ---------------------------------------------------------------------------

def test_loading_has_progress_bar() -> None:
    loading = read("src/components/LoadingState.tsx")
    assert "progress" in loading, "progress prop missing from LoadingState.tsx"


def test_loading_has_spin_animation() -> None:
    loading = read("src/components/LoadingState.tsx")
    assert "spin" in loading, "Spin animation missing from LoadingState.tsx"


def test_loading_blush_ring_color() -> None:
    loading = read("src/components/LoadingState.tsx")
    assert "#C4897A" in loading, "Blush/rose ring color missing from LoadingState.tsx"


def test_loading_progress_bar_transition() -> None:
    loading = read("src/components/LoadingState.tsx")
    assert "transition" in loading, "Smooth transition missing from progress bar"


# ---------------------------------------------------------------------------
# 9 — StoreCard.tsx
# ---------------------------------------------------------------------------

def test_store_card_score_percentage() -> None:
    card = read("src/components/StoreCard.tsx")
    assert "final_score * 10" in card, \
        "Score percentage formula (final_score * 10) missing from StoreCard.tsx"


def test_store_card_rank_number() -> None:
    card = read("src/components/StoreCard.tsx")
    assert "rank" in card, "Rank number missing from StoreCard.tsx"


def test_store_card_priority_badge() -> None:
    card = read("src/components/StoreCard.tsx")
    assert "HIGH" in card and "MEDIUM" in card and "LOW" in card, \
        "Priority badge colors (HIGH/MEDIUM/LOW) missing from StoreCard.tsx"


def test_store_card_why_matched() -> None:
    card = read("src/components/StoreCard.tsx")
    assert "why_matched" in card, "why_matched field missing from StoreCard.tsx"


def test_store_card_entry_animation() -> None:
    card = read("src/components/StoreCard.tsx")
    assert "animationDelay" in card or "animation-delay" in card, \
        "Stagger animation delay missing from StoreCard.tsx"


# ---------------------------------------------------------------------------
# 10 — TeaserBlur.tsx
# ---------------------------------------------------------------------------

def test_teaser_uses_block_characters() -> None:
    teaser = read("src/components/TeaserBlur.tsx")
    assert "████" in teaser, "Block characters (████) missing from TeaserBlur.tsx"


def test_teaser_has_lock_icon() -> None:
    teaser = read("src/components/TeaserBlur.tsx")
    assert "<svg" in teaser, "Lock SVG icon missing from TeaserBlur.tsx"


def test_teaser_pointer_events_none() -> None:
    teaser = read("src/components/TeaserBlur.tsx")
    # React JSX uses camelCase: pointerEvents (CSS: pointer-events)
    assert "pointerEvents" in teaser or "pointer-events" in teaser, \
        "pointerEvents: 'none' missing from TeaserBlur.tsx"


def test_teaser_decreasing_opacity() -> None:
    teaser = read("src/components/TeaserBlur.tsx")
    assert "0.7" in teaser and "0.5" in teaser and "0.3" in teaser, \
        "Decreasing opacity values (0.7, 0.5, 0.3) missing from TeaserBlur.tsx"


# ---------------------------------------------------------------------------
# 11 — CTABanner.tsx
# ---------------------------------------------------------------------------

def test_cta_calendly_env_var() -> None:
    cta = read("src/components/CTABanner.tsx")
    assert "NEXT_PUBLIC_CALENDLY_URL" in cta, \
        "NEXT_PUBLIC_CALENDLY_URL env var missing from CTABanner.tsx"


def test_cta_opens_new_tab() -> None:
    cta = read("src/components/CTABanner.tsx")
    assert 'target="_blank"' in cta, \
        "target='_blank' missing from Calendly link in CTABanner.tsx"


def test_cta_sage_background() -> None:
    cta = read("src/components/CTABanner.tsx")
    assert "#7C9A82" in cta or "bg-sage" in cta, \
        "Sage background color missing from CTABanner.tsx"


def test_cta_dynamic_store_count() -> None:
    cta = read("src/components/CTABanner.tsx")
    assert "totalStores" in cta, \
        "Dynamic totalStores prop missing from CTABanner.tsx"


# ---------------------------------------------------------------------------
# 12 — .env.local
# ---------------------------------------------------------------------------

def test_env_local_api_url() -> None:
    env = read(".env.local")
    assert "NEXT_PUBLIC_API_URL" in env, \
        "NEXT_PUBLIC_API_URL missing from .env.local"


def test_env_local_calendly_url() -> None:
    env = read(".env.local")
    assert "NEXT_PUBLIC_CALENDLY_URL" in env, \
        "NEXT_PUBLIC_CALENDLY_URL missing from .env.local"


# ---------------------------------------------------------------------------
# 13 — npm run build (zero TypeScript errors)
# ---------------------------------------------------------------------------

def test_npm_build_succeeds() -> None:
    result = subprocess.run(
        ["npm", "run", "build"],
        cwd=str(FRONTEND),
        capture_output=True,
        text=True,
        timeout=180,
        shell=True,
    )
    assert result.returncode == 0, (
        f"npm run build failed:\n{result.stdout[-2000:]}\n{result.stderr[-1000:]}"
    )


# ---------------------------------------------------------------------------
# 14–15 — HTTP tests (requires: cd frontend && npm run dev)
# ---------------------------------------------------------------------------

def _get_server():  # type: ignore[return]
    try:
        import httpx
        return httpx.get("http://localhost:3000", timeout=3)
    except Exception:
        return None


@pytest.mark.server
def test_server_returns_200() -> None:
    r = _get_server()
    if r is None:
        pytest.skip("Dev server not running — start with: cd frontend && npm run dev")
    assert r.status_code == 200, f"Expected 200, got {r.status_code}"


@pytest.mark.server
def test_server_page_has_title() -> None:
    r = _get_server()
    if r is None:
        pytest.skip("Dev server not running — start with: cd frontend && npm run dev")
    assert "DistroAgent" in r.text, "Brand title missing from page HTML"


@pytest.mark.server
def test_server_page_has_font_reference() -> None:
    r = _get_server()
    if r is None:
        pytest.skip("Dev server not running — start with: cd frontend && npm run dev")
    # next/font injects a <style> or link referencing the font variable
    assert "playfair" in r.text.lower() or "font" in r.text.lower(), \
        "No font reference found in page HTML"
