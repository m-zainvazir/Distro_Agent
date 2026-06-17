"""NegotiatorAgent — parses buyer objections and drafts rule-bound counter-offers.

Flow
----
parse_objection → check_rulebook → route_by_rulebook_check
    ├── within limits  → draft_counter → hitl_approval → finalize
    │                                                       ├── approved  → END
    │                                                       └── rejected  → draft_counter (retry)
    └── outside limits → escalate → END  (founder notified, no auto-counter)

Critical invariants
-------------------
- NEVER draft a counter that would violate the rulebook.
- Every drafted counter must pass through the HITL gate (interrupt).
- Out-of-rulebook requests always escalate — never auto-decide.
"""
from __future__ import annotations

import asyncio
import re
import uuid
from typing import Literal

from typing_extensions import TypedDict

from groq import AsyncGroq
from langgraph.graph import END, StateGraph


from app.agents.hitl_gate import DEAL, request_human_approval
from app.core.config import settings
from app.core.logging import logger
from app.models.rulebook import WholesaleRulebook

# ---------------------------------------------------------------------------
# Objection type constants
# ---------------------------------------------------------------------------

_MAX_COUNTER_COST_USD = 0.10   # safety ceiling per negotiation run

PRICE = "PRICE"
MOQ = "MOQ"
SHIPPING = "SHIPPING"
NET_TERMS = "NET_TERMS"
OTHER = "OTHER"

ObjectionType = Literal["PRICE", "MOQ", "SHIPPING", "NET_TERMS", "OTHER"]

# ---------------------------------------------------------------------------
# State
# ---------------------------------------------------------------------------


class NegotiatorState(TypedDict):
    objection_text: str
    buyer_email: str
    buyer_name: str               # display name for Stripe customer (defaults to email)
    original_email_id: str
    tenant_id: str
    rulebook: WholesaleRulebook
    objection_type: str
    within_rulebook: bool
    escalation_reason: str
    counter_offer_body: str
    counter_id: str
    revision_count: int
    approved: bool | None
    final_counter: str | None
    routing_action: str
    token_usage: dict[str, int]   # accumulated {"input": n, "output": n}
    cost_usd: float               # accumulated Groq spend for this run
    graph_thread_id: str          # LangGraph thread_id for HITL resume routing
    # Invoice fields — populated by caller; reviewed by admin before sending
    invoice_line_items: list[dict]  # [{description, amount_cents}]
    invoice_due_days: int           # days until invoice due (default 30)


# ---------------------------------------------------------------------------
# Objection classifier (keyword scoring — no external API)
# ---------------------------------------------------------------------------

_PRICE_PHRASES = ["too expensive", "too costly", "off retail", "wholesale price", "pricing too high"]
_PRICE_WORDS = ["price", "discount", "expensive", "costly", "margin", "markup", "pricing", "rate"]

_MOQ_PHRASES = ["minimum order quantity", "minimum order", "order minimum", "too many units", "minimum quantity"]
_MOQ_WORDS = ["moq", "units", "pieces", "quantity"]

_SHIPPING_PHRASES = ["shipping cost", "shipping fee", "shipping rate", "freight cost", "delivery cost"]
_SHIPPING_WORDS = ["shipping", "freight", "delivery", "transport", "postage"]

_NET_PHRASES = ["payment terms", "payment days", "net terms", "invoice terms", "billing terms"]
_NET_WORDS = ["net", "billing", "invoice", "payment"]


def _classify_objection_type(text: str) -> ObjectionType:
    """Classify objection into PRICE | MOQ | SHIPPING | NET_TERMS | OTHER.

    Uses keyword scoring: phrase matches score 2, word-boundary matches score 1.
    Ties resolved by dict insertion order (PRICE first) — reasonable default.
    """
    lower = text.lower()
    scores: dict[str, int] = {PRICE: 0, MOQ: 0, SHIPPING: 0, NET_TERMS: 0}

    for phrase in _PRICE_PHRASES:
        if phrase in lower:
            scores[PRICE] += 2
    for word in _PRICE_WORDS:
        if re.search(rf"\b{re.escape(word)}\b", lower):
            scores[PRICE] += 1

    for phrase in _MOQ_PHRASES:
        if phrase in lower:
            scores[MOQ] += 2
    for word in _MOQ_WORDS:
        if re.search(rf"\b{re.escape(word)}\b", lower):
            scores[MOQ] += 1

    for phrase in _SHIPPING_PHRASES:
        if phrase in lower:
            scores[SHIPPING] += 2
    for word in _SHIPPING_WORDS:
        if re.search(rf"\b{re.escape(word)}\b", lower):
            scores[SHIPPING] += 1

    for phrase in _NET_PHRASES:
        if phrase in lower:
            scores[NET_TERMS] += 2
    for word in _NET_WORDS:
        if re.search(rf"\b{re.escape(word)}\b", lower):
            scores[NET_TERMS] += 1

    best = max(scores, key=lambda k: scores[k])
    return OTHER if scores[best] == 0 else best  # type: ignore[return-value]


