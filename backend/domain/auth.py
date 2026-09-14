"""Token thiết bị (mục 5.2): server chỉ lưu hash, cấp riêng theo thiết bị,
chủ sở hữu, tài khoản và scope hành động. Token không bao giờ đi qua URL/log.
"""
from __future__ import annotations

import hashlib
import hmac
import secrets

from backend.config import settings


def generate_raw_token() -> str:
    return secrets.token_urlsafe(32)


def hash_token(raw_token: str) -> str:
    mac = hmac.new(
        settings.device_token_pepper.encode("utf-8"), raw_token.encode("utf-8"), hashlib.sha256
    )
    return mac.hexdigest()


def generate_pairing_code() -> str:
    # 8 ký tự, dễ gõ tay, đủ ngẫu nhiên cho TTL ngắn + giới hạn số lần thử.
    alphabet = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"
    return "".join(secrets.choice(alphabet) for _ in range(8))


def hash_pairing_code(code: str) -> str:
    mac = hmac.new(
        settings.device_token_pepper.encode("utf-8"), code.encode("utf-8"), hashlib.sha256
    )
    return mac.hexdigest()
