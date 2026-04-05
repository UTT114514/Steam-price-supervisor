from __future__ import annotations

import logging
from decimal import Decimal

import httpx
from tenacity import (
    retry,
    stop_after_attempt,
    wait_exponential,
    retry_if_exception_type,
)

from ..config import Settings
from .base import PriceOffer, ProviderGameData

logger = logging.getLogger(__name__)


class SteamProvider:
    name = "steam"

    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self._timeout = settings.request_timeout_seconds

    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=2, max=10),
        retry=retry_if_exception_type((httpx.TimeoutException, httpx.ConnectError)),
        reraise=True,
    )
    def fetch(self, steam_appid: int) -> ProviderGameData | None:
        """从 Steam API 拉取游戏信息
        
        Args:
            steam_appid: Steam 应用 ID
            
        Returns:
            ProviderGameData 对象或 None（如果游戏不存在或被下架）
            
        Raises:
            httpx.HTTPError: 网络请求失败
            httpx.TimeoutError: 请求超时（会自动重试）
        """
        params = {
            "appids": steam_appid,
            "cc": self.settings.steam_country_code,
            "l": self.settings.steam_language,
        }
        
        try:
            response = httpx.get(
                "https://store.steampowered.com/api/appdetails",
                params=params,
                timeout=self._timeout,
            )
            response.raise_for_status()
        except httpx.TimeoutException as e:
            logger.warning(
                f"Steam API timeout for appid {steam_appid} (retry pending): {e}"
            )
            raise
        except httpx.ConnectError as e:
            logger.warning(
                f"Steam API connection error for appid {steam_appid} (retry pending): {e}"
            )
            raise
        except httpx.HTTPStatusError as e:
            logger.error(
                f"Steam API HTTP error for appid {steam_appid}: {e.status_code} {e.response.text[:200]}"
            )
            return None
        except Exception as e:
            logger.error(f"Unexpected error fetching Steam appid {steam_appid}: {e}")
            return None

        try:
            payload = response.json()
        except Exception as e:
            logger.error(f"Failed to parse Steam API response for appid {steam_appid}: {e}")
            return None

        node = payload.get(str(steam_appid), {})
        if not node.get("success"):
            logger.debug(f"Steam appid {steam_appid} not found or not successful")
            return None

        try:
            data = node.get("data", {})
            price = data.get("price_overview") or {}
            current_price = (
                Decimal(str(price["final"] / 100)) if price.get("final") is not None else None
            )
            original_price = (
                Decimal(str(price["initial"] / 100))
                if price.get("initial") is not None
                else current_price
            )
            discount_percent = int(price.get("discount_percent", 0))
            currency = price.get("currency", self.settings.default_currency)
            title = data.get("name") or f"Steam App {steam_appid}"
            
            offer = PriceOffer(
                source_name=self.name,
                source_game_id=str(steam_appid),
                title=title,
                current_price=current_price,
                original_price=original_price,
                discount_percent=discount_percent,
                currency=currency,
                is_available=bool(data),
                source_url=f"https://store.steampowered.com/app/{steam_appid}",
            )
            
            logger.debug(f"Fetched Steam appid {steam_appid}: {title} ({currency} {current_price})")
            
            return ProviderGameData(
                steam_appid=steam_appid,
                source_name=self.name,
                title=title,
                capsule_url=data.get("header_image"),
                publisher=", ".join(data.get("publishers") or []),
                developer=", ".join(data.get("developers") or []),
                is_removed=not bool(data),
                offers=[offer],
            )
        except Exception as e:
            logger.error(f"Error processing Steam API data for appid {steam_appid}: {e}")
            return None
