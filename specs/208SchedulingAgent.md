# Spec: Block H — Scheduling Agent

## Overview
When a buyer is high-value (lead_score > 8.0) OR explicitly requests a call, this agent checks the founder's Google Calendar, proposes 3 slots, books the chosen one, and notifies the founder. A guardrail protects the founder's calendar from low-value prospects.

## Files to create
| File | Purpose |
|---|---|
| app/services/calendar_service.py | Google Calendar OAuth + events |
| app/agents/scheduling_agent.py | Slot proposal + booking flow |
| tests/agents/test_scheduling.py | Guardrail + booking tests |

## Calendar Guardrail (CRITICAL — from blueprint)
ONLY initiate meeting booking when:
  store.lead_score > 8.0  OR  buyer explicitly requested a call
Otherwise, do NOT propose a meeting. Protects founder's time.

## Flow
1. guardrail_node → check lead_score > 8.0 or explicit request; else END
2. fetch_availability_node → read founder's Google Calendar free slots
3. propose_slots_node → draft email proposing 3 specific time slots [HITL]
4. (buyer replies picking a slot — handled via Reply Handler)
5. book_node → create Google Calendar event + Meet link
6. confirm_node → send confirmation email with the link
7. notify_node → WhatsApp alert to founder: meeting booked

## calendar_service.py
- Zero-credential OAuth (Google Workspace 1-click), tokens only
- get_free_slots(days_ahead=7) -> list of available 30-min slots
- create_event(slot, attendees, title) -> event with Google Meet link

## Acceptance Criteria
- [x] Guardrail blocks booking for lead_score <= 8.0 with no explicit request
- [x] Guardrail allows booking when buyer explicitly asks for a call
- [x] 3 real free slots proposed from the founder's calendar
- [x] Booking creates a calendar event with a Meet link
- [x] Founder notified via WhatsApp on booking
- [x] Calendar uses OAuth tokens, never passwords
