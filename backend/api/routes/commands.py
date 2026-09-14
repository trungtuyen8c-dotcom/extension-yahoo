"""`/api/commands*` (mục 7, 9.1). Đây là điểm chịu trách nhiệm chống gửi
trùng: tra khóa trùng trước, ghi lệnh + dự trữ ngân sách cùng transaction,
commit rồi mới trả `202`.
"""
from __future__ import annotations

from typing import Optional

from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, Header
from pydantic import TypeAdapter, ValidationError
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from backend.adapters.factory import get_adapter
from backend.api.deps import get_current_device, get_db
from backend.db.models import Account, Command, CommandEvent, Device, Preview
from backend.domain.budget import release_reservations_for_command, reserve_budget
from backend.domain.errors import (
    CommandNotCancellableError,
    ForbiddenError,
    IdempotencyConflictError,
    NotFoundError,
    PaymentAuthRequiredError,
    PreviewInvalidError,
    UnknownCostBlockedError,
    ValidationDomainError,
)
from backend.domain.idempotency import payload_hash
from backend.domain.schemas import CommandPayload, CommandStatusResponse
from backend.domain.status import apply_transition, should_release_reservation

router = APIRouter(tags=["commands"])

_payload_adapter: TypeAdapter = TypeAdapter(CommandPayload)


def _status_response(command: Command) -> CommandStatusResponse:
    return CommandStatusResponse(
        command_id=command.id,
        command_status=command.command_status,
        action=command.action,
        auction_status=command.auction_status,
        payment_status=command.payment_status,
        last_verified_at=command.last_verified_at.isoformat() if command.last_verified_at else None,
    )


def _get_owned_command(db: Session, command_id: str, device: Device) -> Command:
    command = db.get(Command, command_id)
    if command is None or command.owner_id != device.owner_id:
        raise NotFoundError("Không tìm thấy lệnh")
    return command


@router.post("/api/commands", response_model=CommandStatusResponse, status_code=202)
def create_command(
    body: dict,
    idempotency_key: Optional[str] = Header(default=None, alias="Idempotency-Key"),
    db: Session = Depends(get_db),
    device: Device = Depends(get_current_device),
):
    if not idempotency_key:
        raise ValidationDomainError("Thiếu header Idempotency-Key")

    try:
        payload = _payload_adapter.validate_python(body)
    except ValidationError as exc:
        raise ValidationDomainError(f"Payload không hợp lệ: {exc.errors()}") from exc

    if payload.action not in (device.scope or []):
        raise ForbiddenError(f"Thiết bị không có quyền cho hành động {payload.action}")

    owner_id = device.owner_id
    new_hash = payload_hash(body)

    existing = (
        db.query(Command)
        .filter(Command.owner_id == owner_id, Command.idempotency_key == idempotency_key)
        .one_or_none()
    )
    if existing is not None:
        if existing.payload_hash != new_hash:
            raise IdempotencyConflictError("Cùng khóa nhưng payload khác — lệnh trước không bị thay đổi")
        return _status_response(existing)

    existing_intent = (
        db.query(Command)
        .filter(Command.owner_id == owner_id, Command.intent_id == payload.intent_id)
        .one_or_none()
    )
    if existing_intent is not None:
        if existing_intent.payload_hash != new_hash:
            raise IdempotencyConflictError("Cùng khóa nhưng payload khác — lệnh trước không bị thay đổi")
        return _status_response(existing_intent)

    account = db.get(Account, payload.account_id)
    if account is None or account.owner_id != owner_id:
        raise ForbiddenError("Tài khoản không thuộc chủ sở hữu này")

    now = datetime.now(timezone.utc)
    preview = db.get(Preview, payload.preview_id)
    if preview is None or not preview.is_valid(
        owner_id=owner_id,
        account_id=payload.account_id,
        action=payload.action,
        auction_id=payload.auction_id,
        at=now,
    ):
        raise PreviewInvalidError(
            "Preview không hợp lệ, hết hạn, sai tài khoản hoặc khác action — lấy preview mới"
        )

    snapshot = preview.listing_snapshot
    if payload.unknown_cost_policy == "BLOCK" and snapshot.get("fees_fully_known") is False:
        raise UnknownCostBlockedError(
            "Chưa xác định đầy đủ phí/thuế; unknown_cost_policy=BLOCK nên dừng lại"
        )

    if payload.action == "STORE_CHECKOUT":
        payment_separable = snapshot.get("payment_separable", True)
        if not payment_separable and not payload.authorize_payment:
            raise PaymentAuthRequiredError(
                "Listing gộp mua và trả tiền; cần authorize_payment=true trước khi gửi"
            )

    command = Command(
        owner_id=owner_id,
        account_id=payload.account_id,
        auction_id=payload.auction_id,
        intent_id=payload.intent_id,
        idempotency_key=idempotency_key,
        payload_hash=new_hash,
        payload=body,
        action=payload.action,
        preview_id=payload.preview_id,
        dry_run=payload.dry_run,
        unknown_cost_policy=payload.unknown_cost_policy,
        expires_at=now + timedelta(seconds=payload.expires_in_seconds),
    )
    db.add(command)
    db.flush()  # Cần command.id trước khi tạo dự trữ ngân sách.

    reserve_budget(db, account=account, command_id=command.id, amount_jpy=payload.max_total_jpy)

    db.add(
        CommandEvent(
            command_id=command.id,
            from_status=None,
            to_status="QUEUED",
            phase="RECEIVED",
            actor="user",
            note="Lệnh nhận từ extension, đã xác nhận trong popup",
        )
    )

    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        # Race hai request cùng khóa/intent tới đồng thời (bấm nhiều lần rất
        # nhanh) — unique constraint DB là nguồn sự thật cuối cùng (mục 9.1).
        existing = (
            db.query(Command)
            .filter(Command.owner_id == owner_id, Command.idempotency_key == idempotency_key)
            .one_or_none()
        )
        if existing is not None:
            if existing.payload_hash != new_hash:
                raise IdempotencyConflictError("Cùng khóa nhưng payload khác — lệnh trước không bị thay đổi") from None
            return _status_response(existing)
        raise

    db.refresh(command)
    return _status_response(command)


