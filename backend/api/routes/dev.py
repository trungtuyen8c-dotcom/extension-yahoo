"""Endpoint chỉ dùng để test thủ công khi `YAHOO_ADAPTER=mock` — seed một
listing giả vào adapter mock đang chạy trong tiến trình API (không có cách
nào khác để tác động từ bên ngoài vào adapter singleton trong process).
Không tồn tại tác dụng gì khi adapter thật được bật (trả 404), nên an toàn
để deploy kèm mà không ảnh hưởng hành vi khi `LIVE_ACTIONS_ENABLED=true`.
"""
from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Depends
from pydantic import BaseModel, ConfigDict

from backend.adapters.factory import get_adapter
from backend.adapters.mock.adapter import MockYahooAdapter
from backend.api.deps import require_admin_session
from backend.domain.errors import NotFoundError

router = APIRouter(tags=["dev"])


class SeedMockListingRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    auction_id: str
    listing_type: str = "AUCTION"
    title: str = "Mock item"
    seller: str = "mock-seller"
    seller_is_store: bool = False
    current_price_jpy: int = 1000
    buy_now_price_jpy: Optional[int] = None
    known_fees_jpy: int = 0
    fees_fully_known: bool = True
    is_closed: bool = False
    payment_separable: bool = True
    scenario: str = "SUCCESS"


@router.post("/api/dev/mock-listings", status_code=204)
def seed_mock_listing(body: SeedMockListingRequest, _admin=Depends(require_admin_session)):
    adapter = get_adapter()
    if not isinstance(adapter, MockYahooAdapter):
        raise NotFoundError("Chỉ dùng được khi YAHOO_ADAPTER=mock")
    adapter.seed_listing(
        body.auction_id,
        listing_type=body.listing_type,
        title=body.title,
        seller=body.seller,
        seller_is_store=body.seller_is_store,
        current_price_jpy=body.current_price_jpy,
        buy_now_price_jpy=body.buy_now_price_jpy,
        known_fees_jpy=body.known_fees_jpy,
        fees_fully_known=body.fees_fully_known,
        is_closed=body.is_closed,
        payment_separable=body.payment_separable,
        scenario=body.scenario,
    )
