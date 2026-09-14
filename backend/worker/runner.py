"""Máy trạng thái thực thi lệnh (mục 9.3, 10). Transaction ngắn quanh mỗi
lần ghi trạng thái; lời gọi tới adapter (có thể chờ Yahoo) nằm ngoài
transaction — đúng ràng buộc "không mở transaction database suốt thời gian
chờ website".
"""
from __future__ import annotations

from typing import Optional

import logging
import types
from datetime import datetime, timezone

from sqlalchemy.orm import Session

from backend.adapters.base import YahooAdapter
from backend.db.models import AuctionPosition, Command, CommandEvent, TradeResult, WorkerHeartbeat
from backend.domain.budget import release_reservations_for_command
from backend.domain.status import apply_transition, can_transition, should_release_reservation

logger = logging.getLogger("yahoo_vps_worker")

_SUBMIT_BY_ACTION = {
    "PLACE_BID": "submit_bid",
    "BUY_NOW": "submit_buy_now",
    "STORE_CHECKOUT": "submit_store_checkout",
    "PAY_WON_ITEM": "submit_payment",
}


def command_view(command: Command) -> types.SimpleNamespace:
    """Đối tượng nhẹ mang dữ liệu payload cho adapter — không phải ORM row,
    tránh adapter phụ thuộc trực tiếp vào schema database (mục 10)."""
    data = dict(command.payload)
    data["account_id"] = command.account_id
    data["auction_id"] = command.auction_id
    data["command_id"] = command.id
    return types.SimpleNamespace(**data)


def _log_event(db: Session, command: Command, note: str) -> None:
    db.add(
        CommandEvent(
            command_id=command.id,
            from_status=command.command_status,
            to_status=command.command_status,
            phase=command.phase,
            actor="worker",
            note=note,
        )
    )


def _finalize_release(db: Session, command: Command) -> None:
    release, reason = should_release_reservation(
        command_status=command.command_status,
        action=command.action,
        auction_status=command.auction_status,
        payment_status=command.payment_status,
    )
    if release:
        release_reservations_for_command(db, command.id, reason=reason)


def _record_trade_result(db: Session, command: Command, result) -> None:
    if result.trade_ref or result.amount_jpy is not None:
        db.add(
            TradeResult(
                command_id=command.id,
                trade_ref=result.trade_ref,
                amount_jpy=result.amount_jpy,
                payment_status=command.payment_status,
                evidence=result.evidence or {},
            )
        )


def _upsert_auction_position(db: Session, command: Command, auction_status: Optional[str]) -> None:
    if not auction_status:
        return
    pos = (
        db.query(AuctionPosition)
        .filter(AuctionPosition.account_id == command.account_id, AuctionPosition.auction_id == command.auction_id)
        .one_or_none()
    )
    if pos is None:
        pos = AuctionPosition(account_id=command.account_id, auction_id=command.auction_id)
        db.add(pos)
    pos.auction_status = auction_status
    pos.last_verified_at = datetime.now(timezone.utc)


