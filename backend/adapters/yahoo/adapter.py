"""Adapter Yahoo thật (mục 10, 13). CHƯA ĐƯỢC KIỂM THỬ với tài khoản hoặc
VPS thật — đây là khung cắm Playwright, không phải luồng đã xác minh.

Mọi hàm `submit_*` cố tình raise `AdapterNotImplementedError` cho tới khi:
1. Đã khảo sát domain/DOM thật của từng loại listing (mục 5.1, 14 bước 1).
2. Đã có locator ngữ nghĩa/selector ổn định được kiểm thử, không phải suy
   đoán từ tài liệu hướng dẫn (mục 10).
3. Đã qua Cổng B (đọc + dry-run) cho đúng loại listing đó (mục 16).

Không tự điền selector đoán mò vào đây — làm vậy vi phạm ràng buộc "không
thử selector dự phòng bằng cách bấm hàng loạt nút có khả năng tạo giao dịch".
"""
from __future__ import annotations

import json
import re
import urllib.error
import urllib.request
from datetime import datetime
from typing import Optional

from backend.adapters.base import (
    AdapterNotImplementedError,
    ListingInfo,
    PrepareResult,
    ReconcileResult,
    SessionStatus,
    SubmitResult,
    YahooAdapter,
)
from backend.config import settings

_NOT_SURVEYED = (
    "Luồng Yahoo thật chưa được khảo sát/kiểm thử. Xem mục 14 bước 1 và mục "
    "17 (URL listing mẫu, loại listing ưu tiên) trước khi triển khai hàm này."
)

# Khảo sát thật ngày 2026-09-14 trên https://auctions.yahoo.co.jp/jp/auction/g1237444582
# (listing đấu giá thường, không có giá mua ngay đã bật). Trang là Next.js
# SSR, dữ liệu đầy đủ nằm trong <script id="__NEXT_DATA__"> kể cả khi không
# đăng nhập — dùng JSON này thay vì đoán selector CSS/DOM (ổn định hơn).
_NEXT_DATA_RE = re.compile(
    r'<script id="__NEXT_DATA__" type="application/json">(.*?)</script>', re.S
)
_ITEM_URL_TEMPLATE = "https://auctions.yahoo.co.jp/jp/auction/{auction_id}"
_HTTP_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/124.0 Safari/537.36"
    )
}


