"""`POST /api/previews` (mục 7): VPS tra cứu listing thật, không giao dịch.
ID do server cấp — local chỉ gửi ID gợi ý, không dùng hash DOM làm bằng chứng.
"""
from __future__ import annotations

from dataclasses import asdict
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from backend.adapters.factory import get_adapter
from backend.api.deps import get_current_device, get_db
from backend.config import settings
from backend.db.models import Account, Device, Preview
from backend.domain.errors import ForbiddenError, NotFoundError, UnsupportedListingTypeError
from backend.domain.schemas import PreviewRequest, PreviewResponse

router = APIRouter(tags=["previews"])


@router.post("/api/previews", response_model=PreviewResponse, status_code=200)
def create_preview(
    body: PreviewRequest,
    db: Session = Depends(get_db),
    device: Device = Depends(get_current_device),
):
    account = db.get(Account, body.account_id)
    if account is None or account.owner_id != device.owner_id:
        raise ForbiddenError("Tài khoản không thuộc chủ sở hữu này")

    adapter = get_adapter()
    listing = adapter.get_listing(body.auction_id)
    if not listing.found:
        raise NotFoundError("Không tìm thấy listing trên Yahoo")
    if not listing.supported:
        raise UnsupportedListingTypeError(
            f"Loại listing '{listing.listing_type}' chưa được hỗ trợ/kiểm thử"
        )

    now = datetime.now(timezone.utc)
    snapshot = asdict(listing)
    if snapshot.get("ends_at") is not None:
        snapshot["ends_at"] = listing.ends_at.isoformat()

    preview = Preview(
        owner_id=device.owner_id,
        account_id=account.id,
        auction_id=body.auction_id,
        action=body.action,
        listing_snapshot=snapshot,
        fetched_at=now,
        expires_at=now + timedelta(seconds=settings.preview_ttl_seconds),
    )
    db.add(preview)
    db.commit()
    db.refresh(preview)

    return PreviewResponse(
        preview_id=preview.id,
        owner_id=preview.owner_id,
        account_id=preview.account_id,
        auction_id=preview.auction_id,
        action=preview.action,
        listing_snapshot=preview.listing_snapshot,
        data_version=preview.data_version,
        fetched_at=preview.fetched_at.isoformat(),
        expires_at=preview.expires_at.isoformat(),
    )
