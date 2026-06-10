# Spec: Block D — WhatsApp Control Plane

## Overview
WhatsApp Business API integration that sends approval cards to founders and processes their Approve/Reject taps to resume paused LangGraph workflows.

## Files to create
| File | Purpose |
|---|---|
| app/services/whatsapp_service.py | Send messages + interactive buttons |
| app/api/v1/webhooks.py | POST /webhooks/whatsapp inbound handler |
| app/core/resume.py | Resume a paused graph by email_id |
| tests/services/test_whatsapp.py | Mocked send + webhook tests |

## Key Functions (whatsapp_service.py)
async send_approval_card(phone, email_preview, email_id) -> None
   → Sends WhatsApp interactive message: email preview text +
     two quick-reply buttons "✅ Approve" / "✏️ Reject"
   → Button payloads encode email_id: "approve:<id>" / "reject:<id>"

async send_deal_alert(phone, store_name, reply_summary) -> None
   → Plain notification when a buyer replies positively

async process_incoming_message(payload: dict) -> None
   → Parses the webhook, extracts button payload
   → If "approve:<id>" → mark email approved, resume graph
   → If "reject:<id>"  → ask founder for feedback, then resume with rejection

## Webhook (webhooks.py)
GET  /api/v1/webhooks/whatsapp  → verification challenge (Meta setup)
POST /api/v1/webhooks/whatsapp  → verify signature, call process_incoming_message

## Security
- Verify X-Hub-Signature-256 header against app secret before processing
- Reject unsigned/invalid payloads with 403

## Acceptance Criteria
- [ ] send_approval_card sends preview + two buttons (mocked test)
- [ ] Webhook verifies signature; rejects invalid with 403
- [ ] "approve:<id>" tap marks email approved and resumes the graph
- [ ] "reject:<id>" tap collects feedback and resumes with rejection
- [ ] GET verification challenge returns the echo token correctly
