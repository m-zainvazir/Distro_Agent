"""CopywriterAgent — drafts personalised B2B outreach emails with a self-critique
loop, then pauses for founder approval via LangGraph interrupt().

Loop:  draft → critique → [revise if score < 7.0, max 2 loops] → HITL pause → finalise
"""

import asyncio
import json
import re
import uuid
from typing import Literal
from typing_extensions import TypedDict

from groq import AsyncGroq
from langgraph.graph import END, StateGraph

from app.agents.hitl_gate import request_human_approval
from app.core.config import settings
from app.core.logging import logger
from app.models.brand_profile import BrandProfile
from app.models.outreach import OutreachEmailDraft
from app.models.store_candidate import ScoredStore

_MAX_DRAFT_COST_USD = 0.10   # safety ceiling per outreach email run

_SPAM_WORDS = {
    "free", "guaranteed", "urgent", "limited time", "act now",
    "click here", "winner", "prize", "deal", "% off",
}


# ---------------------------------------------------------------------------
# State
# ---------------------------------------------------------------------------

class CopywriterState(TypedDict):
    store: ScoredStore
    brand_profile: BrandProfile
    founder_name: str
    email_tone: str           # "warm" | "professional" | "casual"
    tenant_id: str
    campaign_id: str          # OutreachCampaign DB id (empty = skip DB persist)
    store_db_id: str          # StoreCandidate DB id   (empty = skip DB persist)
    draft_subject_a: str
    draft_subject_b: str
    draft_body: str
    personalization_score: float
    critique_notes: str
    revision_count: int
    approved: bool | None     # set by HITL resume
    final_email: OutreachEmailDraft | None
    token_usage: dict[str, int]   # accumulated {"input": n, "output": n}
    cost_usd: float               # accumulated Groq spend for this run


# ---------------------------------------------------------------------------
# Nodes
# ---------------------------------------------------------------------------

async def draft_node(state: CopywriterState) -> dict:
    store = state["store"]
    brand = state["brand_profile"]
    revision_count = state.get("revision_count", 0)
    critique = state.get("critique_notes", "")

    revision_note = (
        f"\n\nPrevious critique — please fix these issues:\n{critique}"
        if critique and revision_count > 0
        else ""
    )

    system_prompt = (
        "You are a B2B wholesale outreach specialist writing personalised pitches "
        "for indie retail partnerships.\n\n"
        "RULES (non-negotiable):\n"
        f"1. Mention the store name EXACTLY 2 times in the body\n"
        "2. Reference the store's specific aesthetic/vibe at least once\n"
        "3. Mention at least one specific product from the brand that fits the store\n"
        "4. Include wholesale terms (MOQ and wholesale pricing tier)\n"
        "5. ONE clear CTA: invite them to reply to learn more\n"
        "6. Body: 150-200 words\n"
        "7. Subject lines: under 60 characters each, no spam words\n"
        f"8. Tone: {state['email_tone']}\n\n"
        "Return ONLY valid JSON with keys: subject_a, subject_b, body"
    )
    user_prompt = (
        f"Brand: {brand.brand_name}\n"
        f"Products: {', '.join(brand.product_categories[:5])}\n"
        f"Aesthetic: {', '.join(brand.aesthetic_keywords[:5])}\n"
        f"Price range: ${brand.price_range[0]:.0f}–${brand.price_range[1]:.0f}\n"
        f"Brand voice: {brand.brand_voice_description[:200]}\n\n"
        f"Target store: {store.store.name}\n"
        f"Location: {store.store.city}, {store.store.state}\n"
        f"Why it fits: {store.why_matched}\n"
        f"Sender: {state['founder_name']}"
        f"{revision_note}"
    )

    client = AsyncGroq(api_key=settings.groq_api_key)
    last_exc: Exception | None = None
    for attempt in range(3):
        try:
            resp = await client.chat.completions.create(
                model=settings.groq_model,
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt},
                ],
                response_format={"type": "json_object"},
                max_tokens=800,
            )
            draft = json.loads(resp.choices[0].message.content or "{}")
            prev = state.get("token_usage", {"input": 0, "output": 0})
            new_in = getattr(resp.usage, "prompt_tokens", 0) if resp.usage else 0
            new_out = getattr(resp.usage, "completion_tokens", 0) if resp.usage else 0
            new_cost = (new_in / 1000) * 0.00059 + (new_out / 1000) * 0.00079
            logger.info(
                "groq_token_usage",
                node="draft",
                input_tokens=new_in,
                output_tokens=new_out,
                cost_usd=round(new_cost, 6),
            )
            logger.info("draft_node_complete", store=store.store.name, attempt=attempt + 1)
            return {
                "draft_subject_a": draft.get("subject_a", ""),
                "draft_subject_b": draft.get("subject_b", ""),
                "draft_body": draft.get("body", ""),
                "revision_count": revision_count + 1,
                "token_usage": {
                    "input": prev.get("input", 0) + new_in,
                    "output": prev.get("output", 0) + new_out,
                },
                "cost_usd": round(state.get("cost_usd", 0.0) + new_cost, 6),
            }
        except Exception as exc:
            last_exc = exc
            logger.warning("draft_node_retry", attempt=attempt + 1, error=str(exc))
            if attempt < 2:
                await asyncio.sleep(1.5 * (attempt + 1))

    logger.error("draft_node_failed", error=str(last_exc))
    return {
        "draft_subject_a": f"Wholesale partnership with {store.store.name}",
        "draft_subject_b": f"{brand.brand_name} wholesale opportunity",
        "draft_body": (
            f"Hi {store.store.name} team, we'd love to discuss a wholesale partnership. "
            f"Please reply to learn more. — {state['founder_name']}"
        ),
        "revision_count": revision_count + 1,
        "token_usage": state.get("token_usage", {"input": 0, "output": 0}),
        "cost_usd": state.get("cost_usd", 0.0),
    }


