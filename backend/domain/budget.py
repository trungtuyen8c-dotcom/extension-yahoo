"""Ngân sách theo mục 8: dự trữ theo khả năng thắng tất cả lệnh đang mở, giải
phóng nguyên tử chỉ khi đã xác minh hết nghĩa vụ nghiệp vụ — không giải phóng
chỉ vì mất mạng hoặc timeout cục bộ.
"""
from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.db.models import Account, BudgetReservation, ReservationStatus
from backend.domain.errors import BudgetExceededError


def active_reservation_total(db: Session, account_id: str) -> int:
    stmt = select(BudgetReservation).where(
        BudgetReservation.account_id == account_id,
        BudgetReservation.status == ReservationStatus.ACTIVE.value,
    )
    return sum(r.reserved_jpy for r in db.execute(stmt).scalars())


def reserve_budget(
    db: Session, *, account: Account, command_id: str, amount_jpy: int
) -> BudgetReservation:
    """Kiểm tra và tạo dự trữ trong cùng transaction với việc ghi lệnh.

    Caller chịu trách nhiệm commit; hàm này chỉ add vào session để đảm bảo
    lệnh và dự trữ ngân sách cùng một transaction (mục 9.1 bước 4).
    """
    current = active_reservation_total(db, account.id)
    if current + amount_jpy > account.budget_limit_jpy:
        raise BudgetExceededError(
            f"Vượt hạn mức tài khoản: đã giữ {current} JPY, cần thêm {amount_jpy} JPY, "
            f"hạn mức {account.budget_limit_jpy} JPY",
        )
    reservation = BudgetReservation(
        account_id=account.id, command_id=command_id, reserved_jpy=amount_jpy
    )
    db.add(reservation)
    return reservation


def release_reservations_for_command(db: Session, command_id: str, *, reason: str) -> None:
    from datetime import datetime, timezone

    stmt = select(BudgetReservation).where(
        BudgetReservation.command_id == command_id,
        BudgetReservation.status == ReservationStatus.ACTIVE.value,
    )
    for reservation in db.execute(stmt).scalars():
        reservation.status = ReservationStatus.RELEASED.value
        reservation.released_at = datetime.now(timezone.utc)
        reservation.release_reason = reason
