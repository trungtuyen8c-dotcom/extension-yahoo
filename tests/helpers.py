from __future__ import annotations

from datetime import datetime, timedelta, timezone

from backend.db.models import Account, Device
from backend.domain.auth import generate_raw_token, hash_token

DEFAULT_SCOPE = ["PLACE_BID", "BUY_NOW", "STORE_CHECKOUT", "PAY_WON_ITEM", "REFRESH_STATUS"]


def create_account(session_factory, *, owner_id="owner-1", budget_limit_jpy=1_000_000) -> str:
    with session_factory() as db:
        account = Account(
            owner_id=owner_id,
            yahoo_account_label="yahoo-jp-01",
            playwright_profile_ref="profile-01",
            budget_limit_jpy=budget_limit_jpy,
        )
        db.add(account)
        db.commit()
        return account.id


def create_device_token(session_factory, *, owner_id="owner-1", scope=None) -> str:
    raw = generate_raw_token()
    with session_factory() as db:
        db.add(
            Device(
                owner_id=owner_id,
                token_hash=hash_token(raw),
                scope=scope if scope is not None else DEFAULT_SCOPE,
                expires_at=datetime.now(timezone.utc) + timedelta(days=1),
            )
        )
        db.commit()
    return raw


def auth_headers(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}
