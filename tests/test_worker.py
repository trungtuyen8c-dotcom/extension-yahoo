from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone

from backend.db.models import Account, Command
from backend.domain.budget import active_reservation_total, reserve_budget
from backend.worker.locks import claim_next_command
from backend.worker.runner import process_claimed_command, recover_on_startup


def _make_account(db_session, budget=100_000) -> Account:
    account = Account(
        owner_id="owner-1", yahoo_account_label="l", playwright_profile_ref="p", budget_limit_jpy=budget
    )
    db_session.add(account)
    db_session.commit()
    return account


def _make_command(db_session, account, *, action="PLACE_BID", auction_id="A1", dry_run=False, payload=None, expires_seconds=120, amount=1500):
    payload = payload or {
        "action": action,
        "account_id": account.id,
        "auction_id": auction_id,
        "preview_id": "prev-1",
        "max_bid_jpy": 1000,
        "max_total_jpy": amount,
        "dry_run": dry_run,
    }
    command = Command(
        owner_id=account.owner_id,
        account_id=account.id,
        auction_id=auction_id,
        intent_id=str(uuid.uuid4()),
        idempotency_key=str(uuid.uuid4()),
        payload_hash="hash",
        payload=payload,
        action=action,
        preview_id="prev-1",
        dry_run=dry_run,
        expires_at=datetime.now(timezone.utc) + timedelta(seconds=expires_seconds),
    )
    db_session.add(command)
    db_session.flush()
    reserve_budget(db_session, account=account, command_id=command.id, amount_jpy=amount)
    db_session.commit()
    return command


def test_dry_run_stops_before_submit_and_releases_budget(db_session, mock_adapter):
    account = _make_account(db_session)
    mock_adapter.seed_listing("A1")
    command = _make_command(db_session, account, dry_run=True)

    claimed = claim_next_command(db_session, "worker-1")
    assert claimed.id == command.id
    process_claimed_command(db_session, claimed, mock_adapter)

    db_session.refresh(command)
    assert command.command_status == "DRY_RUN_SUCCEEDED"
    assert active_reservation_total(db_session, account.id) == 0


def test_place_bid_success_keeps_budget_until_auction_resolved(db_session, mock_adapter):
    account = _make_account(db_session)
    mock_adapter.seed_listing("A1")
    command = _make_command(db_session, account, dry_run=False)

    claimed = claim_next_command(db_session, "worker-1")
    process_claimed_command(db_session, claimed, mock_adapter)

    db_session.refresh(command)
    assert command.command_status == "SUCCEEDED"
    assert command.auction_status == "BID_ACCEPTED"
    # Đấu giá chưa kết thúc — vẫn giữ ngân sách (mục 8).
    assert active_reservation_total(db_session, account.id) == 1500


def test_buy_now_success_records_trade(db_session, mock_adapter):
    account = _make_account(db_session)
    mock_adapter.seed_listing("A1", listing_type="FIXED_PRICE")
    command = _make_command(db_session, account, action="BUY_NOW", dry_run=False, payload={
        "action": "BUY_NOW", "account_id": account.id, "auction_id": "A1", "preview_id": "prev-1",
        "max_item_price_jpy": 1000, "max_total_jpy": 1500, "dry_run": False,
    })

    claimed = claim_next_command(db_session, "worker-1")
    process_claimed_command(db_session, claimed, mock_adapter)

    db_session.refresh(command)
    assert command.command_status == "SUCCEEDED"
    assert command.auction_status == "WON"
    assert len(command.events) >= 1


def test_yahoo_timeout_keeps_unknown_and_holds_budget(db_session, mock_adapter):
    account = _make_account(db_session)
    mock_adapter.seed_listing("A1", scenario="TIMEOUT")
    command = _make_command(db_session, account, dry_run=False)

    claimed = claim_next_command(db_session, "worker-1")
    process_claimed_command(db_session, claimed, mock_adapter)

    db_session.refresh(command)
    assert command.command_status == "UNKNOWN"
    assert active_reservation_total(db_session, account.id) == 1500


def test_closed_listing_fails_and_releases_budget(db_session, mock_adapter):
    account = _make_account(db_session)
    mock_adapter.seed_listing("A1", scenario="CLOSED", is_closed=True)
    command = _make_command(db_session, account, dry_run=False)

    claimed = claim_next_command(db_session, "worker-1")
    process_claimed_command(db_session, claimed, mock_adapter)

    db_session.refresh(command)
    assert command.command_status == "FAILED"
    assert active_reservation_total(db_session, account.id) == 0


def test_otp_required_moves_to_waiting_user(db_session, mock_adapter):
    account = _make_account(db_session)
    mock_adapter.seed_listing("A1", scenario="OTP_REQUIRED")
    command = _make_command(db_session, account, dry_run=False)

    claimed = claim_next_command(db_session, "worker-1")
    process_claimed_command(db_session, claimed, mock_adapter)

    db_session.refresh(command)
    assert command.command_status == "WAITING_USER"
    assert command.claimed_by_worker is None
    # Vẫn giữ ngân sách — chưa xác minh hết nghĩa vụ.
    assert active_reservation_total(db_session, account.id) == 1500