# ---------------------------------------------------------------------------
# Number extractors for rulebook boundary checks
# ---------------------------------------------------------------------------


def _extract_discount_pct(text: str) -> float | None:
    m = re.search(r"(\d+(?:\.\d+)?)\s*%", text)
    if m:
        return float(m.group(1))
    m = re.search(r"(\d+(?:\.\d+)?)\s+percent", text)
    if m:
        return float(m.group(1))
    return None


def _extract_quantity(text: str) -> int | None:
    m = re.search(r"(\d+)\s+(?:units?|pieces?|items?)", text)
    if m:
        return int(m.group(1))
    m = re.search(r"(?:minimum|at least|only|just)\s+(\d+)", text)
    if m:
        return int(m.group(1))
    return None


def _extract_net_days(text: str) -> int | None:
    m = re.search(r"net[-\s]?(\d+)", text)
    if m:
        return int(m.group(1))
    m = re.search(r"(\d+)[-\s]?day", text)
    if m:
        return int(m.group(1))
    m = re.search(r"(\d+)\s+days", text)
    if m:
        return int(m.group(1))
    return None


# ---------------------------------------------------------------------------
# Rulebook boundary check (deterministic, no LLM)
# ---------------------------------------------------------------------------


def _check_within_rulebook(
    objection_type: str,
    objection_text: str,
    rulebook: WholesaleRulebook,
) -> tuple[bool, str]:
    """Return (within_limits, escalation_reason).

    Non-negotiables are checked first regardless of objection type.
    """
    lower = objection_text.lower()

    # Non-negotiables always escalate — checked before type-specific logic
    for term in rulebook.non_negotiables:
        if term.lower() in lower:
            return False, f"Buyer request involves non-negotiable term: '{term}'"

    if objection_type == PRICE:
        discount = _extract_discount_pct(lower)
        if discount is not None and discount > rulebook.wholesale_discount_max_pct:
            return (
                False,
                f"Requested {discount:.0f}% discount exceeds "
                f"max allowed {rulebook.wholesale_discount_max_pct:.0f}%",
            )
        return True, ""

    if objection_type == MOQ:
        qty = _extract_quantity(lower)
        if qty is not None and qty < rulebook.min_order_quantity:
            return (
                False,
                f"Requested MOQ {qty} is below minimum {rulebook.min_order_quantity} units",
            )
        return True, ""

    if objection_type == NET_TERMS:
        days = _extract_net_days(lower)
        if days is not None and days > rulebook.net_payment_days_max:
            return (
                False,
                f"Requested Net {days} exceeds maximum Net {rulebook.net_payment_days_max}",
            )
        return True, ""

    if objection_type == SHIPPING:
        # Shipping objections are resolvable within rulebook (offer free shipping threshold)
        return True, ""

    # OTHER — cannot auto-resolve, always escalate
    return False, "Objection type OTHER requires founder judgment"


# ---------------------------------------------------------------------------
# Graph nodes
# ---------------------------------------------------------------------------


async def parse_objection_node(state: NegotiatorState) -> dict:
    objection_type = _classify_objection_type(state["objection_text"])
    logger.info("objection_parsed", type=objection_type)
    return {"objection_type": objection_type}


async def check_rulebook_node(state: NegotiatorState) -> dict:
    within, reason = _check_within_rulebook(
        state["objection_type"],
        state["objection_text"],
        state["rulebook"],
    )
    logger.info("rulebook_checked", within=within, reason=reason or "ok")
    return {"within_rulebook": within, "escalation_reason": reason}


