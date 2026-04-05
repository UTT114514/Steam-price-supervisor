from __future__ import annotations

from datetime import datetime
from decimal import Decimal

from pydantic import BaseModel, ConfigDict, Field


class WatchItemCreate(BaseModel):
    steam_appid: int
    target_price: Decimal | None = Field(default=None, ge=0)
    priority: int = Field(default=5, ge=1, le=10)
    include_downloadable_content: bool = False
    enabled: bool = True
    title: str | None = None
    edition_label: str = "Standard"
    value_score: Decimal = Field(default=Decimal("1.00"), gt=0)
    base_game_appid: int | None = None


class WatchItemResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    steam_appid: int
    title: str
    edition_label: str
    value_score: Decimal
    target_price: Decimal | None
    priority: int
    enabled: bool
    current_price: Decimal | None = None
    currency: str | None = None
    current_discount_percent: int | None = None
    last_decision_status: str | None = None
    last_decision_reason: str | None = None
    last_checked_at: datetime | None = None


class RefreshRequest(BaseModel):
    steam_appid: int | None = None


class EditionRecommendation(BaseModel):
    steam_appid: int
    title: str
    edition_label: str
    current_price: Decimal | None
    historical_low_90d: Decimal | None
    historical_low_180d: Decimal | None
    discount_percent: int
    best_source: str | None
    value_score: Decimal
    normalized_price: Decimal | None


class DecisionResponse(BaseModel):
    steam_appid: int
    title: str
    status: str
    reason: str
    current_price: Decimal | None
    currency: str | None
    historical_low_90d: Decimal | None
    historical_low_180d: Decimal | None
    delta_to_180d_low: Decimal | None
    target_price: Decimal | None
    recommended_purchase_appid: int | None
    recommended_purchase_title: str | None
    recommended_source: str | None
    alternatives: list[EditionRecommendation]


class PricePoint(BaseModel):
    observed_at: datetime
    current_price: Decimal | None
    source_name: str
    discount_percent: int


class AlertResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    steam_appid: int
    alert_type: str
    message: str
    status: str
    price_amount: Decimal | None
    triggered_at: datetime
    sent_at: datetime | None
    last_error: str | None


class GameDetailResponse(BaseModel):
    steam_appid: int
    title: str
    edition_label: str
    base_game_appid: int | None
    capsule_url: str | None
    publisher: str | None
    developer: str | None
    decision: DecisionResponse
    price_history: list[PricePoint]
    alerts: list[AlertResponse]


class SettingsPayload(BaseModel):
    refresh_interval_minutes: int = Field(default=180, ge=15, le=1440)
    full_sync_hour: int = Field(default=6, ge=0, le=23)
    notification_email: str = ""
    smtp_host: str = ""
    smtp_port: int = Field(default=587, ge=1, le=65535)
    smtp_username: str = ""
    smtp_password: str = ""
    smtp_sender: str = ""
    smtp_use_tls: bool = True
    smtp_use_ssl: bool = False
    xiaoheihe_enabled: bool = False
