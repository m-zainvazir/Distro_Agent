# /run-spec — Read and Implement a Feature Specification Exactly as Written

## Steps

1. Ask: "Which spec file should I implement? (give the filename in specs/)"
2. Read the spec file thoroughly
3. Check existing code for any related patterns to follow
4. Spawn subagents if the spec has multiple independent components
5. Implement all components described in the spec
6. Run tests: make test
7. Report: list every file created/modified

## Critical Rules

- Implement EXACTLY what the spec says — no additions, no omissions
- If the spec is unclear, ask for clarification BEFORE coding
- Every new function MUST have a corresponding test