def process_claimed_command(db: Session, command: Command, adapter: YahooAdapter) -> None:
    now = datetime.now(timezone.utc)

    if command.command_status in ("QUEUED", "PRECHECK") and now >= command.expires_at:
        apply_transition(db, command, to_status="EXPIRED", phase="EXPIRED", actor="worker")
        from backend.worker.locks import release_claim

        release_claim(db, command)
        _finalize_release(db, command)
        db.commit()
        return

    if command.command_status == "RECONCILING":
        _run_reconcile(db, command, adapter)
        return

    # Lệnh đã từng gửi tới Yahoo trước khi bị resume (mục 9.3: worker phải
    # kiểm tra lại phase/lịch sử vì người dùng có thể đã hoàn thành thao
    # tác) — đối soát trước, không submit lại mù quáng.
    if command.phase == "WAITING_USER_AFTER_SUBMIT":
        _run_reconcile(db, command, adapter)
        return

    if command.command_status == "QUEUED":
        apply_transition(db, command, to_status="PRECHECK", phase="PRECHECK", actor="worker")
        db.commit()

    session_status = adapter.check_session(command.account_id)
    if not session_status.can_execute:
        apply_transition(
            db, command, to_status="WAITING_USER", phase="LOGIN_REQUIRED", actor="worker",
            note=session_status.note or "Cần đăng nhập lại trên VPS",
        )
        from backend.worker.locks import release_claim

        release_claim(db, command)
        db.commit()
        return

    prepared = adapter.prepare(action=command.action, command=command_view(command))
    if prepared.requires_user:
        apply_transition(
            db, command, to_status="WAITING_USER", phase=prepared.reason or "WAITING_USER", actor="worker"
        )
        from backend.worker.locks import release_claim

        release_claim(db, command)
        db.commit()
        return

    if not prepared.reached_boundary:
        apply_transition(db, command, to_status="FAILED", phase=prepared.reason or "PRECHECK_FAILED", actor="worker")
        from backend.worker.locks import release_claim

        release_claim(db, command)
        _finalize_release(db, command)
        db.commit()
        return

    if command.dry_run:
        apply_transition(db, command, to_status="DRY_RUN_SUCCEEDED", phase="DRY_RUN_STOP", actor="worker")
        from backend.worker.locks import release_claim

        release_claim(db, command)
        _finalize_release(db, command)
        db.commit()
        return

    submit_method_name = _SUBMIT_BY_ACTION[command.action]
    apply_transition(db, command, to_status="SUBMITTING", phase=f"SUBMITTING:{submit_method_name}", actor="worker")
    db.commit()  # Ghi bền vững ý định submit TRƯỚC khi gọi Yahoo (mục 9.3).

    try:
        result = getattr(adapter, submit_method_name)(command_view(command))
    except Exception as exc:  # Yahoo timeout/lỗi mạng: giữ UNKNOWN, không đoán.
        logger.warning("submit_exception command_id=%s action=%s", command.id, command.action)
        apply_transition(db, command, to_status="UNKNOWN", phase="SUBMIT_EXCEPTION", actor="worker", note=str(exc))
        from backend.worker.locks import release_claim

        release_claim(db, command)
        # Không release ngân sách — chưa xác minh hết nghĩa vụ (mục 8).
        db.commit()
        return

    _apply_submit_result(db, command, result)


def _apply_submit_result(db: Session, command: Command, result) -> None:
    if result.auction_status:
        command.auction_status = result.auction_status
    if result.payment_status:
        command.payment_status = result.payment_status
    command.last_verified_at = datetime.now(timezone.utc)

    if result.command_status == "WAITING_USER":
        apply_transition(db, command, to_status="WAITING_USER", phase="WAITING_USER_AFTER_SUBMIT", actor="worker", note=result.note)
    elif result.command_status == "SUCCEEDED":
        apply_transition(db, command, to_status="SUCCEEDED", phase="DONE", actor="worker", note=result.note)
        _record_trade_result(db, command, result)
        _upsert_auction_position(db, command, result.auction_status)
    elif result.command_status == "FAILED":
        apply_transition(db, command, to_status="FAILED", phase="DONE", actor="worker", note=result.note)
        _upsert_auction_position(db, command, result.auction_status)
    else:  # UNKNOWN hoặc giá trị lạ — an toàn hơn khi coi là chưa rõ.
        apply_transition(db, command, to_status="UNKNOWN", phase="SUBMIT_RESULT_UNCLEAR", actor="worker", note=result.note)

    from backend.worker.locks import release_claim

    release_claim(db, command)
    _finalize_release(db, command)
    db.commit()


def _infer_outcome_from_reconcile(action: str, auction_status: str, payment_status: str) -> Optional[str]:
    """Trả None nếu bằng chứng chưa đủ phân biệt — giữ nguyên UNKNOWN/RECONCILING
    thay vì đoán (mục 9.3: "không đủ bằng chứng: giữ UNKNOWN")."""
    if action == "PLACE_BID":
        if auction_status in ("BID_ACCEPTED", "LEADING", "OUTBID", "WON", "LOST", "CLOSED"):
            return "SUCCEEDED"
        if auction_status == "NOT_BID":
            return "FAILED"
        return None
    if payment_status == "PAID":
        return "SUCCEEDED"
    if payment_status == "FAILED":
        return "FAILED"
    return None


