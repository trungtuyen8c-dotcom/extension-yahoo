"""Giao diện adapter Yahoo (mục 10). Không đặt selector website vào API
handler hay worker — mọi chi tiết DOM/luồng Yahoo nằm sau giao diện này.
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Optional


class AdapterNotImplementedError(Exception):
    """Luồng chưa được kiểm thử với tài khoản/listing thật. Không đoán selector."""


@dataclass
class SessionStatus:
    account_id: str
    is_logged_in: bool
    verified_identity: Optional[str]
    can_execute: bool
    note: str = ""


@dataclass
class ListingInfo:
    auction_id: str
    found: bool
    listing_type: str  # AUCTION | FIXED_PRICE | STORE_FIXED_PRICE | UNKNOWN
    supported: bool
    title: str = ""
    seller: str = ""
    seller_is_store: bool = False
    current_price_jpy: Optional[int] = None
    buy_now_price_jpy: Optional[int] = None
    known_fees_jpy: int = 0
    fees_fully_known: bool = False
    currency: str = "JPY"
    ends_at: Optional[datetime] = None
    is_closed: bool = False
    # False nếu luồng checkout của listing này gộp mua và trả tiền, không
    # tách được thành hai bước xin quyền riêng (mục 11).
    payment_separable: bool = True
    raw_evidence: dict = field(default_factory=dict)


@dataclass
class PrepareResult:
    reached_boundary: bool
    requires_user: bool
    reason: str = ""
    evidence: dict = field(default_factory=dict)


@dataclass
class SubmitResult:
    command_status: str  # SUCCEEDED | FAILED | UNKNOWN | WAITING_USER
    auction_status: Optional[str] = None
    payment_status: Optional[str] = None
    trade_ref: Optional[str] = None
    amount_jpy: Optional[int] = None
    evidence: dict = field(default_factory=dict)
    note: str = ""


@dataclass
class ReconcileResult:
    auction_status: str
    payment_status: str
    trade_ref: Optional[str] = None
    evidence: dict = field(default_factory=dict)
    note: str = ""


class YahooAdapter(ABC):
    """Mỗi hàm tương ứng một trách nhiệm ở mục 10. `command` là đối tượng
    domain (không phải ORM row) mang các trường cần thiết cho adapter.
    """

    @abstractmethod
    def check_session(self, account_id: str) -> SessionStatus: ...

    @abstractmethod
    def get_listing(self, auction_id: str) -> ListingInfo: ...

    @abstractmethod
    def prepare(self, *, action: str, command: Any) -> PrepareResult: ...

    @abstractmethod
    def submit_bid(self, command: Any) -> SubmitResult: ...

    @abstractmethod
    def submit_buy_now(self, command: Any) -> SubmitResult: ...

    @abstractmethod
    def submit_store_checkout(self, command: Any) -> SubmitResult: ...

    @abstractmethod
    def submit_payment(self, command: Any) -> SubmitResult: ...

    @abstractmethod
    def reconcile(self, command: Any) -> ReconcileResult: ...
