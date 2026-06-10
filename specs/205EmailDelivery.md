# Spec: Block E — Email Delivery & Domain Shield

## Overview
Send ONLY approved OutreachEmails via SendGrid (or Resend). Protect the brand's primary domain by using warmed secondary sending domains.

## Files to create
| File | Purpose |
|---|---|
| app/services/email_service.py | Send + track via SendGrid/Resend |
| app/services/domain_service.py | Secondary domain config + warming |
| app/tasks/email_tasks.py | Celery task: send approved emails |
| tests/services/test_email_service.py | Mocked send + tracking tests |

## email_service.py
async send_outreach_email(email: OutreachEmail) -> None
   → PRECONDITION: email.status == "approved" (assert — never send otherwise)
   → Send via SendGrid from the tenant's secondary sending domain
   → Set status="sent", record sent_at, message_id for reply tracking
   → Respect per-tenant daily send cap (default 100/day)

## domain_service.py (Domain Rotation & Deliverability Shield)
- Per tenant, use a secondary domain (e.g. trybrandname.com), NOT primary
- Configure SPF / DKIM / DMARC records (document the DNS values to set)
- Warming schedule: day 1 = 10 emails, ramping to 100/day over 2 weeks
- Track domain reputation; pause if bounce rate > 5%

## Celery Task (email_tasks.py)
send_approved_emails_task()
   → Runs every 15 min via Celery beat
   → Finds OutreachEmails with status="approved"
   → Sends each (respecting daily cap), updates status

## Acceptance Criteria
- [x] send_outreach_email ASSERTS status=="approved" (test the guard)
- [x] Sends from secondary domain, never the primary brand domain
- [x] Daily send cap enforced per tenant
- [x] status transitions approved → sent with sent_at + message_id
- [x] Celery task picks up approved emails and sends them
