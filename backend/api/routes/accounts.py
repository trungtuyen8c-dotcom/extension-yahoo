"""`GET /api/accounts/{id}/status` (mục 7): trạng thái phiên và khả năng
thực thi đã xác minh trên VPS, cộng ngân sách đang giữ để dashboard/extension
hiển thị.
"""
from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy.orm import Session

from backend.adapters.factory import get_adapter
from backend.api.deps import get_current_device, get_db
from backend.db.models import Account, Device
from backend.domain.budget import active_reservation_total
from backend.domain.errors import ForbiddenError, NotFoundError

router = APIRouter(tags=["accounts"])


class AccountStatusResponse(BaseModel):
    account_id: str
    is_logged_in: bool
    can_execute: bool
    verified_identity: Optional[str]
    budget_limit_jpy: int
    budget_reserved_jpy: int
    note: str = ""


@router.get("/api/accounts/{account_id}/status", response_model=AccountStatusResponse)
def get_account_status(
    account_id: str, db: Session = Depends(get_db), device: Device = Depends(get_current_device)
):
    account = db.get(Account, account_id)
    if account is None:
        raise NotFoundError("Không tìm thấy tài khoản")
    if account.owner_id != device.owner_id:
        raise ForbiddenError("Tài khoản không thuộc chủ sở hữu này")

    session_status = get_adapter().check_session(account_id)
    reserved = active_reservation_total(db, account_id)

    return AccountStatusResponse(
        account_id=account_id,
        is_logged_in=session_status.is_logged_in,
        can_execute=session_status.can_execute,
        verified_identity=session_status.verified_identity,
        budget_limit_jpy=account.budget_limit_jpy,
        budget_reserved_jpy=reserved,
        note=session_status.note,
    )