@router.get("/api/commands/{command_id}", response_model=CommandStatusResponse)
def get_command(command_id: str, db: Session = Depends(get_db), device: Device = Depends(get_current_device)):
    command = _get_owned_command(db, command_id, device)
    return _status_response(command)


@router.get("/api/commands", response_model=CommandStatusResponse)
def find_command_by_intent(
    intent_id: str, db: Session = Depends(get_db), device: Device = Depends(get_current_device)
):
    command = (
        db.query(Command)
        .filter(Command.owner_id == device.owner_id, Command.intent_id == intent_id)
        .one_or_none()
    )
    if command is None:
        raise NotFoundError("Không tìm thấy lệnh cho intent_id này")
    return _status_response(command)


@router.post("/api/commands/{command_id}/cancel", response_model=CommandStatusResponse)
def cancel_command(command_id: str, db: Session = Depends(get_db), device: Device = Depends(get_current_device)):
    command = _get_owned_command(db, command_id, device)
    if command.command_status != "QUEUED":
        raise CommandNotCancellableError(
            "Chỉ hủy nguyên tử được khi lệnh còn QUEUED — worker có thể đã nhận"
        )
    apply_transition(db, command, to_status="CANCELLED", phase="CANCELLED", actor="user")
    release_reservations_for_command(db, command.id, reason="cancelled_before_worker")
    db.commit()
    db.refresh(command)
    return _status_response(command)


@router.post("/api/commands/{command_id}/resume", response_model=CommandStatusResponse)
def resume_command(command_id: str, db: Session = Depends(get_db), device: Device = Depends(get_current_device)):
    command = _get_owned_command(db, command_id, device)
    now = datetime.now(timezone.utc)

    if command.command_status != "WAITING_USER":
        raise ValidationDomainError("Chỉ resume được lệnh đang WAITING_USER")

    if now >= command.expires_at:
        # Không bỏ qua hết hạn: nếu chưa từng submit thì hết hạn thật sự chặn
        # lệnh; nếu đã submit thì hạn chỉ ngăn phần chưa thực thi (mục 8).
        if command.phase in ("SUBMITTING", "AFTER_SUBMIT"):
            apply_transition(db, command, to_status="RECONCILING", phase="RECONCILE_AFTER_EXPIRY", actor="system")
        else:
            apply_transition(db, command, to_status="EXPIRED", phase="EXPIRED", actor="system")
            release_reservations_for_command(db, command.id, reason="expired_before_submit")
        db.commit()
        db.refresh(command)
        return _status_response(command)

    # Trả về hàng đợi đúng phase trước đó; worker sẽ nhận lại bằng claim.
    command.claimed_by_worker = None
    command.claimed_at = None
    apply_transition(db, command, to_status="PRECHECK", phase=command.phase, actor="user", note="resume")
    db.commit()
    db.refresh(command)
    return _status_response(command)


@router.post("/api/commands/{command_id}/reconcile", response_model=CommandStatusResponse)
def reconcile_command(command_id: str, db: Session = Depends(get_db), device: Device = Depends(get_current_device)):
    command = _get_owned_command(db, command_id, device)
    adapter = get_adapter()
    result = adapter.reconcile(command)

    command.auction_status = result.auction_status
    command.payment_status = result.payment_status
    command.last_verified_at = datetime.now(timezone.utc)
    db.add(
        CommandEvent(
            command_id=command.id,
            from_status=command.command_status,
            to_status=command.command_status,
            phase="RECONCILE",
            actor="system",
            note=result.note,
        )
    )

    release, reason = should_release_reservation(
        command_status=command.command_status,
        action=command.action,
        auction_status=command.auction_status,
        payment_status=command.payment_status,
    )
    if release:
        release_reservations_for_command(db, command.id, reason=reason)

    db.commit()
    db.refresh(command)
    return _status_response(command)
