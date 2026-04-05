from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, Numeric, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .database import Base


def utc_now() -> datetime:
    return datetime.now(UTC).replace(tzinfo=None)


class GameCanonical(Base):
    __tablename__ = "game_canonical"

    steam_appid: Mapped[int] = mapped_column(Integer, primary_key=True)
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    capsule_url: Mapped[str | None] = mapped_column(String(500), nullable=True)
    publisher: Mapped[str | None] = mapped_column(String(255), nullable=True)
    developer: Mapped[str | None] = mapped_column(String(255), nullable=True)
    is_removed: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    base_game_appid: Mapped[int | None] = mapped_column(
        ForeignKey("game_canonical.steam_appid"), nullable=True
    )
    edition_label: Mapped[str] = mapped_column(String(120), default="Standard")
    value_score: Mapped[Decimal] = mapped_column(
        Numeric(10, 2), default=Decimal("1.00"), nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=utc_now,
        onupdate=utc_now,
        nullable=False,
    )

    price_snapshots: Mapped[list["PriceSnapshot"]] = relationship(
        back_populates="game", cascade="all, delete-orphan"
    )
    watch_items: Mapped[list["WatchItem"]] = relationship(back_populates="game")
    mappings: Mapped[list["SourceGameMapping"]] = relationship(
        back_populates="game", cascade="all, delete-orphan"
    )
    alerts: Mapped[list["AlertEvent"]] = relationship(back_populates="game")


class SourceGameMapping(Base):
    __tablename__ = "source_game_mapping"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    steam_appid: Mapped[int] = mapped_column(
        ForeignKey("game_canonical.steam_appid"), nullable=False, index=True
    )
    source_name: Mapped[str] = mapped_column(String(50), nullable=False, index=True)
    source_game_id: Mapped[str] = mapped_column(String(120), nullable=False, index=True)
    source_url: Mapped[str | None] = mapped_column(String(500), nullable=True)
    is_primary: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, nullable=False
    )

    game: Mapped[GameCanonical] = relationship(back_populates="mappings")


class WatchItem(Base):
    __tablename__ = "watch_item"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    steam_appid: Mapped[int] = mapped_column(
        ForeignKey("game_canonical.steam_appid"), nullable=False, unique=True
    )
    target_price: Mapped[Decimal | None] = mapped_column(Numeric(10, 2), nullable=True)
    priority: Mapped[int] = mapped_column(Integer, default=5, nullable=False)
    include_downloadable_content: Mapped[bool] = mapped_column(
        Boolean, default=False, nullable=False
    )
    enabled: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    last_decision_status: Mapped[str | None] = mapped_column(String(20), nullable=True)
    last_decision_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    last_checked_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=utc_now,
        onupdate=utc_now,
        nullable=False,
    )

    game: Mapped[GameCanonical] = relationship(back_populates="watch_items")
    alerts: Mapped[list["AlertEvent"]] = relationship(back_populates="watch_item")


class PriceSnapshot(Base):
    __tablename__ = "price_snapshot"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    steam_appid: Mapped[int] = mapped_column(
        ForeignKey("game_canonical.steam_appid"), nullable=False, index=True
    )
    source_name: Mapped[str] = mapped_column(String(50), nullable=False, index=True)
    source_game_id: Mapped[str] = mapped_column(String(120), nullable=False)
    source_url: Mapped[str | None] = mapped_column(String(500), nullable=True)
    original_price: Mapped[Decimal | None] = mapped_column(Numeric(10, 2), nullable=True)
    current_price: Mapped[Decimal | None] = mapped_column(Numeric(10, 2), nullable=True)
    discount_percent: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    currency: Mapped[str] = mapped_column(String(16), default="CNY", nullable=False)
    is_available: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    observed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, nullable=False, index=True
    )

    game: Mapped[GameCanonical] = relationship(back_populates="price_snapshots")


class AlertEvent(Base):
    __tablename__ = "alert_event"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    steam_appid: Mapped[int] = mapped_column(
        ForeignKey("game_canonical.steam_appid"), nullable=False, index=True
    )
    watch_item_id: Mapped[int | None] = mapped_column(
        ForeignKey("watch_item.id"), nullable=True, index=True
    )
    alert_type: Mapped[str] = mapped_column(String(50), nullable=False)
    alert_key: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    fingerprint: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    message: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(String(20), default="pending", nullable=False)
    price_amount: Mapped[Decimal | None] = mapped_column(Numeric(10, 2), nullable=True)
    triggered_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, nullable=False, index=True
    )
    sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_error: Mapped[str | None] = mapped_column(Text, nullable=True)

    game: Mapped[GameCanonical] = relationship(back_populates="alerts")
    watch_item: Mapped[WatchItem | None] = relationship(back_populates="alerts")


class AppSetting(Base):
    __tablename__ = "app_setting"

    key: Mapped[str] = mapped_column(String(100), primary_key=True)
    value: Mapped[str] = mapped_column(Text, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=utc_now,
        onupdate=utc_now,
        nullable=False,
    )
