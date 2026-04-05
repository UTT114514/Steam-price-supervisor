from __future__ import annotations

from decimal import Decimal

import httpx

from ..config import Settings
from .base import PriceOffer, ProviderGameData


class XiaoHeiHeProvider:
    name = "xiaoheihe"

    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self._timeout = settings.request_timeout_seconds

    def fetch(self, steam_appid: int) -> ProviderGameData | None:
        if not self.settings.xiaoheihe_enabled or not self.settings.xiaoheihe_base_url:
            return None

        url = self.settings.xiaoheihe_base_url.format(appid=steam_appid)
        response = httpx.get(url, timeout=self._timeout)
        response.raise_for_status()
        payload = response.json()
        if not payload:
            return None

        title = payload.get("title") or payload.get("name") or f"Steam App {steam_appid}"
        offers = []
        for entry in payload.get("offers", [payload]):
            current_raw = entry.get("current_price")
            original_raw = entry.get("original_price", current_raw)
            offers.append(
                PriceOffer(
                    source_name=self.name,
                    source_game_id=str(entry.get("source_game_id") or steam_appid),
                    title=entry.get("title") or title,
                    current_price=Decimal(str(current_raw)) if current_raw is not None else None,
                    original_price=Decimal(str(original_raw))
                    if original_raw is not None
                    else None,
                    discount_percent=int(entry.get("discount_percent", 0)),
                    currency=entry.get("currency", self.settings.default_currency),
                    is_available=entry.get("is_available", True),
                    source_url=entry.get("source_url"),
                    edition_label=entry.get("edition_label", "Supplemental"),
                    base_game_appid=entry.get("base_game_appid"),
                    value_score=Decimal(str(entry.get("value_score", "1.00"))),
                )
            )

        return ProviderGameData(
            steam_appid=steam_appid,
            source_name=self.name,
            title=title,
            capsule_url=payload.get("capsule_url"),
            publisher=payload.get("publisher"),
            developer=payload.get("developer"),
            is_removed=payload.get("is_removed", False),
            offers=offers,
        )
