from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal
from typing import Protocol


@dataclass(slots=True)
class PriceOffer:
    source_name: str
    source_game_id: str
    title: str
    current_price: Decimal | None
    original_price: Decimal | None
    discount_percent: int
    currency: str
    is_available: bool = True
    source_url: str | None = None
    edition_label: str = "Standard"
    base_game_appid: int | None = None
    value_score: Decimal = Decimal("1.00")


@dataclass(slots=True)
class ProviderGameData:
    steam_appid: int
    source_name: str
    title: str
    capsule_url: str | None = None
    publisher: str | None = None
    developer: str | None = None
    is_removed: bool = False
    offers: list[PriceOffer] = field(default_factory=list)


class PriceProvider(Protocol):
    name: str

    def fetch(self, steam_appid: int) -> ProviderGameData | None:
        ...
