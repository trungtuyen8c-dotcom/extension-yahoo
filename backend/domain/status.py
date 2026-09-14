"""Máy trạng thái lệnh (mục 9.2) và quy tắc giải phóng ngân sách (mục 8).

Tách biệt hoàn toàn `command_status` / `auction_status` / `payment_status`
theo ràng buộc CLAUDE.md — không suy cái này ra cái kia.
"""
from __future__ import annotations

from typing import Optional

from datetime import datetime, timezone

from sqlalchemy.orm import Session

from backend.db.models import Command, CommandEvent

# Cạnh hợp lệ của máy trạng thái command_status. UNKNOWN có thể tới từ hầu hết
# trạng thái đang xử lý vì "không đủ bằng chứng" có thể xảy ra bất cứ lúc nào
# sau khi đã bắt đầu thao tác.
VALID_TRANSITIONS: dict[str, set[str]] = {
    "QUEUED": {"PRECHECK", "CANCELLED", "EXPIRED"},
    "PRECHECK": {"WAITING_USER", "SUBMITTING", "DRY_RUN_SUCCEEDED", "FAILED", "EXPIRED", "UNKNOWN"},
    "WAITING_USER": {"PRECHECK", "SUBMITTING", "FAILED", "UNKNOWN"},
    "SUBMITTING": {"RECONCILING", "SUCCEEDED", "FAILED", "UNKNOWN"},
    "RECONCILING": {"SUCCEEDED", "FAILED", "UNKNOWN", "RECONCILING"},
    "UNKNOWN": {"RECONCILING", "SUCCEEDED", "FAILED", "UNKNOWN"},
    # Trạng thái cuối: không có cạnh đi ra.
    "SUCCEEDED": set(),
    "DRY_RUN_SUCCEEDED": set(),
    "FAILED": set(),
    "CANCELLED": set(),
    "EXPIRED": set(),
}


def can_transition(from_status: str, to_status: str) -> bool:
    if from_status == to_status:
        return True
    return to_status in VALID_TRANSITIONS.get(from_status, set())


def apply_transition(
    db: Session,
    command: Command,
    *,
    to_status: str,
    phase: str,
    actor: str,
    note: str = "",
) -> None:
    from_status = command.command_status
    if not can_transition(from_status, to_status):
        raise ValueError(f"Chuyển trạng thái không hợp lệ: {from_status} -> {to_status}")
    command.command_status = to_status
    command.phase = phase
    db.add(
        CommandEvent(
            command_id=command.id,
            from_status=from_status,
            to_status=to_status,
            phase=phase,
            actor=actor,
            note=note,
        )
    )


def touch_verified(command: Command, *, at: Optional[datetime] = None) -> None:
    command.last_verified_at = at or datetime.now(timezone.utc)


# --- Quy tắc giải phóng ngân sách (mục 8) ---

_NO_OBLIGATION_STATUSES = {"CANCELLED", "EXPIRED", "FAILED", "DRY_RUN_SUCCEEDED"}
_BID_RESOLVED_AUCTION_STATUSES = {"WON", "LOST", "CLOSED"}
_PAYMENT_RESOLVED_STATUSES = {"PAID", "FAILED"}


def should_release_reservation(
    *, command_status: str, action: str, auction_status: str, payment_status: str
) -> tuple[bool, str]:
    """True nếu nghĩa vụ tiềm năng đã được xác minh giải quyết xong.

    `UNKNOWN` không bao giờ tự giải phóng — phải đối soát trước.
    """
    if command_status == "UNKNOWN":
        return False, ""
    if command_status in _NO_OBLIGATION_STATUSES:
        return True, f"command_status={command_status}: chưa từng phát sinh nghĩa vụ"
    if command_status != "SUCCEEDED":
        return False, ""

    if action == "PLACE_BID":
        if auction_status in _BID_RESOLVED_AUCTION_STATUSES:
            return True, f"auction_status={auction_status}: đấu giá đã kết thúc"
        return False, ""

    # BUY_NOW / STORE_CHECKOUT / PAY_WON_ITEM: nghĩa vụ là tiền phải trả.
    if payment_status in _PAYMENT_RESOLVED_STATUSES:
        return True, f"payment_status={payment_status}: đã xác định kết quả thanh toán"
    return False, ""
