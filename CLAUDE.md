# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Tổng quan

Extension trình duyệt (local) + backend/worker (VPS Nhật) để đặt giá/mua trên
`auctions.yahoo.co.jp`. Local chỉ xem hàng và xác nhận lệnh; VPS mới là nơi
thực thi giao dịch bằng tài khoản đã đăng nhập (Playwright + Chromium).

Đặc tả đầy đủ, nguồn sự thật duy nhất: [local-gui-lenh-vps-thuc-hien (1) (1).md](local-gui-lenh-vps-thuc-hien%20(1)%20(1).md) —
đọc trước khi code. Các mục quan trọng nhất để tra cứu nhanh:

- Mục 3: kiến trúc & đường đi dữ liệu (Local → VPS FastAPI → PostgreSQL, Worker riêng biệt với HTTP request).
- Mục 7–9: hợp đồng API, ngân sách/thời gian, chống gửi trùng, máy trạng thái.
- Mục 10–11: adapter Yahoo, phiên đăng nhập, quy tắc quyền hạn mua/thanh toán.
- Mục 13: cấu trúc mã nguồn dự kiến (bảng đường dẫn).
- Mục 15–16: bảng kiểm thử bắt buộc và các cổng nghiệm thu A–E — coi một tính
  năng là "xong" chỉ khi qua các cổng này.

## Trạng thái hiện tại

`extension/`, `backend/worker/`, `migrations/versions/`, `tests/`, `deploy/`,
`docs/` tồn tại nhưng phần lớn còn trống — đây là bộ khung mục 13, chưa phải
sản phẩm chạy được. Cụ thể những gì **đã có**:

- `backend/config.py`, `backend/db/` (models + session), `backend/domain/`
  (schemas, status machine, idempotency, budget, auth, errors),
  `backend/adapters/` (interface `base.py`, `factory.py`, `mock/`, khung
  `yahoo/` chưa triển khai), `backend/api/` (deps + routes: commands,
  pairing, previews).

Những gì **chưa có** — đừng giả định chúng tồn tại:

- Không có entrypoint FastAPI (`backend/main.py` hoặc tương đương) — chưa có
  `FastAPI()` app nào include các router trong `backend/api/routes/`.
- Không có `backend/worker/` thật — thư mục rỗng, chưa có vòng lặp nhận lệnh
  (mục 9.3).
- `migrations/versions/` rỗng — chưa có Alembic env/revision nào, dù
  `alembic` đã khai trong `pyproject.toml`.
- `tests/` rỗng — chưa có test nào, dù `pyproject.toml` đã cấu hình pytest.
- `extension/` chỉ có thư mục `icons/` rỗng — chưa có manifest/content
  script/popup.
- Chưa đăng nhập Yahoo, chưa truy cập VPS, chưa đặt giá/mua/thanh toán thật.
- `backend/adapters/yahoo/adapter.py` cố tình `raise AdapterNotImplementedError`
  ở mọi hàm `submit_*` — không tự điền selector đoán mò (xem docstring đầu file).

## Lệnh thường dùng

```bash
pip install -e ".[dev]"   # cài backend + pytest/httpx
pytest                     # chạy test suite (tests/ hiện chưa có file test)
```

Chưa có lint/format tool nào được cấu hình trong repo (không có ruff/black/
mypy config) — đừng bịa lệnh lint.

## Kiến trúc backend

Luồng phụ thuộc theo lớp, từ trong ra ngoài:

```
config.py (Settings, đọc .env)
  └─ db/ (SQLAlchemy models + session)
       └─ domain/ (business rules thuần, không phụ thuộc FastAPI)
            └─ adapters/ (interface YahooAdapter + factory chọn mock/yahoo)
                 └─ api/ (FastAPI routers, chỉ orchestration + HTTP mapping)
```

- **`domain/schemas.py`**: mỗi action (`PLACE_BID`, `BUY_NOW`,
  `STORE_CHECKOUT`, `PAY_WON_ITEM`) có Pydantic model riêng, `extra="forbid"`,
  discriminated union theo `action`. Đây là hợp đồng payload lệnh — sửa ở đây
  khi thêm/đổi field của một action.
