# Runbook

## 0. Trạng thái hiện tại — đọc trước

Đây là bản dựng khung theo lộ trình mục 14 bước 1–2 của đặc tả
(`local-gui-lenh-vps-thuc-hien (1) (1).md`): **nền tảng (extension + API +
database + worker) chạy được với adapter mock, đã có test tự động cho
idempotency/ngân sách/máy trạng thái/crash-recovery.**

**Đã xác minh bằng chạy thật (không chỉ đọc code):**

- Migration `alembic upgrade head` đã chạy thành công trên PostgreSQL 16
  thật (container tạm), đủ 11 bảng, và `commands`/`budget_reservations`
  đã xác nhận foreign key được PostgreSQL enforce đúng (phát hiện qua đó:
  test suite ban đầu dùng SQLite không bật FK nên che mất vài chỗ test
  tạo dữ liệu thiếu tham chiếu hợp lệ — đã bật `PRAGMA foreign_keys=ON`
  trong `tests/conftest.py` và sửa các fixture liên quan).
- Luồng API đầy đủ (pairing → preview → tạo lệnh → idempotent replay →
  tra trạng thái) đã chạy thật qua HTTP nhắm vào PostgreSQL thật, không
  chỉ qua TestClient với SQLite.
- Worker (`claim_next_command` dùng `FOR UPDATE SKIP LOCKED` thật, không
  phải nhánh fallback của SQLite) đã chạy thật trên PostgreSQL, xử lý một
  lệnh `PLACE_BID` từ `QUEUED` tới `SUCCEEDED` đúng.
- **Extension đã được nạp thật vào Chromium (Playwright + Chrome for
  Testing) dưới dạng unpacked extension, không phải chỉ đọc code**: ghép
  cặp, xem trước, gửi lệnh dry-run, theo dõi trạng thái, đóng/mở lại popup
  để khôi phục lệnh từ storage — toàn bộ chạy đúng qua `background.js`
  thật gọi API thật. Việc này phát hiện và đã sửa một lỗi thật trong
  `extension/background.js`: kiểm tra sender cũ (`!sender.tab`) sai logic
  — một trang extension mở dưới dạng tab (không chỉ content script trên
  trang lạ) cũng có `sender.tab`, khiến message bị từ chối nhầm. Đã đổi
  sang kiểm tra `sender.url` thuộc đúng origin `chrome-extension://<id>/`.

**Đã triển khai lên VPS thật** (không phải hướng dẫn lý thuyết nữa):

- VPS: `103.166.184.140` — **dùng chung với production của dự án
  `orderhangnhat`** (đã có postgres/redis/minio/nginx/grafana riêng chạy
  trên đó). Đã xác nhận với chủ dự án trước khi cài. Ubuntu 24.04, 2 vCPU,
  3.8GB RAM (không swap), ~3.3GB đĩa trống sau khi cài — khá chật, cân
  nhắc kỹ trước khi cài thêm gì nặng (đặc biệt Chromium).
- User vận hành: `yahoo-vps` (không phải root), SSH alias cục bộ
  `yahoojp-vps` (key `~/.ssh/id_ed25519_yahoojp_vps`). `yahoo-vps` chỉ có
  sudo giới hạn (`/etc/sudoers.d/yahoo-vps`) để `start/stop/restart/status`
  đúng 2 service `yahoo-vps-api`/`yahoo-vps-worker` — không có quyền root
  khác. Dùng `sudo -n` (non-interactive) khi gọi qua SSH không có tty.
- Postgres: container Docker riêng `yahoo-vps-postgres`, KHÔNG dùng chung
  với postgres của orderhangnhat, volume riêng `yahoo_vps_pg_data`, chỉ
  bind `127.0.0.1:15432` (không public).
- Code deploy bằng `rsync` trực tiếp từ máy local vào
  `/home/yahoo-vps/app` (không qua GitHub trên VPS) — xem mục 11 để biết
  cách cập nhật code sau này.
- `.env` thật nằm ở `/home/yahoo-vps/app/.env` trên VPS (secrets random,
  không có trong git). `LIVE_ACTIONS_ENABLED=false`, `YAHOO_ADAPTER=mock`.
- Đã xác nhận qua tunnel SSH thật (`ssh -L 127.0.0.1:18000:127.0.0.1:8000
  yahoojp-vps`): pairing exchange, preview 404 đúng cho listing không tồn
  tại, tạo lệnh 422 đúng khi preview sai, token sai trả 401.
- **Chưa cài Playwright/Chromium trên VPS** — cố tình bỏ qua vì đĩa chật
  và adapter Yahoo thật chưa viết; cài khi nào thật sự cần.

**Chưa làm, không được coi là đã xong:**

- Chưa khảo sát URL/DOM thật của `auctions.yahoo.co.jp` — `backend/adapters/yahoo/adapter.py`
  cố tình raise `AdapterNotImplementedError` ở mọi hàm thao tác. ID trong
  `extension/content.js` vẫn là pattern **chưa xác minh** với trang thật.
- Chưa đăng nhập Yahoo thật trên VPS (chưa cần vì chưa cài Chromium).
- Chưa đặt giá, mua hay thanh toán thật. `LIVE_ACTIONS_ENABLED=false` theo
  mặc định và phải giữ vậy cho tới khi qua Cổng B với listing/account thật.
