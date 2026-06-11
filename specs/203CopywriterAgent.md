# Spec: Block C — Copywriter Agent + HITL Gate

## Overview
A LangGraph agent that drafts a hyper-personalized outreach email per HIGH/MEDIUM store, scores its own personalization, revises if weak, then PAUSES (interrupt) for founder approval via WhatsApp before anything sends.

## Files to create
| File | Purpose |
|---|---|
| app/models/outreach.py | OutreachEmail + OutreachCampaign (if not built) |
| app/agents/copywriter_agent.py | State + nodes + graph |
| app/agents/hitl_gate.py | Shared HITL interrupt node |
| app/services/campaign_service.py | Orchestrates campaign creation |
| app/api/v1/campaigns.py | Campaign endpoints |
| tests/agents/test_copywriter_agent.py | All tests |

## State
class CopywriterState(TypedDict):
    store: ScoredStore
    brand_profile: BrandProfile
    founder_name: str
    email_tone: str              # "warm" | "professional" | "casual"
    tenant_id: str
    draft_subject_a: str
    draft_subject_b: str
    draft_body: str
    personalization_score: float
    critique_notes: str
    revision_count: int
    approved: bool | None         # set by HITL
    final_email: OutreachEmail | None

## Nodes
1. draft_node → Claude writes subject A/B + body, personalized to the store
2. critique_node → Claude scores its own draft 0-10 on personalization
   (checks: store name 2x? vibe referenced? specific products? one CTA?
    150-200 words? subject < 60 chars, no spam words?)
3. route_revision → if score < 7.0 AND revision_count < 2 → back to draft
                    else → proceed to hitl
4. hitl_approval_node → save email as status="pending_approval",
   send WhatsApp approval card, then interrupt() the graph
5. (on resume) finalize_node → if approved: status="approved" (ready to send)
                               if rejected: loop to draft with founder feedback

## HITL Implementation
- Compile graph with checkpointer = AsyncPostgresSaver
- hitl_approval_node calls whatsapp_service.send_approval_card() then
  raises a LangGraph interrupt with the email_id as the resume key
- A separate webhook (Block D) resumes the graph when founder taps Approve/Reject

## Personalization Rules (enforced in critique_node)
- Store name mentioned >= 2 times
- Store's aesthetic/vibe referenced >= 1 time (from store.why_matched)
- At least one specific product from brand_profile that fits the store
- Clear wholesale terms (MOQ, wholesale pricing tier)
- Exactly ONE call-to-action (reply to learn more)
- Body 150-200 words; subjects < 60 chars; no spam trigger words

## Acceptance Criteria
- [x] Draft mentions store name >= 2x and references its vibe
- [x] Two distinct A/B subject lines generated, both < 60 chars
- [x] personalization_score computed; weak drafts revised (max 2 loops)
- [x] Email saved as OutreachEmail status="pending_approval"
- [x] Graph PAUSES at hitl — nothing sends without approval
- [x] Rejection loops back to draft with founder feedback incorporated
- [x] Graph compiled with AsyncPostgresSaver (falls back to MemorySaver when libpq unavailable)