def test_expired_before_claim_marks_expired(db_session, mock_adapter):
    account = _make_account(db_session)
    mock_adapter.seed_listing("A1")
    command = _make_command(db_session, account, dry_run=False, expires_seconds=-10)

    claimed = claim_next_command(db_session, "worker-1")
    process_claimed_command(db_session, claimed, mock_adapter)

    db_session.refresh(command)
    assert command.command_status == "EXPIRED"
    assert active_reservation_total(db_session, account.id) == 0


def test_recover_on_startup_moves_crashed_submitting_to_reconciling(db_session, mock_adapter):
    account = _make_account(db_session)
    command = _make_command(db_session, account, dry_run=False)
    command.command_status = "SUBMITTING"
    command.phase = "SUBMITTING:submit_bid"
    command.claimed_by_worker = "dead-worker"
    db_session.commit()

    recover_on_startup(db_session, "new-worker")

    db_session.refresh(command)
    assert command.command_status == "RECONCILING"
    assert command.claimed_by_worker is None
    # Không tự failover gửi lại — vẫn giữ ngân sách cho tới khi đối soát.
    assert active_reservation_total(db_session, account.id) == 1500


def test_claim_is_exclusive_no_double_claim(db_session, mock_adapter):
    account = _make_account(db_session)
    mock_adapter.seed_listing("A1")
    _make_command(db_session, account, dry_run=True)

    first = claim_next_command(db_session, "worker-1")
    second = claim_next_command(db_session, "worker-2")
    assert first is not None
    assert second is None


_ADDRESS = {
    "recipient_name": "Nguyen Van A",
    "postal_code": "123-4567",
    "prefecture": "Tokyo",
    "city_line": "1-2-3",
    "phone": "0312345678",
}


def test_store_checkout_pays_immediately_when_combined_and_authorized(db_session, mock_adapter):
    account = _make_account(db_session)
    mock_adapter.seed_listing("S1", listing_type="STORE_FIXED_PRICE", payment_separable=False)
    command = _make_command(
        db_session, account, action="STORE_CHECKOUT", auction_id="S1", dry_run=False, amount=2000,
        payload={
            "action": "STORE_CHECKOUT", "account_id": account.id, "auction_id": "S1", "preview_id": "prev-1",
            "max_total_jpy": 2000, "address": _ADDRESS, "delivery_method": "yamato",
            "payment_method": "bank_transfer", "authorize_payment": True, "dry_run": False,
        },
    )

    claimed = claim_next_command(db_session, "worker-1")
    process_claimed_command(db_session, claimed, mock_adapter)

    db_session.refresh(command)
    assert command.command_status == "SUCCEEDED"
    assert command.payment_status == "PAID"
    # Đã trả tiền — nghĩa vụ đã hết, giải phóng dự trữ (mục 8).
    assert active_reservation_total(db_session, account.id) == 0


def test_store_checkout_fails_without_authorization_when_combined(db_session, mock_adapter):
    account = _make_account(db_session)
    mock_adapter.seed_listing("S2", listing_type="STORE_FIXED_PRICE", payment_separable=False)
    command = _make_command(
        db_session, account, action="STORE_CHECKOUT", auction_id="S2", dry_run=False, amount=2000,
        payload={
            "action": "STORE_CHECKOUT", "account_id": account.id, "auction_id": "S2", "preview_id": "prev-1",
            "max_total_jpy": 2000, "address": _ADDRESS, "delivery_method": "yamato",
            "payment_method": "bank_transfer", "authorize_payment": False, "dry_run": False,
        },
    )

    claimed = claim_next_command(db_session, "worker-1")
    process_claimed_command(db_session, claimed, mock_adapter)

    db_session.refresh(command)
    assert command.command_status == "FAILED"
    assert active_reservation_total(db_session, account.id) == 0


def test_pay_won_item_success_marks_paid(db_session, mock_adapter):
    account = _make_account(db_session)
    mock_adapter.seed_listing("A1")
    command = _make_command(
        db_session, account, action="PAY_WON_ITEM", auction_id="A1", dry_run=False, amount=1500,
        payload={
            "action": "PAY_WON_ITEM", "account_id": account.id, "auction_id": "A1", "preview_id": "prev-1",
            "trade_ref": "MOCK-TRADE-1", "max_total_jpy": 1500, "payment_method": "bank_transfer",
            "dry_run": False,
        },
    )

    claimed = claim_next_command(db_session, "worker-1")
    process_claimed_command(db_session, claimed, mock_adapter)

    db_session.refresh(command)
    assert command.command_status == "SUCCEEDED"
    assert command.payment_status == "PAID"
    assert active_reservation_total(db_session, account.id) == 0
