from __future__ import annotations

import pytest

from backend.db.models import Command
from backend.domain.status import apply_transition, can_transition


def test_valid_transition_chain():
    assert can_transition("QUEUED", "PRECHECK")
    assert can_transition("PRECHECK", "SUBMITTING")
    assert can_transition("SUBMITTING", "SUCCEEDED")


def test_invalid_transition_rejected():
    assert not can_transition("SUCCEEDED", "QUEUED")
    assert not can_transition("CANCELLED", "SUBMITTING")
    assert not can_transition("QUEUED", "SUCCEEDED")


def test_apply_transition_writes_event(db_session):
    command = Command(
        owner_id="o",
        account_id="a",
        auction_id="x",
        intent_id="i",
        idempotency_key="k",
        payload_hash="h",
        payload={},
        action="PLACE_BID",
        preview_id="p",
        expires_at=__import__("datetime").datetime.now(__import__("datetime").timezone.utc),
    )
    db_session.add(command)
    db_session.commit()

    apply_transition(db_session, command, to_status="PRECHECK", phase="PRECHECK", actor="worker")
    db_session.commit()

    assert command.command_status == "PRECHECK"
    assert len(command.events) == 1
    assert command.events[0].from_status == "QUEUED"
    assert command.events[0].to_status == "PRECHECK"


def test_apply_invalid_transition_raises(db_session):
    command = Command(
        owner_id="o",
        account_id="a",
        auction_id="x",
        intent_id="i2",
        idempotency_key="k2",
        payload_hash="h",
        payload={},
        action="PLACE_BID",
        preview_id="p",
        command_status="SUCCEEDED",
        expires_at=__import__("datetime").datetime.now(__import__("datetime").timezone.utc),
    )
    db_session.add(command)
    db_session.commit()

    with pytest.raises(ValueError):
        apply_transition(db_session, command, to_status="QUEUED", phase="X", actor="worker")
