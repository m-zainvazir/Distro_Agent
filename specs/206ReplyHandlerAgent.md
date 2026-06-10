# Spec: Block F — Reply Handler Agent + Follow-up Sequencer

## Overview
Reads new inbound emails via Gmail API (OAuth), classifies buyer intent, and routes each reply. Sends timed follow-ups when no reply arrives.

## Files to create
| File | Purpose |
|---|---|
| app/agents/reply_handler_agent.py | Classify + route replies |
| app/services/gmail_service.py | Read inbound via Gmail API OAuth |
| app/tasks/reply_tasks.py | Celery beat: hourly reply check + follow-ups |
| tests/agents/test_reply_handler.py | Classification tests |

## Classification (5 intents)
INTERESTED      → buyer wants more → route to Scheduling (Block H) or send info
OBJECTION       → concern re price/MOQ/shipping/terms → route to Negotiator (Block G)
NOT_INTERESTED  → mark lead lost, stop outreach
MEETING_REQUEST → buyer asks for a call → route to Scheduling (Block H)
NO_REPLY        → handled by follow-up sequencer, not the classifier

## Follow-up Sequencer (in reply_tasks.py)
- 5 days no reply → send Follow-up #1 (gentle bump) [through HITL]
- 5 more days no reply → send Follow-up #2 (final, value-add) [through HITL]
- After F/U #2 no reply → mark lead dormant, stop

## Gmail Integration (gmail_service.py)
- Zero-credential: OAuth tokens only, never passwords
- Poll for new messages in threads we started (match by message_id)
- Return parsed reply text + sender + thread_id

## Celery Task
check_replies_task() — runs hourly via Celery beat
   → Fetch new replies, classify each, route per intent
   → Trigger follow-up sequencer for stale threads

## Acceptance Criteria
- [x] Classifier correctly labels all 5 intents (test each)
- [x] OBJECTION routes to Negotiator; MEETING_REQUEST to Scheduling
- [x] Follow-ups still pass through HITL (no auto-send)
- [x] Gmail uses OAuth tokens, never stores passwords
- [x] Hourly Celery task wired and idempotent (no double-processing)
