# Runbook

## 0. Trạng thái hiện tại — đọc trước

Đây là bản dựng khung theo lộ trình mục 14 bước 1–2 của đặc tả
(`local-gui-lenh-vps-thuc-hien (1) (1).md`): **nền tảng (extension + API +
database + worker) chạy được với adapter mock, đã có test tự động cho
idempotency/ngân sách/máy trạng thái/crash-recovery.**

**Chưa làm, không được coi là đã xong:**

- Chưa khảo sát URL/DOM thật của `auctions.yahoo.co.jp` — `backend/adapters/yahoo/adapter.py`
  cố tình raise `AdapterNotImplementedError` ở mọi hàm thao tác.
- Chưa cài lên VPS thật, chưa mở tunnel thật, chưa đăng nhập Yahoo thật.
- Chưa đặt giá, mua hay thanh toán thật. `LIVE_ACTIONS_ENABLED=false` theo
  mặc định và phải giữ vậy cho tới khi qua Cổng B với listing/account thật.
- Extension chưa được load thử trong Chrome thật, chưa xác minh
  `content.js` khớp URL Yahoo thật (mẫu ID trong đó **chưa xác minh**).
- Chưa chạy migration lên PostgreSQL thật (chỉ đã kiểm chứng trên SQLite
  cục bộ khi phát triển).

Xem mục 15–16 của đặc tả gốc để biết bảng kiểm thử và cổng nghiệm thu đầy
đủ. Phần "Đã kiểm thử / chưa kiểm thử" ở cuối file này liệt kê chi tiết.

## 1. Cài đặt phát triển local (chạy trên máy bạn, không phải VPS)

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -e .
pip install pytest httpx  # dev

cp .env.example .env      # sửa DEVICE_TOKEN_PEPPER, DASHBOARD_SESSION_SECRET

