from __future__ import annotations

from typing import Optional

import enum
import uuid
from datetime import datetime, timezone

from sqlalchemy import (
    Boolean,
    DateTime,
    ForeignKey,
    Integer,
    JSON,
    String,
    Text,
    TypeDecorator,
    UniqueConstraint,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


def _uuid() -> str:
    return str(uuid.uuid4())


def _now() -> datetime:
    return datetime.now(timezone.utc)


class UTCDateTime(TypeDecorator):
    """SQLite (dùng trong test) không giữ tzinfo qua round-trip như
    PostgreSQL — luôn gắn lại `tzinfo=UTC` khi đọc để so sánh datetime an
    toàn trên cả hai backend."""

    impl = DateTime(timezone=True)
    cache_ok = True

    def process_bind_param(self, value, dialect):
        if value is not None and value.tzinfo is None:
            value = value.replace(tzinfo=timezone.utc)
        return value

    def process_result_value(self, value, dialect):
        if value is not None and value.tzinfo is None:
            value = value.replace(tzinfo=timezone.utc)
        return value


class Base(DeclarativeBase):
    pass


# --- Enum của phần mềm nội bộ. Đây KHÔNG phải tên trường API Yahoo. ---


class ActionType(str, enum.Enum):
    PLACE_BID = "PLACE_BID"
    BUY_NOW = "BUY_NOW"
    STORE_CHECKOUT = "STORE_CHECKOUT"
    PAY_WON_ITEM = "PAY_WON_ITEM"
    REFRESH_STATUS = "REFRESH_STATUS"


class CommandStatus(str, enum.Enum):
    QUEUED = "QUEUED"
    PRECHECK = "PRECHECK"
    WAITING_USER = "WAITING_USER"
    SUBMITTING = "SUBMITTING"
    RECONCILING = "RECONCILING"
    SUCCEEDED = "SUCCEEDED"
    DRY_RUN_SUCCEEDED = "DRY_RUN_SUCCEEDED"
    FAILED = "FAILED"
    UNKNOWN = "UNKNOWN"
    CANCELLED = "CANCELLED"
    EXPIRED = "EXPIRED"


TERMINAL_COMMAND_STATUSES = {
    CommandStatus.SUCCEEDED,
    CommandStatus.DRY_RUN_SUCCEEDED,
    CommandStatus.FAILED,
    CommandStatus.CANCELLED,
    CommandStatus.EXPIRED,
}


class AuctionStatus(str, enum.Enum):
    NOT_BID = "NOT_BID"
    BID_ACCEPTED = "BID_ACCEPTED"
    LEADING = "LEADING"
    OUTBID = "OUTBID"
    WON = "WON"
    LOST = "LOST"
    CLOSED = "CLOSED"
    UNKNOWN = "UNKNOWN"


class PaymentStatus(str, enum.Enum):
    NOT_STARTED = "NOT_STARTED"
    PENDING = "PENDING"
    PAID = "PAID"
    FAILED = "FAILED"
    UNKNOWN = "UNKNOWN"


class UnknownCostPolicy(str, enum.Enum):
    BLOCK = "BLOCK"


class ReservationStatus(str, enum.Enum):
    ACTIVE = "ACTIVE"
    RELEASED = "RELEASED"


class Account(Base):
    """`accounts`: chủ sở hữu, định danh Yahoo đã xác minh, profile, hạn mức."""

    __tablename__ = "accounts"

    id: Mapped[str] = mapped_column(String(64), primary_key=True, default=_uuid)
    owner_id: Mapped[str] = mapped_column(String(128), index=True, nullable=False)
    yahoo_account_label: Mapped[str] = mapped_column(String(255), nullable=False)
    playwright_profile_ref: Mapped[str] = mapped_column(String(255), nullable=False)
    budget_limit_jpy: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    is_session_verified: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=_now)

    devices: Mapped[list["Device"]] = relationship(back_populates="account")


class Device(Base):
    """`devices`: token hash, scope, hạn và trạng thái thu hồi."""

    __tablename__ = "devices"

    id: Mapped[str] = mapped_column(String(64), primary_key=True, default=_uuid)
    owner_id: Mapped[str] = mapped_column(String(128), index=True, nullable=False)
    account_id: Mapped[Optional[str]] = mapped_column(
        String(64), ForeignKey("accounts.id"), nullable=True
    )
    token_hash: Mapped[str] = mapped_column(String(128), unique=True, nullable=False)
    # Danh sách action được phép, vd ["PLACE_BID", "BUY_NOW"].
    scope: Mapped[list] = mapped_column(JSON, default=list)
    label: Mapped[str] = mapped_column(String(255), default="")
    expires_at: Mapped[datetime] = mapped_column(UTCDateTime(), nullable=False)
    revoked_at: Mapped[Optional[datetime]] = mapped_column(UTCDateTime(), nullable=True)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=_now)

    account: Mapped[Optional[Account]] = relationship(back_populates="devices")

    def is_valid(self, at: datetime) -> bool:
        if self.revoked_at is not None:
            return False
        return at < self.expires_at


