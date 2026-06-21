"""Alembic migration graph sanity — single linear head, no DB required."""
from __future__ import annotations

from pathlib import Path

from alembic.config import Config
from alembic.script import ScriptDirectory

_ALEMBIC_INI = str(Path(__file__).resolve().parents[1] / "alembic.ini")


def _script() -> ScriptDirectory:
    return ScriptDirectory.from_config(Config(_ALEMBIC_INI))


def test_single_head() -> None:
    # A branching migration graph (multiple heads) cannot be auto-upgraded.
    assert len(_script().get_heads()) == 1


def test_head_revision_chains_from_previous() -> None:
    script = _script()
    (head,) = script.get_heads()
    assert head == "b2c3d4e5f6a7"
    assert script.get_revision(head).down_revision == "a1f2b3c4d5e6"


def test_full_chain_walks_to_base() -> None:
    # Walking from head to base must not raise (proves the chain is unbroken).
    script = _script()
    (head,) = script.get_heads()
    revs = list(script.walk_revisions(base="base", head=head))
    assert revs[-1].down_revision is None  # reaches the initial migration