- **`domain/status.py`**: máy trạng thái `command_status` (`VALID_TRANSITIONS`)
  tách biệt hoàn toàn khỏi `auction_status`/`payment_status`; và quy tắc giải
  phóng ngân sách (`should_release_reservation`) — chỉ giải phóng khi đã xác
  minh xong nghĩa vụ nghiệp vụ, không suy đoán.
- **`domain/idempotency.py`**: hash payload sau khi loại `intent_id` và
  `expires_in_seconds` (đây là metadata của lần gửi, không phải nội dung
  nghiệp vụ) — dùng để phát hiện "cùng khóa, khác payload" → 409.
- **`domain/budget.py`**: dự trữ ngân sách (`reserve_budget`) phải nằm cùng
  transaction với việc tạo `Command` (xem `api/routes/commands.py`
  `create_command`) — flush lấy `command.id` trước, add reservation, rồi mới
  commit chung.
- **`adapters/base.py`**: interface `YahooAdapter` — mọi chi tiết
  DOM/selector Yahoo phải nằm sau interface này, không rò vào API handler
  hay worker. `adapters/factory.py` chọn implementation theo
  `settings.yahoo_adapter` (`mock` | `yahoo`).
- **`adapters/mock/adapter.py`**: dùng để test độ tin cậy (crash/retry/
  timeout/race) mà không chạm Yahoo thật — đây là công cụ kiểm thử chính cho
  đến khi adapter Yahoo qua Cổng B.
- **`api/deps.py`**: `get_current_device` xác thực bearer token (hash so
  sánh, token thô không log/lưu); `require_admin_session` là placeholder
  tách biệt endpoint tạo mã ghép cặp khỏi API bearer-token của extension —
  không phải hệ thống login admin đầy đủ (xem docstring trong file).
- **`api/routes/commands.py`**: điểm chịu trách nhiệm chống gửi trùng —
  tra `idempotency_key` rồi `intent_id` trước, ghi `Command` + dự trữ ngân
  sách cùng transaction, `db.commit()` rồi mới trả `202`. Có xử lý
  `IntegrityError` cho race hai request cùng khóa tới gần như đồng thời
  (unique constraint DB là nguồn sự thật cuối).
- **`db/models.py`**: enum trạng thái (`CommandStatus`, `AuctionStatus`,
  `PaymentStatus`, …) là enum nội bộ, **không phải** tên trường API Yahoo.
  `Command` có `UniqueConstraint` trên `(owner_id, idempotency_key)` và
  `(owner_id, intent_id)`.

## Ràng buộc cứng khi code (bắt buộc, không thương lượng)

- Không để content script/nút trên trang Yahoo tự gửi lệnh giao dịch. Mọi
  lệnh `PLACE_BID`/`BUY_NOW`/`STORE_CHECKOUT`/`PAY_WON_ITEM` phải qua
  popup/trang extension đã xác nhận.
- Local không gọi trực tiếp API đặt giá/mua của Yahoo. Chỉ VPS (Playwright +
  Chromium) thao tác trên Yahoo.
- Mỗi lệnh phải có `Idempotency-Key` + `intent_id`; commit DB trước khi trả
  `202`. Không suy đoán idempotency phía Yahoo.
- Tách riêng `command_status`, `auction_status`, `payment_status` — không suy
  ra cái này từ cái kia (ví dụ: đặt giá thành công ≠ thắng đấu giá).
- Mặc định `unknown_cost_policy=BLOCK` và `LIVE_ACTIONS_ENABLED=false` cho
  adapter chưa kiểm thử. Không trả thành công giả khi chưa cấu hình xong.
- Không log cookie, token, OTP, mật khẩu, số thẻ.
- Không tự điền selector/DOM locator đoán mò vào `adapters/yahoo/adapter.py`
  — phải khảo sát thật (mục 14 bước 1) và qua Cổng B trước.
- Xem mục 15–16 của đặc tả trước khi coi một tính năng là "xong" — có bảng
  kiểm thử bắt buộc và các cổng nghiệm thu (A–E).
