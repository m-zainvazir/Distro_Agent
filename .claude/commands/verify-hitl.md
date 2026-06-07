# /verify-hitl

Audit the codebase to confirm NO message can be sent without approval.

## Checks
1. Grep every email/message send call (sendgrid, whatsapp send)
2. Trace each one back through the call graph
3. Confirm each send is downstream of a passed HITL interrupt
4. Flag ANY send path that bypasses approval
5. Confirm interrupts use AsyncPostgresSaver checkpointer

## Output
Report: SAFE send paths (gated) vs UNSAFE send paths (must fix).
If any UNSAFE path exists, this is a release blocker.