def route_by_rulebook_check(
    state: NegotiatorState,
) -> Literal["draft_counter", "escalate"]:
    return "draft_counter" if state["within_rulebook"] else "escalate"


async def escalate_node(state: NegotiatorState) -> dict:
    """Notify founder — NEVER auto-counter an out-of-rulebook request."""
    logger.warning(
        "negotiator_escalating",
        objection_type=state["objection_type"],
        reason=state["escalation_reason"],
    )
    # Production: send WhatsApp alert to founder with context
    try:
        from app.services.whatsapp_service import send_deal_alert

        await send_deal_alert(
            phone=settings.whatsapp_founder_phone,
            store_name=state.get("buyer_email", "buyer"),
            reply_summary=(
                f"Objection escalated ({state['objection_type']}): "
                f"{state['objection_text'][:200]}\n"
                f"Reason: {state['escalation_reason']}"
            ),
        )
    except Exception as exc:
        logger.warning("escalate_whatsapp_failed", error=str(exc))

    return {"routing_action": "escalated_to_founder"}


async def draft_counter_node(state: NegotiatorState) -> dict:
    """Draft a counter-offer strictly within rulebook limits using Groq."""
    rulebook = state["rulebook"]
    system_prompt = (
        "You are a wholesale negotiation specialist.\n"
        "Draft a professional, empathetic counter-offer STRICTLY within these limits:\n"
        f"- Max wholesale discount: {rulebook.wholesale_discount_max_pct:.0f}% off retail\n"
        f"- Minimum order: {rulebook.min_order_quantity} units\n"
        f"- Max payment terms: Net {rulebook.net_payment_days_max}\n"
        f"- Free shipping on orders over ${rulebook.free_shipping_threshold:.0f}\n\n"
        "RULES (non-negotiable):\n"
        "1. Never exceed the limits above\n"
        "2. Cite specific numbers when addressing the concern\n"
        "3. Warm, collaborative tone\n"
        "4. Under 150 words\n"
        "5. End with a clear call to proceed"
    )
    user_prompt = (
        f"Buyer objection ({state['objection_type']}):\n"
        f"{state['objection_text']}\n\n"
        "Draft a counter-offer that addresses this within our wholesale terms."
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
                max_tokens=400,
            )
            counter = resp.choices[0].message.content or ""
            prev = state.get("token_usage", {"input": 0, "output": 0})
            new_in = getattr(resp.usage, "prompt_tokens", 0) if resp.usage else 0
            new_out = getattr(resp.usage, "completion_tokens", 0) if resp.usage else 0
            new_cost = (new_in / 1000) * 0.00059 + (new_out / 1000) * 0.00079
            logger.info(
                "groq_token_usage",
                node="draft_counter",
                input_tokens=new_in,
                output_tokens=new_out,
                cost_usd=round(new_cost, 6),
            )
            logger.info("draft_counter_complete", objection_type=state["objection_type"])
            return {
                "counter_offer_body": counter,
                "revision_count": state.get("revision_count", 0) + 1,
                "token_usage": {
                    "input": prev.get("input", 0) + new_in,
                    "output": prev.get("output", 0) + new_out,
                },
                "cost_usd": round(state.get("cost_usd", 0.0) + new_cost, 6),
            }
        except Exception as exc:
            last_exc = exc
            logger.warning("draft_counter_retry", attempt=attempt + 1, error=str(exc))
            if attempt < 2:
                await asyncio.sleep(1.5 * (attempt + 1))

    logger.error("draft_counter_failed", error=str(last_exc))
    return {
        "counter_offer_body": (
            "Thank you for your feedback. We would love to work within your "
            "needs — please reply and we can discuss further."
        ),
        "revision_count": state.get("revision_count", 0) + 1,
        "token_usage": state.get("token_usage", {"input": 0, "output": 0}),
        "cost_usd": state.get("cost_usd", 0.0),
    }


