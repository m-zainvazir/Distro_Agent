# Spec: Block G — Negotiator Agent

## Overview
When a reply is classified OBJECTION, this agent parses the specific objection, drafts a counter-offer strictly within the brand's wholesale rulebook, and routes it through the HITL gate. Out-of-rulebook requests escalate to the founder instead of auto-countering.

## Files to create
| File | Purpose |
|---|---|
| app/models/rulebook.py | WholesaleRulebook model (per tenant) |
| app/agents/negotiator_agent.py | Parse objection + draft counter |
| tests/agents/test_negotiator.py | Rulebook boundary tests |

## WholesaleRulebook (per tenant)
- min_order_quantity: int
- wholesale_discount_max_pct: float   # e.g. 50% off retail max
- net_payment_days_max: int           # e.g. Net 30 max
- free_shipping_threshold: float
- non_negotiables: list[str]          # e.g. ["no consignment"]

## Nodes
1. parse_objection_node → identify type: PRICE | MOQ | SHIPPING | NET_TERMS | OTHER
2. check_rulebook_node → is the buyer's ask within rulebook limits?
3. route_node:
     within limits  → draft_counter_node
     outside limits → escalate_node (notify founder, no auto-counter)
4. draft_counter_node → Claude drafts a counter within limits, cites rulebook
5. hitl_approval_node → SAME shared HITL gate (founder approves via WhatsApp)
6. finalize_node → on approval, queue counter-offer email (status=approved)

## Critical Rules
- NEVER draft a counter that violates the rulebook
- Out-of-rulebook → escalate, never auto-decide
- Every counter routes through HITL — no exceptions

## Acceptance Criteria
- [x] rulebook.py — per-tenant WholesaleRulebook model
- [x] Objection parser handles PRICE / MOQ / SHIPPING / NET_TERMS
- [x] Counter-offers never violate rulebook limits
- [x] Out-of-rulebook asks escalate to founder (no auto-counter)
- [x] Non-negotiables trigger escalation
- [x] Every counter routes through shared HITL gate
- [x] Boundary tests prove escalation behavior
