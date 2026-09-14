"""`GET /api/health` (mục 7): sức khỏe API, database, worker. Không xác
thực bearer — chỉ dùng cho kiểm tra hạ tầng qua loopback/tunnel."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy import select, text
from sqlalchemy.orm import Session

from backend.api.deps import get_db
from backend.config import settings
from backend.db.models import WorkerHeartbeat

router = APIRouter(tags=["health"])


class HealthResponse(BaseModel):
    status: str
    database: str
    worker: str
    live_actions_enabled: bool
    yahoo_adapter: str


@router.get("/api/health", response_model=HealthResponse)
def health(db: Session = Depends(get_db)):
    try:
        db.execute(text("SELECT 1"))
        database_ok = True
    except Exception:
        database_ok = False

    worker_status = "unknown"
    if database_ok:
        heartbeat = db.execute(select(WorkerHeartbeat)).scalars().first()
        if heartbeat is None:
            worker_status = "no_heartbeat"
        else:
            stale_after = timedelta(seconds=settings.worker_heartbeat_seconds * 3)
            worker_status = (
                "ok"
                if datetime.now(timezone.utc) - heartbeat.last_seen_at < stale_after
                else "stale"
            )

    overall = "ok" if database_ok and worker_status == "ok" else "degraded"
    return HealthResponse(
        status=overall,
        database="ok" if database_ok else "error",
        worker=worker_status,
        live_actions_enabled=settings.live_actions_enabled,
        yahoo_adapter=settings.yahoo_adapter,
    )
