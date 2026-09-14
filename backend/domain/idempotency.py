"""Chống gửi trùng theo mục 9.1: hash payload chuẩn hóa, tra khóa trùng
trước khi tạo lệnh mới. `intent_id` và `expires_in_seconds` bị loại khỏi hash
vì chúng là siêu dữ liệu của lần gửi, không phải nội dung nghiệp vụ của lệnh.
"""
from __future__ import annotations

import hashlib
import json

_EXCLUDED_KEYS = {"intent_id", "expires_in_seconds"}


def normalize_payload(payload: dict) -> dict:
    return {k: v for k, v in sorted(payload.items()) if k not in _EXCLUDED_KEYS}


def payload_hash(payload: dict) -> str:
    canonical = json.dumps(normalize_payload(payload), sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()
