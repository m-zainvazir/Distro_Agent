"""Shared HITL interrupt helper with per-tenant autonomy gating.

``request_human_approval(payload, action_class=..., autonomy_mode=...)`` decides
whether to pause the graph for founder approval. The pause/skip decision is
governed by the tenant's autonomy mode (Layer 8 of the blueprint) and the
action's risk class:

- ``unbypassable`` actions (final pricing, contracts) ALWAYS interrupt.
- ``deal`` actions interrupt unless the tenant is in ``full_auto``.
- ``routine_outreach`` interrupts only in ``assist`` mode.

When the gate is skipped the action is auto-approved (returns ``True``) so the
graph proceeds autonomously. Calling with no class/mode defaults to the
fail-safe (``unbypassable`` × ``assist``) — i.e. it always interrupts, exactly
matching the pre-autonomy behavior.

The graph must be compiled with a checkpointer for state to survive a pause.
"""
from langgraph.types import interrupt

from app.core.logging import logger

# --- Autonomy modes (mirror Tenant.autonomy_mode) --------------------------
ASSIST = "assist"
SEMI_AUTO = "semi_auto"
FULL_AUTO = "full_auto"
AUTONOMY_MODES = (ASSIST, SEMI_AUTO, FULL_AUTO)

# --- Action risk classes ---------------------------------------------------
ROUTINE_OUTREACH = "routine_outreach"  # cold outreach drafts (copywriter)
DEAL = "deal"                          # counter-offers, meeting proposals
UNBYPASSABLE = "unbypassable"          # final pricing, contracts — never auto
ACTION_CLASSES = (ROUTINE_OUTREACH, DEAL, UNBYPASSABLE)


def should_request_approval(action_class: str, autonomy_mode: str) -> bool:
    """Pure decision: does this action require founder approval under this mode?

    Fail-safe: an unrecognised action class always requires approval.
    """
    if action_class == UNBYPASSABLE:
        return True
    if action_class == DEAL:
        return autonomy_mode != FULL_AUTO
    if action_class == ROUTINE_OUTREACH:
        return autonomy_mode == ASSIST
    # Unknown action class → safest choice is to require approval.
    return True


def request_human_approval(
    payload: dict,
    *,
    action_class: str = UNBYPASSABLE,
    autonomy_mode: str = ASSIST,
) -> bool:
    """Pause the graph for a human decision, or auto-approve per autonomy mode.

    Returns the resume value (True = approved, False = rejected) once the graph
    is resumed by the webhook handler when the gate fires, or ``True``
    immediately when the tenant's autonomy mode permits the action to proceed
    without approval.
    """
    if should_request_approval(action_class, autonomy_mode):
        return interrupt(payload)  # type: ignore[return-value]
    logger.info(
        "hitl_auto_approved",
        action_class=action_class,
        autonomy_mode=autonomy_mode,
    )
    return True