# Test đơn vị + tích hợp (dùng SQLite in-memory, không cần Postgres)
pytest -q
```

Yêu cầu Python **>= 3.10** để chạy `backend/` (dự án dùng cú pháp kiểu
`X | None`). Máy dùng để soạn thảo lần đầu chỉ có Python 3.9 nên các union
type được viết bằng `typing.Optional` để tương thích — vẫn nên triển khai
thật trên Python 3.11+ (ghim version cụ thể, xem `deploy/Dockerfile`).

## 2. Cài đặt VPS

1. Tạo user không phải root (`yahoo-vps`), SSH key, xác minh host key.
2. Cài PostgreSQL (volume bền vững, backup định kỳ — chưa cấu hình trong
   repo này, cần làm theo hạ tầng VPS thật).
3. Chọn systemd (`deploy/systemd/*.service`) hoặc Docker Compose
   (`deploy/docker-compose.yml`). Cả hai đều bind API vào
   `127.0.0.1:8000`, không publish database ra Internet.
4. Chạy migration: `alembic upgrade head` (với `DATABASE_URL` trỏ Postgres
   thật).
5. Cài Playwright + Chromium trên VPS bằng user không phải root, giữ
   sandbox: `python -m playwright install --with-deps chromium`.
6. Đăng nhập Yahoo lần đầu **trong browser trên VPS** (không copy cookie
   từ local) — cần một phiên có giao diện qua kênh riêng (mục 10), chưa có
   sẵn trong repo vì phụ thuộc cách bạn truy cập VPS (VNC nội bộ, X11
   forward, hay công cụ khác đã đánh giá an toàn).

## 3. Mở tunnel và ghép cặp thiết bị

```bash
VPS_USER=deploy VPS_IP=203.0.113.10 ./deploy/tunnel.sh
```

Sau đó trên VPS (qua API, tạm thời bằng curl — dashboard đầy đủ chưa xây):

```bash
curl -X POST http://127.0.0.1:8000/api/admin/pairing/codes \
  -H "X-Admin-Secret: $DASHBOARD_SESSION_SECRET" \
  -H "Content-Type: application/json" \
  -d '{"owner_id":"ban","account_id":"<account_id đã tạo trong bảng accounts>","scope":["PLACE_BID","BUY_NOW"]}'
```

Lấy `pairing_code` trả về, nhập vào extension (mục 5.2 dưới). Mã hết hạn
theo `PAIRING_CODE_TTL_SECONDS` (mặc định 300s) và dùng một lần.

> `require_admin_session` hiện chỉ so khớp một secret tĩnh
> (`DASHBOARD_SESSION_SECRET`) — đây là **placeholder**, không phải hệ
> thống đăng nhập dashboard đầy đủ theo mục 5.2. Thay bằng session có đăng
> nhập thật trước khi vận hành cho nhiều người dùng.

## 4. Cài extension

1. Mở `chrome://extensions`, bật Developer mode.
2. "Load unpacked" → chọn thư mục `extension/`.
3. Mở popup, dán `pairing_code`.
4. Extension gọi `POST /api/pairing/exchange` qua tunnel, nhận token và
   lưu vào `chrome.storage.session` (mất khi đóng trình duyệt — phải ghép
   cặp lại, đúng thiết kế mục 5.2).

Extension **chưa** có content script tự động chèn nút trên trang Yahoo
(xem lý do trong `extension/content.js` — chưa xác minh URL/DOM thật). Việc
dò ID listing hiện chỉ chạy khi người dùng mở popup (dùng `activeTab`).

## 5. Chạy dry-run đầu tiên

Với `YAHOO_ADAPTER=mock` (mặc định), mọi preview/lệnh chạy qua
`backend/adapters/mock/adapter.py` — không chạm Yahoo thật. Dùng để tập
luyện toàn bộ luồng UI trước khi có adapter thật.

Khi đã khảo sát xong URL/DOM thật (mục 17 của đặc tả gốc: cần một URL
listing mẫu, biết loại listing ưu tiên...), triển khai các hàm còn thiếu
trong `backend/adapters/yahoo/adapter.py`, rồi:

1. Giữ `LIVE_ACTIONS_ENABLED=false`, `YAHOO_ADAPTER=yahoo`.
2. Chạy `check_session` + `get_listing` thật, xác nhận đúng tài khoản/dữ
   liệu (Cổng B, mục 16).
3. Gửi lệnh với `dry_run=true` — `prepare()` phải dừng trước ranh giới đặt
   giá/tạo giao dịch/giữ tiền.
4. Chỉ sau khi qua Cổng B mới bật `LIVE_ACTIONS_ENABLED=true` cho đúng
   account/loại listing đã kiểm thử, và chỉ người dùng chủ động xác nhận
   một hành động thật cụ thể (Cổng C).

## 6. Xử lý lệnh `UNKNOWN`

Worker không tự gửi lại khi không đủ bằng chứng (mục 9.3). Cách xử lý:

```bash
curl -X POST http://127.0.0.1:18000/api/commands/<id>/reconcile \
  -H "Authorization: Bearer <device_token>"
```

Endpoint này chỉ đọc, không tạo giao dịch mới. Nếu Yahoo không cho đủ bằng
chứng phân biệt, kiểm tra thủ công qua browser VPS rồi ghi quyết định
(hiện chưa có UI ghi log quyết định thủ công — cần bổ sung ở lớp dashboard
khi xây tiếp phần "Giao diện quản trị" của mục 3 đặc tả).

## 7. Thu hồi thiết bị

Chưa có endpoint DELETE riêng; thu hồi bằng cách set `revoked_at` trực
tiếp trên bảng `devices` (SQL) cho tới khi có endpoint quản trị chuyên
dụng. `Device.is_valid()` kiểm tra `revoked_at` ở mọi request.

## 8. Backup / restore

Chưa có script backup/restore trong repo này — cần thêm theo hạ tầng VPS
thật (`pg_dump`/snapshot volume). **Trước khi phục hồi backup cũ vào môi
trường live:** tạm dừng nhận lệnh mới, đối soát toàn bộ lệnh `UNKNOWN` và
đang mở trước khi cho worker chạy lại (mục 12).

## 9. Đã kiểm thử / chưa kiểm thử (theo yêu cầu Cổng E)

| Hạng mục | Trạng thái |
| --- | --- |
| Idempotency (trùng khóa, trùng intent, race) | Đã kiểm thử tự động (mock/SQLite) |
| Ngân sách: dự trữ/giải phóng theo mục 8 | Đã kiểm thử tự động (mock/SQLite) |
| Máy trạng thái `command_status` | Đã kiểm thử tự động (mock/SQLite) |
| Crash-recovery (`SUBMITTING` → `RECONCILING`) | Đã kiểm thử tự động (mock/SQLite) |
| PLACE_BID trên mock adapter | Đã kiểm thử tự động |
| BUY_NOW trên mock adapter | Đã kiểm thử tự động |
| STORE_CHECKOUT, PAY_WON_ITEM | Có schema + adapter mock, **chưa có test end-to-end riêng** |
| Migration trên PostgreSQL thật | **Chưa** (mới chạy trên SQLite) |
| Extension trong Chrome thật | **Chưa cài/chưa test tay** |
| `check_session`/`get_listing` Yahoo thật | **Chưa** — raise `AdapterNotImplementedError` |
| `submit_bid`/`submit_buy_now`/`submit_store_checkout`/`submit_payment` Yahoo thật | **Chưa** — raise `AdapterNotImplementedError` |
| Đăng nhập Yahoo trên VPS thật | **Chưa** |
| Bất kỳ giao dịch thật (đặt giá/mua/trả tiền) | **Chưa, không được thực hiện cho tới khi qua Cổng B/C** |

## 10. Việc cần làm tiếp theo (ưu tiên đề xuất)

1. Khảo sát: một URL listing PLACE_BID thật + một URL BUY_NOW thật (mục 17
   đặc tả gốc), xác nhận pattern trong `content.js` và viết
   `get_listing`/`check_session` thật trong `backend/adapters/yahoo/adapter.py`.
2. Load thử extension trong Chrome thật với adapter mock, xác nhận toàn bộ
   UX mục 4 hoạt động trơn tru trước khi đụng Yahoo thật.
3. Cài Postgres thật trên VPS, chạy `alembic upgrade head`, kiểm tra lại
   migration (mới autogenerate trên SQLite).
4. Viết `submit_bid` thật, dừng ở dry-run (Cổng B) trước khi bật live cho
   PLACE_BID.
5. Dashboard quản trị đầy đủ (đăng nhập thật, xem hàng đợi/tuổi lệnh/nhịp
   worker/ngân sách đang giữ, nút tạm dừng) — hiện chỉ có endpoint tạo mã
   ghép cặp tối thiểu.
