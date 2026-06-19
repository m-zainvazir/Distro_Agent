"""Campaign launch service — turn stored brand + store rows into a live Phase 2 run.

`POST /api/v1/campaigns/start` calls into here. For each selected store we kick
off the Phase 2 master graph (copywriter → dispatch → reply → negotiate/schedule)
as a FastAPI BackgroundTask, run it to its first HITL pause (the copywriter draft
approval), and register the pause so the existing `/campaigns/{email_id}/approve`
and `/reject` endpoints can resume it.

The persisted DB schema (`BrandProfileRecord`, `StoreCandidate`) is thinner than
the rich Pydantic models the agents consume (`BrandProfile`, `ScoredStore`), so
the mappers below synthesise sensible defaults for fields the DB does not store.
"""
from __future__ import annotations

import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.logging import logger
from app.models.brand_profile import BrandProfile
from app.models.campaign import BrandProfileRecord, StoreCandidate
from app.models.store_candidate import (
    DimensionScore,
    ScoredStore,
    compute_priority,
)
from app.models.store_candidate import StoreCandidate as ScoredStoreCandidate


def record_to_brand_profile(rec: BrandProfileRecord) -> BrandProfile:
    """Map a persisted BrandProfileRecord into the Pydantic BrandProfile agents use."""
    keywords = list(rec.aesthetic_keywords or [])
    price_min = float(rec.price_range_min) if rec.price_range_min is not None else 0.0
    price_max = float(rec.price_range_max) if rec.price_range_max is not None else 0.0
    embedding = list(rec.embedding_vector or [])
    return BrandProfile(
        brand_name=rec.brand_name,
        tagline="",
        primary_colors=[],
        aesthetic_keywords=keywords,
        product_categories=[],
        price_range=(price_min, price_max),
        brand_voice_description="",
        wholesale_readiness_score=0.0,
        raw_product_images=[],
        embedding_vector=embedding,
    )


def record_to_scored_store(store: StoreCandidate) -> ScoredStore:
    """Map a persisted StoreCandidate row into a ScoredStore for the agent swarm.

    Scoring already happened during discovery; we only carry the stored
    `lead_score`/`vibe_score` forward and fill structural defaults for the
    fields the discovery pipeline did not persist.
    """
    final_score = float(store.lead_score) if store.lead_score is not None else 0.0
    vibe = float(store.vibe_score) if store.vibe_score is not None else 0.0
    candidate = ScoredStoreCandidate(
        place_id=store.google_place_id or str(store.id),
        name=store.name,
        address=store.address or "",
        city="",
        state="",
        google_categories=[],
        website_url=None,
        instagram_handle=store.instagram_handle,
        instagram_followers=None,
        instagram_posts_last_30_days=None,
        storefront_image_urls=[],
        price_tier=None,
        review_snippets=[],
    )
    placeholder = DimensionScore(score=final_score, reasoning="carried from discovery", data_used=[])
    return ScoredStore(
        store=candidate,
        visual_vibe_score=DimensionScore(score=vibe, reasoning="stored vibe", data_used=[]),
        category_score=placeholder,
        price_score=placeholder,
        engagement_score=placeholder,
        wholesale_score=placeholder,
        text_score=final_score,
        final_score=final_score,
        vision_was_run=False,
        match_summary=f"{store.name} matched during discovery",
        why_matched=f"{store.name} fits the brand aesthetic",
        outreach_priority=compute_priority(final_score),
    )


async def load_campaign_inputs(
    db: AsyncSession,
    tenant_id: str,
    brand_profile_id: str,
    store_ids: list[str],
) -> tuple[BrandProfileRecord, list[StoreCandidate]]:
    """Load the brand profile + selected stores, scoped to the tenant.

    Raises LookupError if the brand profile is missing or no stores match.
    """
    tid = uuid.UUID(tenant_id)

    brand_result = await db.execute(
        select(BrandProfileRecord).where(
            BrandProfileRecord.id == uuid.UUID(brand_profile_id),
            BrandProfileRecord.tenant_id == tid,
        )
    )
    brand_rec = brand_result.scalar_one_or_none()
    if brand_rec is None:
        raise LookupError("brand_profile not found for this tenant")

    store_uuids = [uuid.UUID(s) for s in store_ids]
    store_result = await db.execute(
        select(StoreCandidate).where(
            StoreCandidate.id.in_(store_uuids),
            StoreCandidate.tenant_id == tid,
        )
    )
    stores = list(store_result.scalars().all())
    if not stores:
        raise LookupError("no matching stores found for this tenant")

    return brand_rec, stores


async def run_phase2_for_store(
    *,
    tenant_id: str,
    campaign_id: str,
    brand_profile: BrandProfile,
    scored_store: ScoredStore,
    store_db_id: str,
    buyer_email: str,
    buyer_name: str,
    founder_name: str,
    email_tone: str,
) -> str:
    """Run the Phase 2 graph for one store up to its first HITL pause.

    Returns the email_id awaiting approval (empty string if the graph finished
    without pausing, e.g. under full_auto autonomy). Registers the pause so the
    approve/reject endpoints can resume the same Phase 2 thread.
    """
    from app.core.checkpointer import get_checkpointer
    from app.services.campaign_service import register_pending_approval
    from app.workflows.phase2_workflow import build_phase2_graph

    checkpointer = await get_checkpointer()
    graph = build_phase2_graph(checkpointer=checkpointer)
    thread_id = f"phase2-{campaign_id}-{store_db_id}"
    config: dict = {"configurable": {"thread_id": thread_id}}

    initial: dict = {
        "tenant_id": tenant_id,
        "brand_profile": brand_profile,
        "store": scored_store,
        "founder_name": founder_name,
        "email_tone": email_tone,
        "campaign_id": campaign_id,
        "store_db_id": store_db_id,
        "buyer_email": buyer_email,
        "buyer_name": buyer_name,
        "approved_email": None,
        "copywriter_thread_id": "",
        "outreach_email_id": "",
        "email_sent": False,
        "reply_text": "",
        "sender_email": "",
        "gmail_thread_id": "",
        "reply_intent": "",
        "negotiation_thread_id": "",
        "scheduling_thread_id": "",
        "meet_link": "",
        "phase": "",
        "follow_up_count": 0,
        "errors": [],
    }

    store_name = scored_store.store.name
    try:
        result = await graph.ainvoke(initial, config=config)
    except Exception as exc:
        logger.error(
            "campaign_phase2_run_failed",
            campaign_id=campaign_id,
            store_db_id=store_db_id,
            error=str(exc),
        )
        return ""

    interrupts = result.get("__interrupt__") if isinstance(result, dict) else None
    if not interrupts:
        logger.info(
            "campaign_phase2_no_pause",
            campaign_id=campaign_id,
            store_db_id=store_db_id,
            phase=result.get("phase", "") if isinstance(result, dict) else "",
        )
        return ""

    payload = getattr(interrupts[0], "value", interrupts[0])
    email_id = payload.get("email_id", "") if isinstance(payload, dict) else ""
    if not email_id:
        logger.warning(
            "campaign_phase2_pause_no_email_id",
            campaign_id=campaign_id,
            store_db_id=store_db_id,
        )
        return ""

    register_pending_approval(
        email_id=email_id,
        thread_id=thread_id,
        store_name=store_name,
        graph_type="phase2",
        tenant_id=tenant_id,
    )
    logger.info(
        "campaign_phase2_paused_for_approval",
        campaign_id=campaign_id,
        store_db_id=store_db_id,
        email_id=email_id,
        thread_id=thread_id,
    )
    return email_id