async def critique_node(state: CopywriterState) -> dict:
    """Score the draft deterministically against all personalisation rules."""
    body = state.get("draft_body", "")
    subject_a = state.get("draft_subject_a", "")
    subject_b = state.get("draft_subject_b", "")
    store_name = state["store"].store.name
    why_matched = state["store"].why_matched

    score = 10.0
    issues: list[str] = []

    # Rule 1: store name >= 2x
    name_count = body.lower().count(store_name.lower())
    if name_count < 2:
        score -= 3.0
        issues.append(f"Store name appears {name_count}x (need 2)")

    # Rule 2: body word count 150-200
    word_count = len(body.split())
    if word_count < 150:
        score -= 2.0
        issues.append(f"Body too short: {word_count} words")
    elif word_count > 200:
        score -= 1.0
        issues.append(f"Body too long: {word_count} words")

    # Rule 3: subject length < 60 chars
    if len(subject_a) >= 60:
        score -= 1.0
        issues.append(f"Subject A too long ({len(subject_a)} chars)")
    if len(subject_b) >= 60:
        score -= 1.0
        issues.append(f"Subject B too long ({len(subject_b)} chars)")

    # Rule 4: subjects are distinct
    if subject_a.lower().strip() == subject_b.lower().strip():
        score -= 1.0
        issues.append("Subject A and B are identical")

    # Rule 5: no spam words — word-boundary match for single words to avoid
    # false positives like "cruelty-free" triggering "free".
    body_lower = body.lower()
    found_spam = []
    for w in _SPAM_WORDS:
        if " " in w or "%" in w:  # multi-word / special-char: substring match
            if w in body_lower:
                found_spam.append(w)
        elif re.search(r"\b" + re.escape(w) + r"\b", body_lower):
            found_spam.append(w)
    if found_spam:
        score -= 2.0
        issues.append(f"Spam trigger words: {', '.join(found_spam)}")

    # Rule 6: vibe referenced (at least one keyword from why_matched)
    vibe_words = [w.lower() for w in why_matched.split() if len(w) > 4 and w.isalpha()][:5]
    if vibe_words and not any(w in body_lower for w in vibe_words):
        score -= 1.5
        issues.append("Store vibe not referenced in body")

    score = round(max(0.0, score), 1)
    notes = "; ".join(issues) if issues else "All personalisation checks passed."
    logger.info("critique_node_complete", score=score, store=store_name)
    return {"personalization_score": score, "critique_notes": notes}


def route_revision(
    state: CopywriterState,
) -> Literal["draft", "hitl_approval"]:
    over_budget = state.get("cost_usd", 0.0) >= _MAX_DRAFT_COST_USD
    if over_budget:
        logger.warning("copywriter_cost_budget_exceeded", cost_usd=state.get("cost_usd"))
    if state["personalization_score"] < 7.0 and state.get("revision_count", 0) < 2 and not over_budget:
        return "draft"
    return "hitl_approval"


