from __future__ import annotations

from backend.domain.idempotency import normalize_payload, payload_hash


def test_same_payload_same_hash_regardless_of_key_order():
    p1 = {"action": "PLACE_BID", "max_bid_jpy": 1000, "intent_id": "a", "expires_in_seconds": 60}
    p2 = {"intent_id": "b", "max_bid_jpy": 1000, "action": "PLACE_BID", "expires_in_seconds": 999}
    assert payload_hash(p1) == payload_hash(p2)


def test_different_money_changes_hash():
    base = {"action": "PLACE_BID", "max_bid_jpy": 1000, "intent_id": "a", "expires_in_seconds": 60}
    changed = {"action": "PLACE_BID", "max_bid_jpy": 2000, "intent_id": "a", "expires_in_seconds": 60}
    assert payload_hash(base) != payload_hash(changed)


def test_different_dry_run_changes_hash():
    base = {"action": "PLACE_BID", "max_bid_jpy": 1000, "dry_run": True}
    changed = {"action": "PLACE_BID", "max_bid_jpy": 1000, "dry_run": False}
    assert payload_hash(base) != payload_hash(changed)


def test_normalize_excludes_intent_and_expiry():
    normalized = normalize_payload({"intent_id": "x", "expires_in_seconds": 5, "action": "PLACE_BID"})
    assert normalized == {"action": "PLACE_BID"}
