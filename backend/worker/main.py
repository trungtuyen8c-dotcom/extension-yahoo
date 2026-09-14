"""Tiến trình worker chủ động (mục 6, 9.3): supervisor (systemd) khởi động
lại khi crash; tự đối soát trước khi nhận lệnh mua mới sau khi lên lại."""
from __future__ import annotations

from typing import Optional

import logging
import socket
import time
import uuid

from backend.adapters.factory import get_adapter
from backend.config import settings
from backend.db.session import SessionLocal
from backend.worker.locks import claim_next_command
from backend.worker.runner import check_no_rival_worker, heartbeat, process_claimed_command, recover_on_startup

logger = logging.getLogger("yahoo_vps_worker")
logging.basicConfig(level=settings.log_level)


def make_worker_id() -> str:
    return f"{socket.gethostname()}-{uuid.uuid4().hex[:8]}"


def run_forever(worker_id: Optional[str] = None) -> None:
    worker_id = worker_id or make_worker_id()
    adapter = get_adapter()

    with SessionLocal() as db:
        check_no_rival_worker(db, worker_id, stale_after_seconds=settings.worker_heartbeat_seconds * 3)
        recover_on_startup(db, worker_id)
        heartbeat(db, worker_id)

    logger.info("worker_started worker_id=%s adapter=%s live=%s", worker_id, settings.yahoo_adapter, settings.live_actions_enabled)

    last_heartbeat = 0.0
    while True:
        now = time.monotonic()
        if now - last_heartbeat >= settings.worker_heartbeat_seconds:
            with SessionLocal() as db:
                heartbeat(db, worker_id)
            last_heartbeat = now

        with SessionLocal() as db:
            command = claim_next_command(db, worker_id)
            if command is None:
                time.sleep(settings.worker_poll_interval_seconds)
                continue
            try:
                process_claimed_command(db, command, adapter)
            except Exception:
                logger.exception("worker_process_error command_id=%s", command.id)
                db.rollback()


if __name__ == "__main__":
    run_forever()
