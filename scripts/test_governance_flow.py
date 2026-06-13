"""Manual end-to-end test for the governance approval gate.

What this shows
---------------
1. A token is generated and stored in Redis.
2. Approve/Reject links are printed (and optionally sent via WhatsApp).
3. The script BLOCKS waiting for a decision.
4. You click one of the links (or curl it) from another terminal.
5. The script prints APPROVED or REJECTED and exits.

Prerequisites
-------------
* Redis running           →  docker compose up -d   (or standalone Redis on :6379)
* API server running      →  .venv\\Scripts\\uvicorn app.main:app --reload --port 8000
* This script in terminal →  .venv\\Scripts\\python -m scripts.test_governance_flow

You do NOT need WhatsApp credentials — the URLs are printed to the console.
If WhatsApp IS configured, the message also lands on the admin phone.
"""

import sys
import time

from app.core.config import settings
from app.core.governance import (
    extract_token_id,
    generate_approval_token,
    send_approval_request,
    store_token_metadata,
    wait_for_approval,
)

# ---------------------------------------------------------------------------
# Test parameters — change these to simulate any real action
# ---------------------------------------------------------------------------

ACTION = "test_governance_gate"
PAYLOAD = {
    "description": "Manual smoke test — no real changes will be made",
    "triggered_at": time.strftime("%Y-%m-%d %H:%M:%S UTC", time.gmtime()),
    "triggered_by": "scripts/test_governance_flow.py",
}
TIMEOUT_SECONDS = 120  # 2 minutes to click the link


# ---------------------------------------------------------------------------
# Run
# ---------------------------------------------------------------------------


def main() -> None:
    sep = "=" * 62

    print(f"\n{sep}")
    print("  GOVERNANCE APPROVAL GATE — MANUAL TEST")
    print(sep)

    # ── 1. Generate token ────────────────────────────────────────────────────
    token = generate_approval_token(ACTION, PAYLOAD)
    token_id = extract_token_id(token)
    print("\n[1/5] Token generated")
    print(f"      ID : {token_id}")

    # ── 2. Store in Redis ────────────────────────────────────────────────────
    print("\n[2/5] Storing token in Redis ...", end=" ", flush=True)
    try:
        store_token_metadata(token, ACTION, PAYLOAD)
        print("OK")
    except Exception as exc:
        print(f"FAILED\n\n      Error: {exc}")
        print(
            "\n      Is Redis running?\n"
            "      Fix: docker compose up -d   (starts Redis + Postgres + Qdrant)\n"
        )
        sys.exit(1)

    # ── 3. Build and display approve / reject URLs ───────────────────────────
    base = settings.base_url.rstrip("/")
    approve_url = f"{base}/api/v1/governance/approve?token={token}&action={ACTION}"
    reject_url = f"{base}/api/v1/governance/reject?token={token}&action={ACTION}"

    print("\n[3/5] Approval URLs")
    print(f"\n      APPROVE  →  {approve_url}")
    print(f"\n      REJECT   →  {reject_url}")

    # ── 4. Send WhatsApp notification (if configured) ────────────────────────
    admin_phone = settings.admin_phone or settings.whatsapp_founder_phone
    if admin_phone and settings.whatsapp_phone_number_id:
        print(f"\n[4/5] Sending WhatsApp message to {admin_phone} ...", end=" ", flush=True)
        send_approval_request(token, ACTION, PAYLOAD)
        print("Sent")
        print("      Check WhatsApp — tap Approve or Reject on your phone.")
    else:
        print("\n[4/5] WhatsApp not configured — use the URLs above.")
        print("\n      Open a NEW terminal and run one of:")
        print(f'\n        curl "{approve_url}"')
        print(f'\n        curl "{reject_url}"')
        print(
            "\n      (The API server must be running:\n"
            "       .venv\\Scripts\\uvicorn app.main:app --reload --port 8000)"
        )

    # ── 5. Block until decision ──────────────────────────────────────────────
    print(f"\n[5/5] Waiting for decision (timeout: {TIMEOUT_SECONDS}s) ...")
    print("      " + "-" * 56)

    approved = wait_for_approval(token, timeout_seconds=TIMEOUT_SECONDS)

    # ── Result ───────────────────────────────────────────────────────────────
    print(f"\n{sep}")
    if approved:
        print("  RESULT:  APPROVED  ✓")
        print("\n  In a real Celery task the action would now execute.")
    else:
        print("  RESULT:  REJECTED / TIMED OUT  ✗")
        print("\n  In a real Celery task the action would be skipped.")
    print(sep + "\n")


if __name__ == "__main__":
    main()
