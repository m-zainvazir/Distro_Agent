"""Real-world Phase 1 smoke test — runs the full pipeline end-to-end.

Invokes the Phase 1 LangGraph (brand extraction -> scout -> analyst -> report)
synchronously, against a real brand URL and target city. No Celery worker,
frontend, or database required — only GROQ_API_KEY + GOOGLE_MAPS_API_KEY + internet.

Usage:
    .venv/Scripts/python -m scripts.run_phase1_test [brand_url] [vertical_tag] [location]
"""
import asyncio
import sys
import time

from app.workflows.phase1_workflow import phase1_graph


async def main() -> None:
    brand_url = sys.argv[1] if len(sys.argv) > 1 else "https://www.allbirds.com"
    vertical = sys.argv[2] if len(sys.argv) > 2 else "footwear"
    location = sys.argv[3] if len(sys.argv) > 3 else "Los Angeles, CA"

    print(f"\n{'=' * 60}")
    print(f"Brand:    {brand_url}")
    print(f"Vertical: {vertical}")
    print(f"Location: {location}")
    print(f"{'=' * 60}")

    start = time.perf_counter()
    result = await phase1_graph.ainvoke(
        {
            "brand_url": brand_url,
            "vertical_tag": vertical,
            "target_location": location,
            "tenant_id": "test",
            "brand_profile": None,
            "store_candidates": [],
            "scored_stores": [],
            "report_url": "",
            "errors": [],
        }
    )
    elapsed = time.perf_counter() - start

    profile = result.get("brand_profile")
    print(f"\n=== BRAND: {profile.brand_name if profile else 'FAILED'} ===")
    if profile:
        print(f"  Tagline:   {profile.tagline}")
        print(f"  Keywords:  {', '.join(profile.aesthetic_keywords)}")
        print(f"  Price:     ${profile.price_range[0]}-${profile.price_range[1]}")
        print(f"  Wholesale readiness: {profile.wholesale_readiness_score}/10")

    scored = result.get("scored_stores", [])
    print(f"\n=== {len(scored)} STORES SCORED ===")
    for i, s in enumerate(scored[:10], 1):
        print(
            f"{i}. {s.store.name} ({s.store.city}) — "
            f"{s.final_score:.1f}/10 [{s.outreach_priority}]"
        )
        print(f"   {s.match_summary}")

    if result.get("report_url"):
        print(f"\nReport written to: {result['report_url']}")
    if result.get("errors"):
        print(f"\nErrors: {result['errors']}")
    print(f"\nElapsed: {elapsed:.1f}s")


if __name__ == "__main__":
    asyncio.run(main())