async def hitl_approval_node(state: CopywriterState) -> dict:
    """Save draft to DB (if campaign_id set), then pause for founder approval."""
    email_id = await _persist_pending_email(state)

    logger.info(
        "hitl_approval_requested",
        email_id=str(email_id),
        store=state["store"].store.name,
        score=state["personalization_score"],
    )

    # Send WhatsApp approval card (Block D wires this up fully)
    try:
        from app.services.whatsapp_service import send_approval_card
        from app.services.campaign_service import register_pending

        register_pending(str(email_id), "pending", state["store"].store.name, tenant_id=state["tenant_id"])
        # Founder phone comes from the tenant's whatsapp_number — stub for now
        await send_approval_card(
            phone=settings.whatsapp_founder_phone,
            email_preview=state["draft_body"][:300],
            email_id=str(email_id),
        )
    except Exception as exc:
        logger.warning("whatsapp_send_failed", error=str(exc))

    # Pause graph — resumes when webhook calls Command(resume=True/False)
    approved: bool = request_human_approval({
        "email_id": str(email_id),
        "store_name": state["store"].store.name,
        "subject_a": state["draft_subject_a"],
        "subject_b": state["draft_subject_b"],
        "body_preview": state["draft_body"][:300],
        "personalization_score": state["personalization_score"],
    })

    return {"approved": approved}


async def finalize_node(state: CopywriterState) -> dict:
    """Update DB status and package the final email, or reset for re-draft."""
    approved = state.get("approved")

    if approved:
        logger.info("email_approved", store=state["store"].store.name)
        return {
            "final_email": OutreachEmailDraft(
                subject_a=state["draft_subject_a"],
                subject_b=state["draft_subject_b"],
                body=state["draft_body"],
                personalization_score=state["personalization_score"],
                status="approved",
            )
        }

    # Rejected — reset counters for a fresh draft; do NOT reset approved here.
    # route_after_finalize reads approved=False from state to route back to draft.
    logger.info("email_rejected", store=state["store"].store.name)
    return {
        "revision_count": 0,
        "critique_notes": "Founder rejected — please revise and try again.",
        "final_email": None,
    }


def route_after_finalize(state: CopywriterState) -> str:
    if state.get("approved") is False:
        return "draft"
    return END


# ---------------------------------------------------------------------------
# DB helper (mockable in tests)
# ---------------------------------------------------------------------------

async def _persist_pending_email(state: CopywriterState) -> uuid.UUID:
    """Save draft to DB as pending_approval if campaign/store IDs are provided."""
    email_id = uuid.uuid4()

    if not state.get("campaign_id") or not state.get("store_db_id"):
        return email_id  # test / dry-run path — skip DB

    try:
        from app.core.database import AsyncSessionLocal
        from app.models.campaign import OutreachEmail as OutreachEmailRecord

        async with AsyncSessionLocal() as session:
            record = OutreachEmailRecord(
                id=email_id,
                campaign_id=uuid.UUID(state["campaign_id"]),
                store_id=uuid.UUID(state["store_db_id"]),
                subject=state["draft_subject_a"],
                body=state["draft_body"],
                outcome="pending_approval",
            )
            session.add(record)
            await session.commit()
            logger.info("email_persisted", email_id=str(email_id))
    except Exception as exc:
        logger.error("email_persist_failed", error=str(exc))

    return email_id


# ---------------------------------------------------------------------------
# Graph factory
# ---------------------------------------------------------------------------

def _build_graph() -> StateGraph:
    graph = StateGraph(CopywriterState)

    graph.add_node("draft", draft_node)
    graph.add_node("critique", critique_node)
    graph.add_node("hitl_approval", hitl_approval_node)
    graph.add_node("finalize", finalize_node)

    graph.set_entry_point("draft")
    graph.add_edge("draft", "critique")
    graph.add_conditional_edges(
        "critique",
        route_revision,
        {"draft": "draft", "hitl_approval": "hitl_approval"},
    )
    graph.add_edge("hitl_approval", "finalize")
    graph.add_conditional_edges(
        "finalize",
        route_after_finalize,
        {"draft": "draft", END: END},
    )

    return graph


def build_copywriter_graph(checkpointer=None):
    """Compile the graph.

    Pass ``MemorySaver()`` for single-process use or ``AsyncPostgresSaver``
    for production. Without a checkpointer the interrupt() will raise
    ``GraphInterrupt`` instead of saving state.
    """
    return _build_graph().compile(checkpointer=checkpointer)
