# /review-agent — Perform a Complete Quality Review of a LangGraph Agent

## Checklist to Verify

- [ ] All state fields have proper TypedDict types
- [ ] All nodes are async functions
- [ ] Error states are handled (agent doesn't crash on API failure)
- [ ] LangSmith tracing is configured
- [ ] Tests cover happy path, error path, empty data edge case
- [ ] No hardcoded API keys or model names
- [ ] Multi-tenant: all DB queries filter by tenant_id
- [ ] Token usage is logged
- [ ] Cost budget per lead is respected (<$0.10 for text, <$0.50 for vision)

## Output Format

Create a report with: PASSED items, FAILED items, and suggested fixes