class YahooBrowserAdapter(YahooAdapter):
    """Playwright + Chromium trên VPS (mục 6, 10). `profile_dir` phải là
    profile đã đăng nhập thật trên VPS, không copy cookie từ local (mục 10).
    """

    def __init__(self, *, profile_dir: Optional[str] = None, headless: Optional[bool] = None) -> None:
        self.profile_dir = profile_dir or settings.yahoo_playwright_profile_dir
        self.headless = settings.yahoo_adapter_headless if headless is None else headless
        self.allowed_nav_domains = set(settings.allowed_nav_domains)
        self._context = None  # Playwright BrowserContext, khởi tạo lười.

    def _require_live_enabled(self) -> None:
        if not settings.live_actions_enabled:
            raise AdapterNotImplementedError(
                "LIVE_ACTIONS_ENABLED=false: adapter Yahoo thật bị khóa theo mặc định "
                "(CLAUDE.md). Không trả thành công giả."
            )

    def _ensure_context(self):
        """Mở persistent context Playwright trên profile VPS đã đăng nhập.

        TODO(khảo sát thật): xác nhận Playwright + Chromium version ghim, và
        rằng profile này chạy bằng user không phải root, giữ sandbox (mục 6).
        """
        if self._context is None:
            raise AdapterNotImplementedError(_NOT_SURVEYED)
        return self._context

    def _check_allowed_domain(self, url: str) -> None:
        from urllib.parse import urlparse

        host = urlparse(url).hostname or ""
        if not any(host == d or host.endswith(f".{d}") for d in self.allowed_nav_domains):
            raise AdapterNotImplementedError(
                f"Domain điều hướng '{host}' không nằm trong allowlist đã xác minh "
                f"({sorted(self.allowed_nav_domains)}) — mục 10."
            )

    # --- YahooAdapter ---

    def check_session(self, account_id: str) -> SessionStatus:
        # TODO(khảo sát thật): mở trang tài khoản Yahoo, đọc tên/ID hiển thị
        # để xác nhận đúng tài khoản đã cấu hình cho account_id này.
        raise AdapterNotImplementedError(_NOT_SURVEYED)

    def _fetch_item_json(self, auction_id: str) -> Optional[dict]:
        """GET trang listing công khai (không cần đăng nhập) và trích JSON
        `__NEXT_DATA__`. Trả None nếu Yahoo trả 404 (listing không tồn tại).
        """
        url = _ITEM_URL_TEMPLATE.format(auction_id=auction_id)
        self._check_allowed_domain(url)
        request = urllib.request.Request(url, headers=_HTTP_HEADERS)
        try:
            with urllib.request.urlopen(request, timeout=15) as resp:
                html = resp.read().decode("utf-8", errors="replace")
        except urllib.error.HTTPError as exc:
            if exc.code == 404:
                return None
            raise
        match = _NEXT_DATA_RE.search(html)
        if match is None:
            return None
        return json.loads(match.group(1))

    def get_listing(self, auction_id: str) -> ListingInfo:
        next_data = self._fetch_item_json(auction_id)
        if next_data is None:
            return ListingInfo(auction_id=auction_id, found=False, listing_type="UNKNOWN", supported=False)

        try:
            item = next_data["props"]["pageProps"]["initialState"]["item"]["detail"]["item"]
        except (KeyError, TypeError):
            # Cấu trúc trang đã đổi so với lần khảo sát — không đoán, chặn lại.
            return ListingInfo(
                auction_id=auction_id,
                found=False,
                listing_type="UNKNOWN",
                supported=False,
                raw_evidence={"note": "Cau truc __NEXT_DATA__ khac voi khao sat, chua ho tro"},
            )

        real_auction_id = item.get("auctionId")
        if real_auction_id != auction_id:
            return ListingInfo(auction_id=auction_id, found=False, listing_type="UNKNOWN", supported=False)

        is_flea_market = bool(item.get("isFleaMarket"))
        listing_type = "FIXED_PRICE" if is_flea_market else "AUCTION"
        # Chỉ chắc chắn hỗ trợ loại đã khảo sát thật (AUCTION không kèm
        # フリマ). FIXED_PRICE/STORE_FIXED_PRICE chưa có listing mẫu để xác
        # nhận cấu trúc JSON tương ứng.
        supported = not is_flea_market

        featured_price = item.get("featuredPrice") or 0

        seller = item.get("seller") or {}
        ends_at: Optional[datetime] = None
        end_time_raw = item.get("endTime")
        if end_time_raw:
            ends_at = datetime.fromisoformat(end_time_raw)

        status = item.get("status")

        return ListingInfo(
            auction_id=auction_id,
            found=True,
            listing_type=listing_type,
            supported=supported,
            title=item.get("title", ""),
            seller=seller.get("displayName") or seller.get("aucUserId", ""),
            seller_is_store=bool(seller.get("isStore")),
            current_price_jpy=item.get("price"),
            buy_now_price_jpy=featured_price or None,
            # Phí/thuế người mua (ship, YPayment,...) chưa được tính gộp
            # thành 1 con số đáng tin — để unknown_cost_policy=BLOCK chặn
            # lại thay vì đoán, đúng ràng buộc cứng trong CLAUDE.md.
            known_fees_jpy=0,
            fees_fully_known=False,
            currency="JPY",
            ends_at=ends_at,
            is_closed=status is not None and status != "open",
            payment_separable=True,
            raw_evidence={
                "source": "next_data_json",
                "url": _ITEM_URL_TEMPLATE.format(auction_id=auction_id),
                "auctionId": real_auction_id,
                "price": item.get("price"),
                "bids": item.get("bids"),
                "status": status,
                "endTime": end_time_raw,
            },
        )

    def prepare(self, *, action: str, command) -> PrepareResult:
        self._require_live_enabled()
        raise AdapterNotImplementedError(_NOT_SURVEYED)

    def submit_bid(self, command) -> SubmitResult:
        self._require_live_enabled()
        raise AdapterNotImplementedError(_NOT_SURVEYED)

    def submit_buy_now(self, command) -> SubmitResult:
        self._require_live_enabled()
        raise AdapterNotImplementedError(_NOT_SURVEYED)

    def submit_store_checkout(self, command) -> SubmitResult:
        self._require_live_enabled()
        raise AdapterNotImplementedError(_NOT_SURVEYED)

    def submit_payment(self, command) -> SubmitResult:
        self._require_live_enabled()
        raise AdapterNotImplementedError(_NOT_SURVEYED)

    def reconcile(self, command) -> ReconcileResult:
        # Đối soát chỉ đọc — vẫn cần selector thật, nhưng không bị chặn bởi
        # LIVE_ACTIONS_ENABLED vì không tạo giao dịch mới.
        raise AdapterNotImplementedError(_NOT_SURVEYED)
