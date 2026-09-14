"""Schema payload cho từng action. Mỗi action có schema riêng (mục 7), từ
chối trường lạ (`extra="forbid"`) và tổ hợp tiền không hợp lệ.
"""
from __future__ import annotations

from typing import Annotated, Literal, Union, Optional

from pydantic import BaseModel, ConfigDict, Field, model_validator


def _jpy_field(**kwargs):
    return Field(gt=0, lt=100_000_000, **kwargs)


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=False)


class Address(StrictModel):
    recipient_name: str
    postal_code: str
    prefecture: str
    city_line: str
    phone: str


class _BaseCommandPayload(StrictModel):
    intent_id: str = Field(min_length=8, max_length=64)
    account_id: str
    auction_id: str
    preview_id: str
    currency: Literal["JPY"] = "JPY"
    unknown_cost_policy: Literal["BLOCK"] = "BLOCK"
    expires_in_seconds: int = Field(gt=0, le=3600)
    dry_run: bool = True

    @model_validator(mode="before")
    @classmethod
    def _reject_float_money(cls, data):
        if isinstance(data, dict):
            for key, value in data.items():
                if key.endswith("_jpy") and isinstance(value, float):
                    raise ValueError(f"{key} phải là số nguyên JPY, không dùng float")
        return data


class PlaceBidPayload(_BaseCommandPayload):
    action: Literal["PLACE_BID"] = "PLACE_BID"
    max_bid_jpy: int = _jpy_field()
    max_total_jpy: int = _jpy_field()

    @model_validator(mode="after")
    def _total_covers_bid(self):
        if self.max_total_jpy < self.max_bid_jpy:
            raise ValueError("max_total_jpy phải >= max_bid_jpy")
        return self


class BuyNowPayload(_BaseCommandPayload):
    action: Literal["BUY_NOW"] = "BUY_NOW"
    max_item_price_jpy: int = _jpy_field()
    max_total_jpy: int = _jpy_field()

    @model_validator(mode="after")
    def _total_covers_item(self):
        if self.max_total_jpy < self.max_item_price_jpy:
            raise ValueError("max_total_jpy phải >= max_item_price_jpy")
        return self


class StoreCheckoutPayload(_BaseCommandPayload):
    action: Literal["STORE_CHECKOUT"] = "STORE_CHECKOUT"
    max_total_jpy: int = _jpy_field()
    address: Address
    delivery_method: str
    payment_method: str
    # Quyền chi tiền rõ ràng cho checkout gộp mua+trả tiền (mục 11). Nếu False
    # và luồng không tách được thanh toán, endpoint trả PAYMENT_AUTH_REQUIRED.
    authorize_payment: bool = False


class PayWonItemPayload(_BaseCommandPayload):
    action: Literal["PAY_WON_ITEM"] = "PAY_WON_ITEM"
    trade_ref: str
    max_total_jpy: int = _jpy_field()
    payment_method: str
    address: Optional[Address] = None


CommandPayload = Annotated[
    Union[PlaceBidPayload, BuyNowPayload, StoreCheckoutPayload, PayWonItemPayload],
    Field(discriminator="action"),
]


class PreviewRequest(StrictModel):
    account_id: str
    auction_id: str
    action: Literal["PLACE_BID", "BUY_NOW", "STORE_CHECKOUT", "PAY_WON_ITEM", "REFRESH_STATUS"]


class PreviewResponse(StrictModel):
    preview_id: str
    owner_id: str
    account_id: str
    auction_id: str
    action: str
    listing_snapshot: dict
    data_version: int
    fetched_at: str
    expires_at: str


class CommandStatusResponse(StrictModel):
    command_id: str
    command_status: str
    action: str
    auction_status: str
    payment_status: str
    last_verified_at: Optional[str] = None


class PairingExchangeRequest(StrictModel):
    pairing_code: str
    device_label: str = ""


class PairingExchangeResponse(StrictModel):
    device_token: str
    owner_id: str
    account_id: Optional[str] = None
    scope: list[str]
    expires_at: str
