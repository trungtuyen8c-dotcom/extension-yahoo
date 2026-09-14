"""Nhận lệnh bằng transaction ngắn (mục 9.3). `FOR UPDATE SKIP LOCKED` chỉ
áp dụng khi backend là PostgreSQL thật; SQLite (dùng trong test) không hỗ
trợ nên rơi về truy vấn đơn giản — vẫn đúng vì test chạy đơn luồng.
"""
from __future__ import annotations

from typing import Optional

from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.db.models import Command

_CLAIMABLE_STATUSES = ("QUEUED", "PRECHECK", "RECONCILING")


def claim_next_command(db: Session, worker_id: str) -> Optional[Command]:
    now = datetime.now(timezone.utc)
    stmt = (
        select(Command)
        .where(Command.command_status.in_(_CLAIMABLE_STATUSES), Command.claimed_by_worker.is_(None))
        .order_by(Command.created_at.asc())
        .limit(1)
    )
    if db.get_bind().dialect.name == "postgresql":
        stmt = stmt.with_for_update(skip_locked=True)

    command = db.execute(stmt).scalar_one_or_none()
    if command is None:
        return None

    command.claimed_by_worker = worker_id
    command.claimed_at = now
    db.commit()
    db.refresh(command)
    return command


def release_claim(db: Session, command: Command) -> None:
    command.claimed_by_worker = None
    command.claimed_at = None
