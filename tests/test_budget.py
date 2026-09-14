from __future__ import annotations

import pytest

from backend.db.models import Account
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


def test_reserve_within_limit(db_session):
    account = _make_account(db_session, budget_limit_jpy=10_000)
    reservation = reserve_budget(db_session, account=account, command_id="cmd-1", amount_jpy=5_000)
    db_session.commit()
    assert reservation.reserved_jpy == 5_000
    assert active_reservation_total(db_session, account.id) == 5_000


def test_reserve_exceeding_limit_raises(db_session):
    account = _make_account(db_session, budget_limit_jpy=10_000)
    reserve_budget(db_session, account=account, command_id="cmd-1", amount_jpy=7_000)
    db_session.commit()
    with pytest.raises(BudgetExceededError):
        reserve_budget(db_session, account=account, command_id="cmd-2", amount_jpy=4_000)


def test_release_reservation_frees_budget(db_session):
    account = _make_account(db_session, budget_limit_jpy=10_000)
    reserve_budget(db_session, account=account, command_id="cmd-1", amount_jpy=6_000)
    db_session.commit()

    release_reservations_for_command(db_session, "cmd-1", reason="test")
    db_session.commit()

    assert active_reservation_total(db_session, account.id) == 0
    # Sau khi giải phóng, có thể dự trữ lại toàn bộ hạn mức.
    reserve_budget(db_session, account=account, command_id="cmd-2", amount_jpy=10_000)


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
