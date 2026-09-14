from __future__ import annotations

from functools import lru_cache

from backend.adapters.base import YahooAdapter
from backend.config import settings


@lru_cache(maxsize=1)
def get_adapter() -> YahooAdapter:
    if settings.yahoo_adapter == "mock":
        from backend.adapters.mock.adapter import MockYahooAdapter

        return MockYahooAdapter()
    if settings.yahoo_adapter == "yahoo":
        from backend.adapters.yahoo.adapter import YahooBrowserAdapter

        return YahooBrowserAdapter()
    raise ValueError(f"YAHOO_ADAPTER không hợp lệ: {settings.yahoo_adapter!r}")
