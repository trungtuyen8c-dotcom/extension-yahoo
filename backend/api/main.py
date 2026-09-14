"""FastAPI app (mục 3, 6): chạy `127.0.0.1:8000` trên VPS, không public ra
Internet. Không cấu hình CORS mở — token bearer là lớp bảo vệ chính; CORS
chỉ là bổ sung (mục 5.2), và mặc định không cho origin bất kỳ.
"""
from __future__ import annotations

import logging

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from backend.api.routes import accounts, commands, dev, health, pairing, previews
from backend.domain.errors import DomainError

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("yahoo_vps_api")

app = FastAPI(title="Yahoo VPS Command API", version="0.1.0")

app.include_router(health.router)
app.include_router(pairing.router)
app.include_router(previews.router)
app.include_router(commands.router)
app.include_router(accounts.router)
app.include_router(dev.router)


@app.exception_handler(DomainError)
def handle_domain_error(request: Request, exc: DomainError) -> JSONResponse:
    # Log có command/action nếu có trong path, không log token/cookie/OTP.
    logger.info("domain_error path=%s code=%s", request.url.path, exc.code)
    return JSONResponse(status_code=exc.http_status, content={"code": exc.code, "detail": exc.message})
