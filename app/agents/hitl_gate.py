"""Shared HITL interrupt helper.

Calling ``request_human_approval(payload)`` inside a LangGraph node pauses
the graph and returns the payload to the caller as an Interrupt object. The
graph resumes when the caller invokes it with ``Command(resume=value)``.

The graph must be compiled with a checkpointer for state to survive the pause.
"""
from langgraph.types import interrupt


def request_human_approval(payload: dict) -> bool:
    """Pause the current graph node and wait for a human decision.

    Returns the resume value (True = approved, False = rejected) once the
    graph is resumed by the webhook handler.
    """
    return interrupt(payload)  # type: ignore[return-value]
