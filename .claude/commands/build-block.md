# /build-block

Implement one full Phase 2 block from spec, with verification.

## Steps
1. Ask: "Which block? (give the spec filename in specs/)"
2. Read the spec file completely
3. Spawn the appropriate subagent from .claude/agents/ if one fits
4. Implement every file listed in the spec's "Files to create" table
5. Implement every test in the spec
6. Run: make test-phase2
7. Run: make lint
8. Check off each checkbox in the spec's Implementation Checklist
9. Report: files created, tests passing, checkboxes completed

## Rules
- Implement EXACTLY what the spec says
- Respect the HITL rule and multi-tenancy rule from CLAUDE.md
- If a test fails, fix the implementation (not the test)