class PairingCode(Base):
    """Mã ghép cặp một lần do dashboard tạo; tiêu thụ nguyên tử qua /pairing/exchange."""

    __tablename__ = "pairing_codes"

    id: Mapped[str] = mapped_column(String(64), primary_key=True, default=_uuid)
    owner_id: Mapped[str] = mapped_column(String(128), nullable=False)
    account_id: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    code_hash: Mapped[str] = mapped_column(String(128), unique=True, nullable=False)
    scope: Mapped[list] = mapped_column(JSON, default=list)
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    max_attempts: Mapped[int] = mapped_column(Integer, default=5)
    expires_at: Mapped[datetime] = mapped_column(UTCDateTime(), nullable=False)
    consumed_at: Mapped[Optional[datetime]] = mapped_column(UTCDateTime(), nullable=True)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=_now)


class Preview(Base):
    """`previews`: dữ liệu đã kiểm chứng bởi VPS, không phải dữ liệu DOM local."""

    __tablename__ = "previews"

    id: Mapped[str] = mapped_column(String(64), primary_key=True, default=_uuid)
    owner_id: Mapped[str] = mapped_column(String(128), index=True, nullable=False)
    account_id: Mapped[str] = mapped_column(String(64), ForeignKey("accounts.id"), nullable=False)
    auction_id: Mapped[str] = mapped_column(String(255), index=True, nullable=False)
    action: Mapped[str] = mapped_column(String(32), nullable=False)
    # Ảnh chụp dữ liệu đã xác minh: tên, người bán, loại listing, giá, phí, hạn...
    listing_snapshot: Mapped[dict] = mapped_column(JSON, nullable=False)
    data_version: Mapped[int] = mapped_column(Integer, default=1)
    fetched_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=_now)
    expires_at: Mapped[datetime] = mapped_column(UTCDateTime(), nullable=False)

    def is_valid(self, *, owner_id: str, account_id: str, action: str, auction_id: str, at: datetime) -> bool:
        return (
            self.owner_id == owner_id
            and self.account_id == account_id
            and self.action == action
            and self.auction_id == auction_id
            and at < self.expires_at
        )


class Command(Base):
    """`commands`: ý định, idempotency, hash payload, phase, trạng thái, thời hạn."""

    __tablename__ = "commands"
    __table_args__ = (
        UniqueConstraint("owner_id", "idempotency_key", name="uq_commands_owner_idem_key"),
        UniqueConstraint("owner_id", "intent_id", name="uq_commands_owner_intent_id"),
    )

    id: Mapped[str] = mapped_column(String(64), primary_key=True, default=_uuid)
    owner_id: Mapped[str] = mapped_column(String(128), index=True, nullable=False)
    account_id: Mapped[str] = mapped_column(String(64), ForeignKey("accounts.id"), nullable=False)
    auction_id: Mapped[str] = mapped_column(String(255), index=True, nullable=False)

    intent_id: Mapped[str] = mapped_column(String(64), nullable=False)
    idempotency_key: Mapped[str] = mapped_column(String(255), nullable=False)
    payload_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    payload: Mapped[dict] = mapped_column(JSON, nullable=False)

    action: Mapped[str] = mapped_column(String(32), nullable=False)
    preview_id: Mapped[str] = mapped_column(String(64), ForeignKey("previews.id"), nullable=False)

    command_status: Mapped[str] = mapped_column(
        String(32), nullable=False, default=CommandStatus.QUEUED.value
    )
    phase: Mapped[str] = mapped_column(String(64), nullable=False, default="RECEIVED")
    auction_status: Mapped[str] = mapped_column(
        String(32), nullable=False, default=AuctionStatus.NOT_BID.value
    )
    payment_status: Mapped[str] = mapped_column(
        String(32), nullable=False, default=PaymentStatus.NOT_STARTED.value
    )

    dry_run: Mapped[bool] = mapped_column(Boolean, default=True)
    unknown_cost_policy: Mapped[str] = mapped_column(
        String(16), default=UnknownCostPolicy.BLOCK.value
    )

    # Lệnh nâng trần giá liên kết với lệnh trước đó (mục 8).
    supersedes_command_id: Mapped[Optional[str]] = mapped_column(
        String(64), ForeignKey("commands.id"), nullable=True
    )

    expires_at: Mapped[datetime] = mapped_column(UTCDateTime(), nullable=False)
    last_verified_at: Mapped[Optional[datetime]] = mapped_column(
        UTCDateTime(), nullable=True
    )
    claimed_by_worker: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    claimed_at: Mapped[Optional[datetime]] = mapped_column(UTCDateTime(), nullable=True)

    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=_now)
    updated_at: Mapped[datetime] = mapped_column(
        UTCDateTime(), default=_now, onupdate=_now
    )

    events: Mapped[list["CommandEvent"]] = relationship(
        back_populates="command", order_by="CommandEvent.created_at"
    )
    reservations: Mapped[list["BudgetReservation"]] = relationship(back_populates="command")


