# Spec: Phase 2 Master Orchestration Workflow

## Overview
Wire all Phase 2 blocks (C–I) into a single LangGraph StateGraph that manages
the full outreach lifecycle for one store lead: draft → send → reply → negotiate
or schedule.

## Files
| File | Purpose |
|---|---|
| app/workflows/phase2_workflow.py | Master orchestration graph |
| tests/workflows/test_phase2_workflow.py | Phase 2 graph tests |

## Flow

```
invoke_copywriter [Block C — HITL forwarded]
    ↓ approved
dispatch_email [Block E — SendGrid]
    ↓
await_reply [INTERRUPT — Gmail poller or operator resumes]
    ↓
classify_reply [Block F — keyword scorer]
    ├─ INTERESTED    → handle_interested → END (phase=won)
    ├─ OBJECTION     → invoke_negotiator [Block G — HITL forwarded] → END
    ├─ NOT_INTERESTED → mark_lost        → END (phase=lost)
    ├─ MEETING_REQUEST → invoke_scheduler [Block H — HITL forwarded] → END
    └─ (empty reply)  → handle_no_reply  → END (phase=dormant)
    ↓ draft rejected
draft_rejected → END (phase=draft_rejected)
```

## Sub-agent invocation pattern
Each sub-agent (copywriter, negotiator, scheduler) is invoked via
`build_xxx_graph().ainvoke()` under a namespaced thread_id. HITL interrupts
from sub-graphs are forwarded up via the master `interrupt()` so the operator
sees a single unified approval stream.

## HITL Gates (ALL sends are gated)
| Send type | Gate |
|---|---|
| Outreach email | Copywriter HITL → approved → dispatch |
| Counter-offer email | Negotiator HITL → approved → finalize |
| Slot proposal email | Scheduling HITL → approved → send |
| Follow-up emails | reply_tasks HITL → pending_approval → Celery |

## State: Phase2State
```python
tenant_id: str
brand_profile: BrandProfile
store: ScoredStore
founder_name: str
email_tone: str
campaign_id: str
store_db_id: str
buyer_email: str
buyer_name: str
approved_email: OutreachEmailDraft | None
copywriter_thread_id: str
outreach_email_id: str
email_sent: bool
reply_text: str
sender_email: str
gmail_thread_id: str
reply_intent: str
negotiation_thread_id: str
scheduling_thread_id: str
meet_link: str
phase: str
follow_up_count: int
errors: list[str]
```

## Acceptance Criteria
- [ ] Graph chains all Phase 2 blocks in correct order
- [ ] HITL interrupts from sub-graphs forwarded to caller — no auto-sends
- [ ] All intent branches (INTERESTED/OBJECTION/NOT_INTERESTED/MEETING_REQUEST/NO_REPLY) route correctly
- [ ] tenant_id flows through to every sub-agent invocation
- [ ] test_phase2_workflow.py passes (≥ 10 test cases)
- [ ] make lint passes