async def hitl_approval_node(state: NegotiatorState) -> dict:
    """Pause for founder approval — every counter must be approved before sending."""
    counter_id = str(uuid.uuid4())

    logger.info(
        "negotiator_hitl_requested",
        counter_id=counter_id,
        objection_type=state["objection_type"],
    )

    try:
        from app.services.campaign_service import register_pending
        from app.services.whatsapp_service import send_approval_card

        register_pending(
            counter_id,
            state.get("graph_thread_id", "unknown"),
            state.get("buyer_email", ""),
            graph_type="negotiator",
            tenant_id=state.get("tenant_id", ""),
        )
        await send_approval_card(
            phone=settings.whatsapp_founder_phone,
            email_preview=state["counter_offer_body"][:300],
            email_id=counter_id,
        )
    except Exception as exc:
        logger.warning("negotiator_whatsapp_failed", error=str(exc))

    from app.services.tenant_service import get_autonomy_mode

    autonomy_mode = await get_autonomy_mode(state.get("tenant_id", ""))
    approved: bool = request_human_approval(
        {
            "counter_id": counter_id,
            "objection_type": state["objection_type"],
            "counter_preview": state["counter_offer_body"][:300],
            "escalation_reason": state.get("escalation_reason", ""),
        },
        action_class=DEAL,
        autonomy_mode=autonomy_mode,
    )

    return {"approved": approved, "counter_id": counter_id}


def _dispatch_invoice_task(state: NegotiatorState) -> None:
    """Fire-and-forget: dispatch Celery invoice task after agreement is reached."""
    try:
        from app.tasks.invoice_task import generate_and_send_invoice_task

        generate_and_send_invoice_task.delay(
            email_id=state.get("original_email_id", ""),
            tenant_id=state.get("tenant_id", ""),
            buyer_email=state.get("buyer_email", ""),
            buyer_name=state.get("buyer_name", ""),
            line_items=state.get("invoice_line_items", []),
            due_days=state.get("invoice_due_days", 30),
            agreed_terms=state.get("counter_offer_body", ""),
        )
        logger.info(
            "invoice_task_dispatched",
            email_id=state.get("original_email_id"),
            buyer_email=state.get("buyer_email"),
        )
    except Exception as exc:
        logger.warning("invoice_task_dispatch_failed", error=str(exc))


async def finalize_node(state: NegotiatorState) -> dict:
    approved = state.get("approved")

    if approved:
        logger.info("counter_approved", objection_type=state["objection_type"])
        _dispatch_invoice_task(state)
        return {
            "final_counter": state["counter_offer_body"],
            "routing_action": "counter_approved",
        }

    # Rejected — reset for re-draft. Do NOT reset approved here;
    # route_after_finalize reads approved=False to loop back.
    logger.info("counter_rejected", objection_type=state["objection_type"])
    return {
        "counter_offer_body": "",
        "revision_count": 0,
    }


def route_after_finalize(state: NegotiatorState) -> str:
    if state.get("approved") is False:
        if state.get("cost_usd", 0.0) >= _MAX_COUNTER_COST_USD:
            logger.warning("negotiator_cost_budget_exceeded", cost_usd=state.get("cost_usd"))
            return END
        return "draft_counter"
    return END


# ---------------------------------------------------------------------------
# Graph factory
# ---------------------------------------------------------------------------


def build_negotiator_graph(checkpointer=None):
    """Compile the Negotiator graph.

    Requires a checkpointer (MemorySaver or AsyncPostgresSaver) for the
    hitl_approval_node interrupt to persist state across HTTP requests.
    """
    graph = StateGraph(NegotiatorState)

    graph.add_node("parse_objection", parse_objection_node)
    graph.add_node("check_rulebook", check_rulebook_node)
    graph.add_node("draft_counter", draft_counter_node)
    graph.add_node("escalate", escalate_node)
    graph.add_node("hitl_approval", hitl_approval_node)
    graph.add_node("finalize", finalize_node)

    graph.set_entry_point("parse_objection")
    graph.add_edge("parse_objection", "check_rulebook")
    graph.add_conditional_edges(
        "check_rulebook",
        route_by_rulebook_check,
        {"draft_counter": "draft_counter", "escalate": "escalate"},
    )
    graph.add_edge("escalate", END)
    graph.add_edge("draft_counter", "hitl_approval")
    graph.add_edge("hitl_approval", "finalize")
    graph.add_conditional_edges(
        "finalize",
        route_after_finalize,
        {"draft_counter": "draft_counter", END: END},
    )

    return graph.compile(checkpointer=checkpointer)
