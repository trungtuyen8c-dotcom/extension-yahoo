from __future__ import annotations

import uuid

from tests.helpers import auth_headers, create_account, create_device_token


def _make_preview(client, token, account_id, auction_id, action="PLACE_BID"):
    resp = client.post(
        "/api/previews",
        json={"account_id": account_id, "auction_id": auction_id, "action": action},
        headers=auth_headers(token),
    )
    assert resp.status_code == 200, resp.text
    return resp.json()


def _bid_payload(*, account_id, auction_id, preview_id, intent_id=None, dry_run=True, max_bid=1000, max_total=1200):
    return {
        "intent_id": intent_id or str(uuid.uuid4()),
        "account_id": account_id,
        "auction_id": auction_id,
        "preview_id": preview_id,
        "action": "PLACE_BID",
        "currency": "JPY",
        "unknown_cost_policy": "BLOCK",
        "max_bid_jpy": max_bid,
        "max_total_jpy": max_total,
        "expires_in_seconds": 120,
        "dry_run": dry_run,
    }


def test_pairing_exchange_and_authenticated_call(app_client):
    account_id = create_account(app_client.SessionLocal, owner_id="owner-pair")
    resp = app_client.post(
        "/api/admin/pairing/codes",
        json={"owner_id": "owner-pair", "account_id": account_id, "scope": ["PLACE_BID"]},
        headers={"X-Admin-Secret": "dev-only-secret-change-me"},
    )
    assert resp.status_code == 200, resp.text
    code = resp.json()["pairing_code"]

    resp2 = app_client.post("/api/pairing/exchange", json={"pairing_code": code, "device_label": "test-device"})
    assert resp2.status_code == 200, resp2.text
    token = resp2.json()["device_token"]

    app_client.mock_adapter.seed_listing(account_id + "-auction")
    resp3 = app_client.get(f"/api/accounts/{account_id}/status", headers=auth_headers(token))
    assert resp3.status_code == 200
    assert resp3.json()["is_logged_in"] is True

    # Mã đã dùng không thể dùng lại.
    resp4 = app_client.post("/api/pairing/exchange", json={"pairing_code": code})
    assert resp4.status_code == 401


def test_unauthenticated_request_rejected(app_client):
    resp = app_client.get("/api/commands/does-not-exist")
    assert resp.status_code == 401


def test_preview_unsupported_listing_type(app_client):
    account_id = create_account(app_client.SessionLocal)
    token = create_device_token(app_client.SessionLocal)
    app_client.mock_adapter.seed_listing("A1", listing_type="OTHER", scenario="UNSUPPORTED")

    resp = app_client.post(
        "/api/previews",
        json={"account_id": account_id, "auction_id": "A1", "action": "PLACE_BID"},
        headers=auth_headers(token),
    )
    assert resp.status_code == 422
    assert resp.json()["code"] == "UNSUPPORTED_LISTING_TYPE"


def test_command_dry_run_idempotent_replay_and_conflict(app_client):
    account_id = create_account(app_client.SessionLocal)
    token = create_device_token(app_client.SessionLocal)
    app_client.mock_adapter.seed_listing("A1")
    preview = _make_preview(app_client, token, account_id, "A1")

    intent_id = str(uuid.uuid4())
    payload = _bid_payload(account_id=account_id, auction_id="A1", preview_id=preview["preview_id"], intent_id=intent_id)

    headers = {**auth_headers(token), "Idempotency-Key": "key-1"}
    r1 = app_client.post("/api/commands", json=payload, headers=headers)
    assert r1.status_code == 202, r1.text
    command_id = r1.json()["command_id"]

    # Bấm nhiều lần cùng khóa/payload -> một lệnh duy nhất.
    for _ in range(5):
        r_retry = app_client.post("/api/commands", json=payload, headers=headers)
        assert r_retry.status_code == 202
        assert r_retry.json()["command_id"] == command_id

    # Cùng khóa nhưng đổi giá -> 409, lệnh cũ không đổi.
    changed_payload = dict(payload, max_total_jpy=1300)
    r_conflict = app_client.post("/api/commands", json=changed_payload, headers=headers)
    assert r_conflict.status_code == 409
    assert r_conflict.json()["code"] == "IDEMPOTENCY_KEY_CONFLICT"

    r_check = app_client.get(f"/api/commands/{command_id}", headers=auth_headers(token))
    assert r_check.json()["command_status"] == "DRY_RUN_SUCCEEDED" or r_check.json()["command_status"] == "QUEUED"


