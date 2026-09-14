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

    def get_listing(self, auction_id: str) -> ListingInfo:
        # TODO(khảo sát thật): xác minh URL pattern thật của
        # auctions.yahoo.co.jp cho một listing mẫu (mục 17) trước khi viết
        # selector đọc tên/người bán/loại listing/giá/phí/hạn (mục 10).
        raise AdapterNotImplementedError(_NOT_SURVEYED)

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
