# Ghim version cụ thể sau khi kiểm thử (mục 6) — không dùng `latest` khi
# triển khai lại.
FROM python:3.11-slim-bookworm

RUN groupadd --system yahoo-vps && useradd --system --gid yahoo-vps --create-home yahoo-vps

WORKDIR /app
COPY pyproject.toml ./
COPY backend ./backend
COPY migrations ./migrations
COPY alembic.ini ./

RUN pip install --no-cache-dir -e .

# Chromium/Playwright chỉ cần trong image worker; nếu tách image
# api/worker riêng để giảm kích thước, bỏ dòng dưới khỏi image api.
RUN python -m playwright install --with-deps chromium

USER yahoo-vps

EXPOSE 8000