def _run_reconcile(db: Session, command: Command, adapter: YahooAdapter) -> None:
    was_actively_resolving = command.command_status in ("RECONCILING", "UNKNOWN")
    if command.command_status != "RECONCILING" and can_transition(command.command_status, "RECONCILING"):
        apply_transition(db, command, to_status="RECONCILING", phase="RECONCILE_IN_PROGRESS", actor="worker")
        db.commit()

    result = adapter.reconcile(command_view(command))
    command.auction_status = result.auction_status
    command.payment_status = result.payment_status
    command.last_verified_at = datetime.now(timezone.utc)

    if was_actively_resolving:
        decided = _infer_outcome_from_reconcile(command.action, result.auction_status, result.payment_status)
        if decided is not None and can_transition(command.command_status, decided):
            apply_transition(db, command, to_status=decided, phase="RECONCILED", actor="worker", note=result.note)
        else:
            apply_transition(db, command, to_status="UNKNOWN", phase="RECONCILE_INCONCLUSIVE", actor="worker", note=result.note)
    else:
        # Lệnh đã SUCCEEDED từ trước — đây chỉ là tác vụ đọc theo dõi kết
        # quả đấu giá, không đổi command_status (mục 9.2).
        _log_event(db, command, note=f"reconcile: {result.note}")

    from backend.worker.locks import release_claim

    release_claim(db, command)
    _finalize_release(db, command)
    db.commit()


def check_no_rival_worker(db: Session, worker_id: str, *, stale_after_seconds: float) -> None:
    """Mục 9.3: "Database không thể ngăn một browser cũ tiếp tục gửi tới
    Yahoo; muốn tiếp quản phải xác minh tiến trình/browser cũ đã dừng." —
    kiểm tra tối thiểu: không có heartbeat gần đây của worker_id khác."""
    from sqlalchemy import select

    heartbeat_row = (
        db.execute(select(WorkerHeartbeat).where(WorkerHeartbeat.worker_id != worker_id))
        .scalars()
        .first()
    )
    if heartbeat_row is None:
        return
    age = (datetime.now(timezone.utc) - heartbeat_row.last_seen_at).total_seconds()
    if age < stale_after_seconds:
        raise RuntimeError(
            f"Worker khác ({heartbeat_row.worker_id}) vẫn còn heartbeat gần đây "
            f"({age:.0f}s trước) — không tự failover (mục 9.3)."
        )


def recover_on_startup(db: Session, worker_id: str) -> None:
    """Áp dụng bảng phục hồi mục 9.3 cho các lệnh còn dang dở từ tiến trình
    worker trước (đã xác nhận dừng qua `check_no_rival_worker`)."""
    now = datetime.now(timezone.utc)

    stuck = db.query(Command).filter(Command.claimed_by_worker.is_not(None)).all()
    for command in stuck:
        if command.command_status in ("QUEUED", "PRECHECK"):
            # Chưa submit — an toàn để nhận lại nếu còn hạn; hết hạn thì đóng.
            command.claimed_by_worker = None
            command.claimed_at = None
            if now >= command.expires_at:
                apply_transition(
                    db, command, to_status="EXPIRED", phase="EXPIRED", actor="system",
                    note="recover_on_startup",
                )
                release_reservations_for_command(db, command.id, reason="expired_before_submit")
        elif command.command_status == "SUBMITTING":
            # Có thể Yahoo đã nhận — chuyển đối soát, không đưa về hàng đợi mua.
            command.claimed_by_worker = None
            command.claimed_at = None
            if can_transition(command.command_status, "RECONCILING"):
                apply_transition(
                    db, command, to_status="RECONCILING", phase="RECONCILE_AFTER_CRASH",
                    actor="system", note="recover_on_startup",
                )
        else:
            command.claimed_by_worker = None
            command.claimed_at = None

    db.commit()


def heartbeat(db: Session, worker_id: str) -> None:
    row = db.get(WorkerHeartbeat, worker_id)
    if row is None:
        row = WorkerHeartbeat(worker_id=worker_id)
        db.add(row)
    row.last_seen_at = datetime.now(timezone.utc)
    db.commit()