class CommandEvent(Base):
    """`command_events`: lịch sử chuyển trạng thái và người/tiến trình thực hiện."""

    __tablename__ = "command_events"

    id: Mapped[str] = mapped_column(String(64), primary_key=True, default=_uuid)
    command_id: Mapped[str] = mapped_column(String(64), ForeignKey("commands.id"), nullable=False)
    from_status: Mapped[Optional[str]] = mapped_column(String(32), nullable=True)
    to_status: Mapped[str] = mapped_column(String(32), nullable=False)
    phase: Mapped[str] = mapped_column(String(64), nullable=False)
    actor: Mapped[str] = mapped_column(String(32), nullable=False)  # user|worker|system
    note: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=_now)

    command: Mapped[Command] = relationship(back_populates="events")


class AuctionPosition(Base):
    """`auction_positions`: trạng thái đấu theo account/auction, lần xác minh gần nhất."""

    __tablename__ = "auction_positions"
    __table_args__ = (
        UniqueConstraint("account_id", "auction_id", name="uq_auction_positions_account_auction"),
    )

    id: Mapped[str] = mapped_column(String(64), primary_key=True, default=_uuid)
    account_id: Mapped[str] = mapped_column(String(64), ForeignKey("accounts.id"), nullable=False)
    auction_id: Mapped[str] = mapped_column(String(255), nullable=False)
    auction_status: Mapped[str] = mapped_column(String(32), default=AuctionStatus.UNKNOWN.value)
    max_bid_accepted_jpy: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    last_verified_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=_now)


class BudgetReservation(Base):
    """`budget_reservations`: ngân sách đang giữ, liên kết lệnh và nghĩa vụ."""

    __tablename__ = "budget_reservations"

    id: Mapped[str] = mapped_column(String(64), primary_key=True, default=_uuid)
    account_id: Mapped[str] = mapped_column(String(64), ForeignKey("accounts.id"), nullable=False)
    command_id: Mapped[str] = mapped_column(String(64), ForeignKey("commands.id"), nullable=False)
    reserved_jpy: Mapped[int] = mapped_column(Integer, nullable=False)
    status: Mapped[str] = mapped_column(String(16), default=ReservationStatus.ACTIVE.value)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=_now)
    released_at: Mapped[Optional[datetime]] = mapped_column(UTCDateTime(), nullable=True)
    release_reason: Mapped[str] = mapped_column(String(255), default="")

    command: Mapped[Command] = relationship(back_populates="reservations")


class WorkerHeartbeat(Base):
    """Nhịp worker cho `/api/health` và dashboard (mục 7, 12). Không phải
    cơ chế bầu chọn/failover — chỉ để quan sát worker còn sống hay không."""

    __tablename__ = "worker_heartbeats"

    worker_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    last_seen_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=_now)
    note: Mapped[str] = mapped_column(String(255), default="")


class TradeResult(Base):
    """`trade_results`: tham chiếu giao dịch, số tiền, trạng thái chi trả, bằng chứng."""

    __tablename__ = "trade_results"

    id: Mapped[str] = mapped_column(String(64), primary_key=True, default=_uuid)
    command_id: Mapped[str] = mapped_column(String(64), ForeignKey("commands.id"), nullable=False)
    trade_ref: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    amount_jpy: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    payment_status: Mapped[str] = mapped_column(
        String(32), default=PaymentStatus.NOT_STARTED.value
    )
    # Bằng chứng đã làm sạch (không cookie/token/OTP/số thẻ).
    evidence: Mapped[dict] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=_now)
