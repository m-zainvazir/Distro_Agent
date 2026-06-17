"""Autonomy-mode HITL gating matrix (Layer 8)."""
import app.agents.hitl_gate as gate


def test_unbypassable_always_requires_approval() -> None:
    for mode in gate.AUTONOMY_MODES:
        assert gate.should_request_approval(gate.UNBYPASSABLE, mode) is True


def test_deal_requires_approval_unless_full_auto() -> None:
    assert gate.should_request_approval(gate.DEAL, gate.ASSIST) is True
    assert gate.should_request_approval(gate.DEAL, gate.SEMI_AUTO) is True
    assert gate.should_request_approval(gate.DEAL, gate.FULL_AUTO) is False


def test_routine_outreach_requires_approval_only_in_assist() -> None:
    assert gate.should_request_approval(gate.ROUTINE_OUTREACH, gate.ASSIST) is True
    assert gate.should_request_approval(gate.ROUTINE_OUTREACH, gate.SEMI_AUTO) is False
    assert gate.should_request_approval(gate.ROUTINE_OUTREACH, gate.FULL_AUTO) is False


def test_unknown_action_class_fails_safe_to_require() -> None:
    assert gate.should_request_approval("mystery", gate.FULL_AUTO) is True


def test_unknown_mode_on_deal_requires_approval() -> None:
    # Any mode that is not full_auto must still gate a deal action.
    assert gate.should_request_approval(gate.DEAL, "garbage_mode") is True


def test_request_auto_approves_without_interrupt_when_permitted(monkeypatch) -> None:
    called = {"hit": False}

    def _fake_interrupt(payload: dict) -> bool:
        called["hit"] = True
        return False

    monkeypatch.setattr(gate, "interrupt", _fake_interrupt)
    # full_auto + deal → auto-approve, interrupt must NOT be called.
    result = gate.request_human_approval(
        {"x": 1}, action_class=gate.DEAL, autonomy_mode=gate.FULL_AUTO
    )
    assert result is True
    assert called["hit"] is False


def test_request_interrupts_when_required(monkeypatch) -> None:
    seen = {"payload": None}

    def _fake_interrupt(payload: dict) -> bool:
        seen["payload"] = payload
        return True

    monkeypatch.setattr(gate, "interrupt", _fake_interrupt)
    result = gate.request_human_approval(
        {"x": 9}, action_class=gate.UNBYPASSABLE, autonomy_mode=gate.FULL_AUTO
    )
    assert result is True
    assert seen["payload"] == {"x": 9}


def test_default_call_preserves_legacy_interrupt_behavior(monkeypatch) -> None:
    fired = {"hit": False}

    def _fake_interrupt(payload: dict) -> bool:
        fired["hit"] = True
        return True

    monkeypatch.setattr(gate, "interrupt", _fake_interrupt)
    # No kwargs → unbypassable × assist → must always interrupt (pre-autonomy behavior).
    gate.request_human_approval({"legacy": True})
    assert fired["hit"] is True
