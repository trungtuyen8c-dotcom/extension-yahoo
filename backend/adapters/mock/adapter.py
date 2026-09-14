"""Adapter mô phỏng (mục 13: `backend/adapters/mock/`). Dùng cho phát triển,
kiểm thử độ tin cậy (crash/retry/timeout) mà không chạm Yahoo thật — đúng
mục 15: "Test retry/crash tài chính trên mock ... không lặp thao tác thật".
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Optional

from datetime import datetime, timezone

from backend.adapters.base import (
    ListingInfo,
    PrepareResult,
    ReconcileResult,
    SessionStatus,
    SubmitResult,
    YahooAdapter,
)

SUPPORTED_LISTING_TYPES = {"AUCTION", "FIXED_PRICE", "STORE_FIXED_PRICE"}


class MockTimeoutError(Exception):
    """Mô phỏng Yahoo timeout sau khi submit — worker phải giữ UNKNOWN."""


def _bid_key(account_id: str, auction_id: str) -> str:
    return f"{account_id}::{auction_id}"


class MockYahooAdapter(YahooAdapter):
    """`state_file` tùy chọn: khi đặt, dữ liệu seed được đọc/ghi qua một
    file JSON dùng chung thay vì chỉ giữ trong bộ nhớ tiến trình. Cần thiết
    vì API và worker chạy hai tiến trình riêng (mục 6, 9.3) nên mỗi bên có
    một instance `MockYahooAdapter` khác nhau — không có file chung thì
    `seed_listing()` gọi từ API sẽ không thấy được từ worker."""

    def __init__(self, *, state_file: Optional[str] = None) -> None:
        self._state_file = Path(state_file) if state_file else None
        self._listings: dict = {}
        self._sessions: dict = {}
        self._bid_state: dict = {}
        self._trade_counter = 0
        self._load()

    # --- Bền vững hoá tối thiểu qua file (chỉ dùng cho dev/test) ---

    def _load(self) -> None:
        if self._state_file is None or not self._state_file.exists():
            return
        try:
            data = json.loads(self._state_file.read_text())
        except (json.JSONDecodeError, OSError):
            return
        self._listings = data.get("listings", {})
        self._sessions = data.get("sessions", {})
        self._bid_state = data.get("bid_state", {})
        self._trade_counter = data.get("trade_counter", 0)

    def _save(self) -> None:
        if self._state_file is None:
            return
        payload = {
            "listings": self._listings,
            "sessions": self._sessions,
            "bid_state": self._bid_state,
            "trade_counter": self._trade_counter,
        }
        self._state_file.write_text(json.dumps(payload))

    # --- Trợ giúp kiểm thử ---

    def seed_listing(
        self,
        auction_id: str,
        *,
        listing_type: str = "AUCTION",
        title: str = "Mock item",
        seller: str = "mock-seller",
        seller_is_store: bool = False,
        current_price_jpy: int = 1000,
        buy_now_price_jpy: Optional[int] = None,
        known_fees_jpy: int = 0,
        fees_fully_known: bool = True,
        is_closed: bool = False,
        payment_separable: bool = True,
        scenario: str = "SUCCESS",
    ) -> None:
        self._load()
        self._listings[auction_id] = dict(
            listing_type=listing_type,
            title=title,
            seller=seller,
            seller_is_store=seller_is_store,
            current_price_jpy=current_price_jpy,
            buy_now_price_jpy=buy_now_price_jpy,
            known_fees_jpy=known_fees_jpy,
            fees_fully_known=fees_fully_known,
            is_closed=is_closed,
            payment_separable=payment_separable,
            scenario=scenario,
        )
        self._save()

    def set_session(self, account_id: str, *, logged_in: bool) -> None:
        self._load()
        self._sessions[account_id] = logged_in
        self._save()

    # --- YahooAdapter ---

    def check_session(self, account_id: str) -> SessionStatus:
        self._load()
        logged_in = self._sessions.get(account_id, True)
        return SessionStatus(
            account_id=account_id,
            is_logged_in=logged_in,
            verified_identity=account_id if logged_in else None,
            can_execute=logged_in,
        )

    def get_listing(self, auction_id: str) -> ListingInfo:
        self._load()
        data = self._listings.get(auction_id)
        if data is None:
            return ListingInfo(
                auction_id=auction_id, found=False, listing_type="UNKNOWN", supported=False
            )
        supported = data["listing_type"] in SUPPORTED_LISTING_TYPES and data["scenario"] != "UNSUPPORTED"
        return ListingInfo(
            auction_id=auction_id,
            found=True,
            listing_type=data["listing_type"],
            supported=supported,
            title=data["title"],
            seller=data["seller"],
            seller_is_store=data["seller_is_store"],
            current_price_jpy=data["current_price_jpy"],
            buy_now_price_jpy=data["buy_now_price_jpy"],
            known_fees_jpy=data["known_fees_jpy"],
            fees_fully_known=data["fees_fully_known"],
            is_closed=data["is_closed"],
            payment_separable=data["payment_separable"],
            raw_evidence={"scenario": data["scenario"]},
        )

    def prepare(self, *, action: str, command) -> PrepareResult:
        self._load()
        listing = self._listings.get(command.auction_id)
        if listing is None:
            return PrepareResult(reached_boundary=False, requires_user=False, reason="LISTING_NOT_FOUND")
        if listing["scenario"] == "OTP_REQUIRED":
            return PrepareResult(reached_boundary=False, requires_user=True, reason="OTP_REQUIRED")
        return PrepareResult(reached_boundary=True, requires_user=False, evidence={"checked_at": _now_iso()})

    def submit_bid(self, command) -> SubmitResult:
        self._load()
        listing = self._listings[command.auction_id]
        if listing["scenario"] == "TIMEOUT":
            raise MockTimeoutError("Yahoo không phản hồi sau khi gửi giá")
        if listing["is_closed"] or listing["scenario"] == "CLOSED":
            return SubmitResult(command_status="FAILED", auction_status="CLOSED", note="Listing đã đóng")
        self._bid_state[_bid_key(command.account_id, command.auction_id)] = {
            "max_bid_jpy": command.max_bid_jpy,
            "outbid": listing["scenario"] == "OUTBID_AFTER_ACCEPT",
        }
        self._save()
        return SubmitResult(
            command_status="SUCCEEDED",
            auction_status="BID_ACCEPTED",
            payment_status="NOT_STARTED",
            evidence={"accepted_max_bid_jpy": command.max_bid_jpy, "at": _now_iso()},
        )

    def submit_buy_now(self, command) -> SubmitResult:
        self._load()
        listing = self._listings[command.auction_id]
        if listing["scenario"] == "TIMEOUT":
            raise MockTimeoutError("Yahoo không phản hồi sau khi mua ngay")
        if listing["is_closed"] or listing["scenario"] == "CLOSED":
            return SubmitResult(command_status="FAILED", auction_status="CLOSED", note="Listing đã đóng")
        self._trade_counter += 1
        self._save()
        return SubmitResult(
            command_status="SUCCEEDED",
            auction_status="WON",
            payment_status="NOT_STARTED",
            trade_ref=f"MOCK-TRADE-{self._trade_counter}",
            evidence={"at": _now_iso()},
        )

    def submit_store_checkout(self, command) -> SubmitResult:
        self._load()
        listing = self._listings[command.auction_id]
        if listing["scenario"] == "TIMEOUT":
            raise MockTimeoutError("Yahoo không phản hồi khi checkout")
        combined_payment_only = not listing["payment_separable"]
        if combined_payment_only and not getattr(command, "authorize_payment", False):
            return SubmitResult(command_status="FAILED", note="PAYMENT_AUTH_REQUIRED")
        self._trade_counter += 1
        self._save()
        paid = combined_payment_only
        return SubmitResult(
            command_status="SUCCEEDED",
            auction_status="WON",
            payment_status="PAID" if paid else "PENDING",
            trade_ref=f"MOCK-TRADE-{self._trade_counter}",
            amount_jpy=command.max_total_jpy,
            evidence={"at": _now_iso()},
        )

    def submit_payment(self, command) -> SubmitResult:
        self._load()
        listing = self._listings.get(command.auction_id, {"scenario": "SUCCESS"})
        if listing["scenario"] == "TIMEOUT":
            raise MockTimeoutError("Yahoo không phản hồi khi thanh toán")
        if listing["scenario"] == "PAYMENT_PENDING_EXTERNAL":
            return SubmitResult(
                command_status="SUCCEEDED",
                payment_status="PENDING",
                trade_ref=command.trade_ref,
                note="Chờ bước thanh toán ngoài browser",
            )
        return SubmitResult(
            command_status="SUCCEEDED",
            payment_status="PAID",
            trade_ref=command.trade_ref,
            amount_jpy=command.max_total_jpy,
            evidence={"at": _now_iso()},
        )

    def reconcile(self, command) -> ReconcileResult:
        self._load()
        listing = self._listings.get(command.auction_id)
        bid = self._bid_state.get(_bid_key(command.account_id, command.auction_id))
        if listing is not None and bid is not None and bid.get("outbid"):
            return ReconcileResult(
                auction_status="LOST",
                payment_status="NOT_STARTED",
                note="Đối soát: bị vượt giá, đấu giá đã đóng",
            )
        if bid is not None:
            return ReconcileResult(auction_status="LEADING", payment_status="NOT_STARTED")
        return ReconcileResult(auction_status="UNKNOWN", payment_status="UNKNOWN", note="Không có dữ liệu")


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()
