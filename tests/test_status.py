from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from backend.db.models import Account, Command, Preview
from backend.domain.status import apply_transition, can_transition


def test_valid_transition_chain():
    assert can_transition("QUEUED", "PRECHECK")
    assert can_transition("PRECHECK", "SUBMITTING")
    assert can_transition("SUBMITTING", "SUCCEEDED")


def test_invalid_transition_rejected():
    assert not can_transition("SUCCEEDED", "QUEUED")
    assert not can_transition("CANCELLED", "SUBMITTING")
    assert not can_transition("QUEUED", "SUCCEEDED")


def _make_account_and_preview(db_session):
    account = Account(owner_id="o", yahoo_account_label="l", playwright_profile_ref="p", budget_limit_jpy=10_000)
    db_session.add(account)
    db_session.flush()
    preview = Preview(
        owner_id="o",
        account_id=account.id,
        auction_id="x",
        action="PLACE_BID",
        listing_snapshot={},
        expires_at=datetime.now(timezone.utc) + timedelta(seconds=300),
    )
    db_session.add(preview)
    db_session.flush()
    return account, preview


def test_apply_transition_writes_event(db_session):
    account, preview = _make_account_and_preview(db_session)
    command = Command(
        owner_id="o",
        account_id=account.id,
        auction_id="x",
        intent_id="i",
        idempotency_key="k",
        payload_hash="h",
        payload={},
        action="PLACE_BID",
        preview_id=preview.id,
        expires_at=datetime.now(timezone.utc),
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
    account, preview = _make_account_and_preview(db_session)
    command = Command(
        owner_id="o",
        account_id=account.id,
        auction_id="x",
        intent_id="i2",
        idempotency_key="k2",
        payload_hash="h",
        payload={},
        action="PLACE_BID",
        preview_id=preview.id,
        command_status="SUCCEEDED",
        expires_at=datetime.now(timezone.utc),
    )
    db_session.add(command)
    db_session.commit()

    with pytest.raises(ValueError):
        apply_transition(db_session, command, to_status="QUEUED", phase="X", actor="worker")
