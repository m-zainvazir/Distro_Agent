# /new-agent — Create a New LangGraph Agent for DistroAgent

## Steps to Execute

1. Ask the user: "What is the agent name and what does it do?"
2. Read @specs/$AGENT_NAME-spec.md if it exists, or ask the user to describe the spec
3. Create the file app/agents/$AGENT_NAME.py with this structure:
   - State TypedDict definition
   - Node functions (one per logical step)
   - StateGraph definition
   - Compiled graph
4. Create tests/agents/test_$AGENT_NAME.py with:
   - At least 3 test cases (happy path, error path, edge case)
5. Register in app/workflows/registry.py
6. Update CLAUDE.md with the new agent description

## Rules

- Always use async functions
- Always add type hints
- Never hardcode model names — use settings.CLAUDE_MODEL
- Add LangSmith tracing decorator on the graph