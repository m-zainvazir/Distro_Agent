from langgraph.types import interrupt


def request_human_approval(payload: dict) -> bool:
    return interrupt(payload)  # type: ignore[return-value]
