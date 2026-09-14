from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone

import pytest

from backend.db.models import Account, Command, Preview
from backend.domain.budget import active_reservation_total, release_reservations_for_command, reserve_budget
from backend.domain.errors import BudgetExceededError
from backend.domain.status import should_release_reservation


def _make_account(db_session, budget_limit_jpy=10_000) -> Account:
    account = Account(
        owner_id="owner-1",
        yahoo_account_label="label",
        playwright_profile_ref="profile",
        budget_limit_jpy=budget_limit_jpy,
    )
    db_session.add(account)
    db_session.commit()
    return account


def _make_command_id(db_session, account) -> str:
    """budget_reservations.command_id là FK thật tới commands.id — tạo một
    lệnh (và preview cho nó) tối thiểu để test dự trữ ngân sách hợp lệ."""
    preview = Preview(
        owner_id=account.owner_id,
        account_id=account.id,
        auction_id="A1",
        action="PLACE_BID",
        listing_snapshot={},
        expires_at=datetime.now(timezone.utc) + timedelta(seconds=300),
    )
    db_session.add(preview)
    db_session.flush()

    command = Command(
        owner_id=account.owner_id,
        account_id=account.id,
        auction_id="A1",
        intent_id=str(uuid.uuid4()),
        idempotency_key=str(uuid.uuid4()),
        payload_hash="hash",
        payload={"action": "PLACE_BID"},
        action="PLACE_BID",
        preview_id=preview.id,
        expires_at=datetime.now(timezone.utc) + timedelta(seconds=120),
    )
    db_session.add(command)
    db_session.flush()
    return command.id


def test_reserve_within_limit(db_session):
    account = _make_account(db_session, budget_limit_jpy=10_000)
    command_id = _make_command_id(db_session, account)
    reservation = reserve_budget(db_session, account=account, command_id=command_id, amount_jpy=5_000)
    db_session.commit()
    assert reservation.reserved_jpy == 5_000
    assert active_reservation_total(db_session, account.id) == 5_000


def test_reserve_exceeding_limit_raises(db_session):
    account = _make_account(db_session, budget_limit_jpy=10_000)
    command_id_1 = _make_command_id(db_session, account)
    command_id_2 = _make_command_id(db_session, account)
    reserve_budget(db_session, account=account, command_id=command_id_1, amount_jpy=7_000)
    db_session.commit()
    with pytest.raises(BudgetExceededError):
        reserve_budget(db_session, account=account, command_id=command_id_2, amount_jpy=4_000)


def test_release_reservation_frees_budget(db_session):
    account = _make_account(db_session, budget_limit_jpy=10_000)
    command_id_1 = _make_command_id(db_session, account)
    command_id_2 = _make_command_id(db_session, account)
    reserve_budget(db_session, account=account, command_id=command_id_1, amount_jpy=6_000)
    db_session.commit()

    release_reservations_for_command(db_session, command_id_1, reason="test")
    db_session.commit()

    assert active_reservation_total(db_session, account.id) == 0
    # Sau khi giải phóng, có thể dự trữ lại toàn bộ hạn mức.
    reserve_budget(db_session, account=account, command_id=command_id_2, amount_jpy=10_000)


@pytest.mark.parametrize(
    "command_status,action,auction_status,payment_status,expected",
    [
        ("CANCELLED", "PLACE_BID", "NOT_BID", "NOT_STARTED", True),
        ("EXPIRED", "PLACE_BID", "NOT_BID", "NOT_STARTED", True),
        ("FAILED", "BUY_NOW", "NOT_BID", "NOT_STARTED", True),
        ("DRY_RUN_SUCCEEDED", "PLACE_BID", "NOT_BID", "NOT_STARTED", True),
        ("UNKNOWN", "PLACE_BID", "UNKNOWN", "UNKNOWN", False),
        ("SUCCEEDED", "PLACE_BID", "LEADING", "NOT_STARTED", False),
        ("SUCCEEDED", "PLACE_BID", "LOST", "NOT_STARTED", True),
        ("SUCCEEDED", "PLACE_BID", "WON", "NOT_STARTED", True),
        ("SUCCEEDED", "BUY_NOW", "WON", "NOT_STARTED", False),
        ("SUCCEEDED", "BUY_NOW", "WON", "PAID", True),
        ("SUCCEEDED", "PAY_WON_ITEM", "WON", "FAILED", True),
    ],
)
def test_should_release_reservation(command_status, action, auction_status, payment_status, expected):
    release, _ = should_release_reservation(
        command_status=command_status, action=action, auction_status=auction_status, payment_status=payment_status
    )
    assert release is expected
