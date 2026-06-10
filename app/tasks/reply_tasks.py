"""Celery task: check Gmail for replies hourly + run follow-up sequencer."""
from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone

from app.celery_app import celery_app
from app.core.logging import logger

_FOLLOWUP_INTERVAL_DAYS = 5
_MAX_FOLLOWUPS = 2

# In-memory idempotency guard for processed Gmail message IDs.
# Prevents double-processing within a single worker process lifetime.
_processed_gmail_ids: set[str] = set()


# ---------------------------------------------------------------------------
# Follow-up sequencer (extracted for direct testing)
# ---------------------------------------------------------------------------


async def _process_followup(
    email: object,
    db: object,
    tenant_id: str = "",
) -> str:  # type: ignore[type-arg]
    """Advance a single stale email through the follow-up sequence.

    All follow-ups are routed through HITL (outcome='pending_approval') so
    the founder approves before anything is sent.  After _MAX_FOLLOWUPS the
    lead is marked dormant and no further outreach occurs.

    Returns:
        "queued"  — follow-up queued for HITL approval
        "dormant" — max follow-ups exhausted, lead marked ignored
    """
    from app.services.campaign_service import register_pending_approval

    follow_up_count: int = getattr(email, "follow_up_count", 0) or 0

    if follow_up_count >= _MAX_FOLLOWUPS:
        email.outcome = "ignored"  # type: ignore[attr-defined]
        await db.commit()  # type: ignore[attr-defined]
        logger.info("lead_marked_dormant", email_id=str(getattr(email, "id", "")))
        return "dormant"

    email.follow_up_count = follow_up_count + 1  # type: ignore[attr-defined]
    email.outcome = "pending_approval"  # type: ignore[attr-defined]
    await db.commit()  # type: ignore[attr-defined]

    email_id_str = str(getattr(email, "id", ""))
    register_pending_approval(
        email_id=email_id_str,
        thread_id=f"followup-{email_id_str}",
        store_name="",
        graph_type="followup",
        tenant_id=tenant_id,
    )
    logger.info(
        "followup_queued_hitl",
        email_id=email_id_str,
        follow_up_number=email.follow_up_count,  # type: ignore[attr-defined]
    )
    return "queued"


# ---------------------------------------------------------------------------
# Main async pipeline
# ---------------------------------------------------------------------------


async def _check_replies() -> dict:
    from sqlalchemy.future import select

    from app.agents.reply_handler_agent import build_reply_handler_graph
    from app.core.database import AsyncSessionLocal
    from app.models.campaign import OutreachEmail
    from app.services.gmail_service import fetch_new_replies

    classified = 0
    followed_up = 0
    errors = 0

    async with AsyncSessionLocal() as db:
        # ── 1. Collect outbound message_ids to match replies against ────────
        sent_res = await db.execute(
            select(OutreachEmail).where(
                OutreachEmail.outcome == "sent",
                OutreachEmail.message_id.isnot(None),
            )
        )
        sent_emails: list[OutreachEmail] = list(sent_res.scalars().all())
        known_ids: set[str] = {e.message_id for e in sent_emails if e.message_id}

        # ── 2. Classify new replies ──────────────────────────────────────────
        replies = await fetch_new_replies(known_ids)
        graph = build_reply_handler_graph()

        for reply in replies:
            if reply.gmail_message_id in _processed_gmail_ids:
                continue  # idempotency guard

            matching = next(
                (e for e in sent_emails if e.message_id == reply.in_reply_to),
                None,
            )
            if matching is None:
                continue

            tenant_id = str(matching.tenant_id or "")  # type: ignore[attr-defined]

            try:
                result = await graph.ainvoke(
                    {
                        "reply_text": reply.body,
                        "sender_email": reply.sender,
                        "gmail_thread_id": reply.gmail_thread_id,
                        "email_id": str(matching.id),
                        "tenant_id": tenant_id,
                        "intent": "",
                        "routing_action": "",
                        "notes": "",
                    }
                )

                matching.reply_received = True
                matching.reply_content = reply.body[:2000]
                matching.reply_intent = result.get("intent", "")
                matching.outcome = "replied"
                await db.commit()

                _processed_gmail_ids.add(reply.gmail_message_id)
                classified += 1
                logger.info(
                    "reply_processed",
                    email_id=str(matching.id),
                    intent=result.get("intent"),
                    action=result.get("routing_action"),
                )
            except Exception as exc:
                errors += 1
                logger.error(
                    "reply_classify_error",
                    email_id=str(matching.id),
                    error=str(exc),
                )

        # ── 3. Follow-up sequencer ───────────────────────────────────────────
        now = datetime.now(timezone.utc)
        cutoff = now - timedelta(days=_FOLLOWUP_INTERVAL_DAYS)

        stale_res = await db.execute(
            select(OutreachEmail).where(
                OutreachEmail.outcome == "sent",
                OutreachEmail.reply_received.is_(False),
                OutreachEmail.sent_at <= cutoff,
            )
        )
        stale_emails: list[OutreachEmail] = list(stale_res.scalars().all())

        for email in stale_emails:
            stale_tenant_id = str(email.tenant_id or "")  # type: ignore[attr-defined]
            action = await _process_followup(email, db, tenant_id=stale_tenant_id)
            if action in ("queued", "dormant"):
                followed_up += 1

    return {"classified": classified, "followed_up": followed_up, "errors": errors}


# ---------------------------------------------------------------------------
# Celery entry point
# ---------------------------------------------------------------------------


@celery_app.task(name="replies.check_replies")
def check_replies_task() -> dict:
    """Check Gmail for new replies and run the follow-up sequencer.

    Scheduled hourly via Celery beat.
    """
    logger.info("reply_task_started")
    result = asyncio.run(_check_replies())
    logger.info("reply_task_complete", **result)
    return result
