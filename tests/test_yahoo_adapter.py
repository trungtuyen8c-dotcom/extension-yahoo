"""Test adapter Yahoo thật (get_listing) dùng fixture JSON lấy từ khảo sát
thật ngày 2026-09-14 trên g1237444582 (mục 14 bước 1) — không gọi mạng thật
trong test để tránh flaky/rate-limit, nhưng cấu trúc field khớp dữ liệu thật.
"""
from __future__ import annotations

from backend.adapters.yahoo.adapter import YahooBrowserAdapter

_REAL_SAMPLE_ITEM = {
    "auctionId": "g1237444582",
    "title": "未使用 イタリア製 ルーチェ LUCE by GRANT 2913 度なし リムなし メガネフレーム 眼鏡 49□17 ピンク",
    "seller": {"displayName": "coco", "aucUserId": "2b1xFQVftGhxduVRPnZENd7tyvfkz", "isStore": False},
    "price": 1250,
    "bids": 0,
    "featuredPrice": 0,
    "isFleaMarket": False,
    "status": "open",
    "endTime": "2026-09-15T21:45:44+09:00",
}

def _adapter_with_fixture(monkeypatch, item: dict = _REAL_SAMPLE_ITEM):
    adapter = YahooBrowserAdapter()
    next_data = {"props": {"pageProps": {"initialState": {"item": {"detail": {"item": item}}}}}}
    monkeypatch.setattr(adapter, "_fetch_item_json", lambda auction_id: next_data)
    return adapter


def test_get_listing_maps_real_auction_fields(monkeypatch):
    adapter = _adapter_with_fixture(monkeypatch)
    info = adapter.get_listing("g1237444582")

    assert info.found is True
    assert info.listing_type == "AUCTION"
    assert info.supported is True
    assert info.title.startswith("未使用")
    assert info.seller == "coco"
    assert info.current_price_jpy == 1250
    assert info.buy_now_price_jpy is None
    assert info.fees_fully_known is False
    assert info.is_closed is False
    assert info.ends_at is not None and info.ends_at.year == 2026


def test_get_listing_flea_market_marked_unsupported(monkeypatch):
    item = dict(_REAL_SAMPLE_ITEM, isFleaMarket=True)
    adapter = _adapter_with_fixture(monkeypatch, item)
    info = adapter.get_listing("g1237444582")

    assert info.listing_type == "FIXED_PRICE"
    assert info.supported is False


def test_get_listing_auction_id_mismatch_treated_as_not_found(monkeypatch):
    adapter = _adapter_with_fixture(monkeypatch)
    info = adapter.get_listing("g999")

    assert info.found is False


def test_get_listing_not_found_when_fetch_returns_none(monkeypatch):
    adapter = YahooBrowserAdapter()
    monkeypatch.setattr(adapter, "_fetch_item_json", lambda auction_id: None)
    info = adapter.get_listing("g1237444582")

    assert info.found is False
    assert info.listing_type == "UNKNOWN"


def test_get_listing_unexpected_structure_treated_as_not_found(monkeypatch):
    adapter = YahooBrowserAdapter()
    monkeypatch.setattr(adapter, "_fetch_item_json", lambda auction_id: {"unexpected": True})
    info = adapter.get_listing("g1237444582")

    assert info.found is False
