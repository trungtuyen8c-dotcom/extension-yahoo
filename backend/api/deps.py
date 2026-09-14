from __future__ import annotations

from typing import Optional

import hmac
from datetime import datetime, timezone

from fastapi import Depends, Header
from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.config import settings
from backend.db.models import Device
from backend.db.session import get_db
from backend.domain.auth import hash_token
from backend.domain.errors import ForbiddenError, UnauthorizedError

__all__ = ["get_db", "get_current_device", "require_scope", "require_admin_session"]


def get_current_device(
    authorization: Optional[str] = Header(default=None), db: Session = Depends(get_db)
) -> Device:
    if not authorization or not authorization.lower().startswith("bearer "):
        raise UnauthorizedError("Thiếu bearer token")
    raw_token = authorization.split(" ", 1)[1].strip()
    if not raw_token:
        raise UnauthorizedError("Token rỗng")
    token_hash = hash_token(raw_token)
    device = db.execute(select(Device).where(Device.token_hash == token_hash)).scalar_one_or_none()
    if device is None:
        raise UnauthorizedError("Token không hợp lệ")
    if not device.is_valid(datetime.now(timezone.utc)):
        raise UnauthorizedError("Token đã hết hạn hoặc bị thu hồi")
    return device


def require_scope(action: str):
    def _dependency(device: Device = Depends(get_current_device)) -> Device:
        if action not in (device.scope or []):
            raise ForbiddenError(f"Thiết bị không có quyền cho hành động {action}")
        return device

    return _dependency


def require_admin_session(x_admin_secret: Optional[str] = Header(default=None)) -> None:
    """Placeholder cho session dashboard (mục 5.2): tách biệt token extension.

    Đây KHÔNG phải hệ thống đăng nhập admin đầy đủ — chỉ đủ để tách biệt
    endpoint tạo mã ghép cặp khỏi API bearer-token của extension. Trước khi
    vận hành thật, thay bằng session có đăng nhập theo mục 5.2.
    """
    if not x_admin_secret or not hmac.compare_digest(x_admin_secret, settings.dashboard_session_secret):
        raise UnauthorizedError("Thiếu hoặc sai phiên quản trị")