def test_command_same_intent_different_key(app_client):
    account_id = create_account(app_client.SessionLocal)
    token = create_device_token(app_client.SessionLocal)
    app_client.mock_adapter.seed_listing("A1")
    preview = _make_preview(app_client, token, account_id, "A1")

    intent_id = str(uuid.uuid4())
    payload = _bid_payload(account_id=account_id, auction_id="A1", preview_id=preview["preview_id"], intent_id=intent_id)

    r1 = app_client.post("/api/commands", json=payload, headers={**auth_headers(token), "Idempotency-Key": "k-a"})
    assert r1.status_code == 202
    command_id = r1.json()["command_id"]

    # Cùng intent, khóa khác nhưng payload khớp -> trả lệnh cũ.
    r2 = app_client.post("/api/commands", json=payload, headers={**auth_headers(token), "Idempotency-Key": "k-b"})
    assert r2.status_code == 202
    assert r2.json()["command_id"] == command_id

    # Cùng intent, khóa khác, payload khác -> xung đột.
    changed = dict(payload, max_bid_jpy=42)
    r3 = app_client.post("/api/commands", json=changed, headers={**auth_headers(token), "Idempotency-Key": "k-c"})
    assert r3.status_code == 409


def test_missing_idempotency_key_rejected(app_client):
    account_id = create_account(app_client.SessionLocal)
    token = create_device_token(app_client.SessionLocal)
    app_client.mock_adapter.seed_listing("A1")
    preview = _make_preview(app_client, token, account_id, "A1")
    payload = _bid_payload(account_id=account_id, auction_id="A1", preview_id=preview["preview_id"])

    resp = app_client.post("/api/commands", json=payload, headers=auth_headers(token))
    assert resp.status_code == 422


def test_budget_exceeded(app_client):
    account_id = create_account(app_client.SessionLocal, budget_limit_jpy=1000)
    token = create_device_token(app_client.SessionLocal)
    app_client.mock_adapter.seed_listing("A1")
    preview = _make_preview(app_client, token, account_id, "A1")
    payload = _bid_payload(account_id=account_id, auction_id="A1", preview_id=preview["preview_id"], max_bid=900, max_total=5000)

    resp = app_client.post("/api/commands", json=payload, headers={**auth_headers(token), "Idempotency-Key": "k-budget"})
    assert resp.status_code == 422
    assert resp.json()["code"] == "BUDGET_EXCEEDED"


def test_unknown_cost_blocked(app_client):
    account_id = create_account(app_client.SessionLocal)
    token = create_device_token(app_client.SessionLocal)
    app_client.mock_adapter.seed_listing("A1", fees_fully_known=False)
    preview = _make_preview(app_client, token, account_id, "A1")
    payload = _bid_payload(account_id=account_id, auction_id="A1", preview_id=preview["preview_id"])

    resp = app_client.post("/api/commands", json=payload, headers={**auth_headers(token), "Idempotency-Key": "k-unknown-cost"})
    assert resp.status_code == 422
    assert resp.json()["code"] == "UNKNOWN_COST_BLOCKED"


def test_preview_wrong_account_rejected(app_client):
    account_id = create_account(app_client.SessionLocal, owner_id="owner-a")
    other_owner_account_id = create_account(app_client.SessionLocal, owner_id="owner-b")
    token = create_device_token(app_client.SessionLocal, owner_id="owner-a")
    app_client.mock_adapter.seed_listing("A1")
    preview = _make_preview(app_client, token, account_id, "A1")

    # Payload trỏ account của owner khác dù preview thuộc owner-a.
    payload = _bid_payload(account_id=other_owner_account_id, auction_id="A1", preview_id=preview["preview_id"])
    resp = app_client.post("/api/commands", json=payload, headers={**auth_headers(token), "Idempotency-Key": "k-wrong-acct"})
    assert resp.status_code == 403


def test_cancel_only_while_queued(app_client):
    account_id = create_account(app_client.SessionLocal)
    token = create_device_token(app_client.SessionLocal)
    app_client.mock_adapter.seed_listing("A1")
    preview = _make_preview(app_client, token, account_id, "A1")
    payload = _bid_payload(account_id=account_id, auction_id="A1", preview_id=preview["preview_id"])

    resp = app_client.post("/api/commands", json=payload, headers={**auth_headers(token), "Idempotency-Key": "k-cancel"})
    command_id = resp.json()["command_id"]

    cancel_resp = app_client.post(f"/api/commands/{command_id}/cancel", headers=auth_headers(token))
    assert cancel_resp.status_code == 200
    assert cancel_resp.json()["command_status"] == "CANCELLED"

    cancel_again = app_client.post(f"/api/commands/{command_id}/cancel", headers=auth_headers(token))
    assert cancel_again.status_code == 409


def test_forbidden_scope(app_client):
    account_id = create_account(app_client.SessionLocal)
    token = create_device_token(app_client.SessionLocal, scope=["BUY_NOW"])
    app_client.mock_adapter.seed_listing("A1")
    preview = _make_preview(app_client, token, account_id, "A1")
    payload = _bid_payload(account_id=account_id, auction_id="A1", preview_id=preview["preview_id"])

    resp = app_client.post("/api/commands", json=payload, headers={**auth_headers(token), "Idempotency-Key": "k-scope"})
    assert resp.status_code == 403
