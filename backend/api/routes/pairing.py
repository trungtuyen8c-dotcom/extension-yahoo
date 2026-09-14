"""`POST /api/pairing/exchange` (mục 7) + endpoint admin tạo mã ghép cặp
(mục 5.2). Dashboard tạo mã một lần, hết hạn ngắn; extension đổi mã lấy
token giới hạn theo scope.
"""
from __future__ import annotations

from typing import Optional

from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends
from pydantic import BaseModel, ConfigDict
from sqlalchemy.orm import Session

from backend.api.deps import get_db, require_admin_session
from backend.config import settings
from backend.db.models import Device, PairingCode
from backend.domain.auth import generate_pairing_code, generate_raw_token, hash_pairing_code, hash_token
from backend.domain.errors import UnauthorizedError
from backend.domain.schemas import PairingExchangeRequest, PairingExchangeResponse

router = APIRouter(tags=["pairing"])


class CreatePairingCodeRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    owner_id: str
    account_id: Optional[str] = None
    scope: list[str] = []


class CreatePairingCodeResponse(BaseModel):
    pairing_code: str
    expires_at: str


@router.post("/api/admin/pairing/codes", response_model=CreatePairingCodeResponse)
def create_pairing_code(
    body: CreatePairingCodeRequest,
    db: Session = Depends(get_db),
    _admin=Depends(require_admin_session),
):
    code = generate_pairing_code()
    expires_at = datetime.now(timezone.utc) + timedelta(seconds=settings.pairing_code_ttl_seconds)
    row = PairingCode(
        owner_id=body.owner_id,
        account_id=body.account_id,
        code_hash=hash_pairing_code(code),
        scope=body.scope,
        max_attempts=settings.pairing_max_attempts,
        expires_at=expires_at,
    )
    db.add(row)
    db.commit()
    return CreatePairingCodeResponse(pairing_code=code, expires_at=expires_at.isoformat())


@router.post("/api/pairing/exchange", response_model=PairingExchangeResponse)
def exchange_pairing_code(body: PairingExchangeRequest, db: Session = Depends(get_db)):
    now = datetime.now(timezone.utc)
    code_hash = hash_pairing_code(body.pairing_code)
    row = db.query(PairingCode).filter(PairingCode.code_hash == code_hash).one_or_none()
    # Không tiết lộ việc mã có tồn tại hay không qua thông điệp lỗi khác nhau.
    if row is None or row.consumed_at is not None or row.expires_at <= now or row.attempts >= row.max_attempts:
        if row is not None and row.consumed_at is None and row.expires_at > now:
            row.attempts += 1
            db.commit()
        raise UnauthorizedError("Mã ghép cặp không hợp lệ hoặc đã hết hạn")

    row.consumed_at = now
    device_token = generate_raw_token()
    device = Device(
        owner_id=row.owner_id,
        account_id=row.account_id,
        token_hash=hash_token(device_token),
        scope=row.scope,
        label=body.device_label,
        expires_at=now + timedelta(days=settings.device_token_ttl_days),
    )
    db.add(device)
    db.commit()

    return PairingExchangeResponse(
        device_token=device_token,
        owner_id=device.owner_id,
        account_id=device.account_id,
        scope=device.scope,
        expires_at=device.expires_at.isoformat(),
    )