- Extension chưa được người dùng thật cài qua "Load unpacked" và bấm tay
  trong Chrome bình thường, chưa trỏ vào VPS thật qua tunnel (chỉ mới
  chạy tự động qua Playwright nhắm vào server local).

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
| STORE_CHECKOUT trên mock adapter (kể cả PAYMENT_AUTH_REQUIRED) | Đã kiểm thử tự động |
| PAY_WON_ITEM trên mock adapter | Đã kiểm thử tự động |
| Migration trên PostgreSQL thật | Đã chạy `alembic upgrade head` thật, xác nhận FK/schema |
| Worker trên PostgreSQL thật (`FOR UPDATE SKIP LOCKED` thật) | Đã kiểm thử (1 lệnh PLACE_BID end-to-end) |
| API đầy đủ qua HTTP nhắm PostgreSQL thật | Đã kiểm thử (pairing→preview→command→idempotent replay) |
| Extension nạp thật vào Chromium (Playwright, unpacked) | Đã kiểm thử tự động: ghép cặp, preview, dry-run, poll, khôi phục sau đóng/mở lại popup |
| Extension cài tay qua Chrome bình thường của người dùng | **Chưa** — mới chạy tự động, chưa có người thật bấm |
| `check_session`/`get_listing` Yahoo thật | **Chưa** — raise `AdapterNotImplementedError` |
| `submit_bid`/`submit_buy_now`/`submit_store_checkout`/`submit_payment` Yahoo thật | **Chưa** — raise `AdapterNotImplementedError` |
| Đăng nhập Yahoo trên VPS thật | **Chưa** |
| Bất kỳ giao dịch thật (đặt giá/mua/trả tiền) | **Chưa, không được thực hiện cho tới khi qua Cổng B/C** |

## 10. Việc cần làm tiếp theo (ưu tiên đề xuất)

1. Khảo sát: một URL listing PLACE_BID thật + một URL BUY_NOW thật (mục 17
   đặc tả gốc), xác nhận pattern trong `content.js` và viết
   `get_listing`/`check_session` thật trong `backend/adapters/yahoo/adapter.py`.
2. ~~Load thử extension trong Chrome thật~~ — đã chạy tự động qua
   Playwright (mục 0), nhưng nên tự tay "Load unpacked" + bấm thử một lần
   trên Chrome thường của bạn trước khi tin tưởng hoàn toàn UX.
3. ~~Cài Postgres, chạy migration~~ — đã chạy thật trên VPS
   `yahoojp-vps` (mục 0, 11); còn thiếu: cấu hình backup định kỳ cho
   volume `yahoo_vps_pg_data`, diễn tập phục hồi.
4. Mở tunnel thật (`ssh -L 127.0.0.1:18000:127.0.0.1:8000 yahoojp-vps`) và
   thử extension với VPS thật (chỉ mới test tự động nhắm server local).
5. Viết `submit_bid` thật, dừng ở dry-run (Cổng B) trước khi bật live cho
   PLACE_BID — lúc đó mới cần cài Playwright/Chromium trên VPS.
6. Dashboard quản trị đầy đủ (đăng nhập thật, xem hàng đợi/tuổi lệnh/nhịp
   worker/ngân sách đang giữ, nút tạm dừng) — hiện chỉ có endpoint tạo mã
   ghép cặp tối thiểu.

## 11. Vận hành VPS đã triển khai (`yahoojp-vps`)

```bash
# SSH (không dùng root cho việc thường ngày)
ssh yahoojp-vps

# Xem log 2 service
ssh yahoojp-vps "sudo -n journalctl -u yahoo-vps-api -n 50 --no-pager"
ssh yahoojp-vps "sudo -n journalctl -u yahoo-vps-worker -n 50 --no-pager"

# Restart sau khi đổi .env hoặc code
ssh yahoojp-vps "sudo -n systemctl restart yahoo-vps-api"
ssh yahoojp-vps "sudo -n systemctl restart yahoo-vps-worker"

# Cập nhật code (từ máy local, trong thư mục dự án)
rsync -az --delete \
  --exclude='.venv' --exclude='.git' --exclude='__pycache__' \
  --exclude='.env' --exclude='*.db' --exclude='.pytest_cache' \
  ./ yahoojp-vps:/home/yahoo-vps/app/
ssh yahoojp-vps "cd /home/yahoo-vps/app && .venv/bin/pip install -q -e . && set -a && source .env && set +a && .venv/bin/alembic upgrade head"
ssh yahoojp-vps "sudo -n systemctl restart yahoo-vps-api && sudo -n systemctl restart yahoo-vps-worker"

# Kiểm tra sức khỏe
ssh yahoojp-vps "curl -s http://127.0.0.1:8000/api/health"
```

`sudo -n` (non-interactive) bắt buộc khi gọi qua `ssh host "command"` không
có tty — `sudo` thường (không `-n`) sẽ báo "a password is required" dù
NOPASSWD đã đúng, vì không cấp phát được pty cho việc hỏi mật khẩu.

Postgres container: `docker exec -it yahoo-vps-postgres psql -U yahoo_app
yahoo_vps` (chạy lệnh này bằng root/`orderhangnhat-production`, vì
`yahoo-vps` không nằm trong docker group — cố tình, để không có quyền
tương đương root qua docker socket).

Mật khẩu Postgres và các secret khác chỉ nằm trong
`/home/yahoo-vps/app/.env` trên VPS — không có bản sao ở đâu khác, không
commit vào git. Nếu mất, tạo secret mới và cập nhật `.env` (không có cách
khôi phục secret cũ).
