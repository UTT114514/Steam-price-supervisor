from __future__ import annotations

import logging
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..models import GameCanonical, PriceSnapshot, SourceGameMapping, WatchItem, utc_now
from ..providers.base import PriceProvider, ProviderGameData
from ..schemas import WatchItemCreate
from .alerts import AlertService
from .decision import DecisionService
from .notifications import EmailNotifier

logger = logging.getLogger(__name__)


class RefreshServiceError(Exception):
    """Base class for refresh errors."""


class RefreshUnavailableError(RefreshServiceError):
    """Raised when no provider returns fresh data for a refresh cycle."""


class RefreshService:
    def __init__(
        self,
        providers: list[PriceProvider],
        decision_service: DecisionService,
        alert_service: AlertService,
    ) -> None:
        self.providers = providers
        self.decision_service = decision_service
        self.alert_service = alert_service

    def ensure_watch_item(
        self,
        session: Session,
        payload: WatchItemCreate,
        notifier: EmailNotifier,
    ) -> WatchItem:
        game = session.get(GameCanonical, payload.steam_appid)
        if game is None:
            game = GameCanonical(
                steam_appid=payload.steam_appid,
                title=payload.title or f"Steam App {payload.steam_appid}",
                edition_label=payload.edition_label,
                value_score=payload.value_score,
                base_game_appid=payload.base_game_appid,
            )
            session.add(game)
            session.flush()
        else:
            game.title = payload.title or game.title
            game.edition_label = payload.edition_label or game.edition_label
            game.value_score = payload.value_score
            if payload.base_game_appid:
                game.base_game_appid = payload.base_game_appid

        watch_item = session.scalars(
            select(WatchItem).where(WatchItem.steam_appid == payload.steam_appid)
        ).first()
        if watch_item is None:
            watch_item = WatchItem(
                steam_appid=payload.steam_appid,
                target_price=payload.target_price,
                priority=payload.priority,
                include_downloadable_content=payload.include_downloadable_content,
                enabled=payload.enabled,
            )
            session.add(watch_item)
            logger.info("Created watch item for appid %s", payload.steam_appid)
        else:
            watch_item.target_price = payload.target_price
            watch_item.priority = payload.priority
            watch_item.include_downloadable_content = payload.include_downloadable_content
            watch_item.enabled = payload.enabled
            logger.info("Updated watch item for appid %s", payload.steam_appid)

        session.commit()

        try:
            self.refresh_watch_item(session, watch_item, notifier)
            session.commit()
        except Exception:
            session.rollback()
            logger.exception(
                "Failed to refresh watch item %s during ensure",
                payload.steam_appid,
            )
            raise

        session.refresh(watch_item)
        return watch_item

    def refresh_watch_item(
        self,
        session: Session,
        watch_item: WatchItem,
        notifier: EmailNotifier,
    ):
        fetched_any = False
        fetch_errors: list[str] = []
        attempted_providers = 0

        for provider in self.providers:
            attempted_providers += 1
            try:
                data = provider.fetch(watch_item.steam_appid)
                if data is None:
                    logger.debug(
                        "Provider %s returned no data for appid %s",
                        provider.name,
                        watch_item.steam_appid,
                    )
                    continue
                fetched_any = True
                self._apply_provider_data(session, data)
                logger.debug(
                    "Success fetching from %s for appid %s",
                    provider.name,
                    watch_item.steam_appid,
                )
            except Exception as exc:
                error_msg = (
                    f"Provider {provider.name} failed for appid "
                    f"{watch_item.steam_appid}: {exc}"
                )
                logger.warning(error_msg)
                fetch_errors.append(error_msg)

        if not fetched_any:
            if fetch_errors:
                error_msg = (
                    f"All providers failed for appid {watch_item.steam_appid}: "
                    + "; ".join(fetch_errors)
                )
                logger.error(error_msg)
                raise RefreshUnavailableError(error_msg)

            error_msg = f"No provider returned fresh data for appid {watch_item.steam_appid}"
            logger.warning(error_msg)
            if attempted_providers == 0 or session.get(GameCanonical, watch_item.steam_appid) is None:
                raise ValueError(error_msg)
            raise RefreshUnavailableError(error_msg)

        session.flush()

        decision = self.decision_service.evaluate(session, watch_item.steam_appid, watch_item)
        logger.debug(
            "Decision for appid %s: %s - %s",
            watch_item.steam_appid,
            decision.status,
            decision.reason,
        )

        try:
            self.alert_service.evaluate_and_send(session, watch_item, decision, notifier)
        except Exception:
            logger.exception(
                "Failed to evaluate/send alerts for appid %s",
                watch_item.steam_appid,
            )

        watch_item.last_checked_at = utc_now()
        watch_item.last_decision_status = decision.status
        watch_item.last_decision_reason = decision.reason
        logger.info("Completed refresh for appid %s", watch_item.steam_appid)
        return decision

    def refresh_all(self, session: Session, notifier: EmailNotifier) -> list[dict]:
        results = []
        watch_items = session.scalars(
            select(WatchItem)
            .where(WatchItem.enabled.is_(True))
            .order_by(WatchItem.priority.asc())
        ).all()

        logger.info("Starting refresh cycle for %s watch items", len(watch_items))

        for watch_item in watch_items:
            try:
                decision = self.refresh_watch_item(session, watch_item, notifier)
                results.append(
                    {
                        "watch_item_id": watch_item.id,
                        "steam_appid": watch_item.steam_appid,
                        "status": decision.status,
                    }
                )
            except Exception as exc:
                logger.exception("Failed to refresh watch item %s", watch_item.steam_appid)
                results.append(
                    {
                        "watch_item_id": watch_item.id,
                        "steam_appid": watch_item.steam_appid,
                        "status": "error",
                        "error": str(exc),
                    }
                )

        session.commit()
        logger.info("Completed refresh cycle: %s items processed", len(results))
        return results

    def _apply_provider_data(self, session: Session, data: ProviderGameData) -> None:
        primary_offer = data.offers[0] if data.offers else None
        game = session.get(GameCanonical, data.steam_appid)
        if game is None:
            game = GameCanonical(
                steam_appid=data.steam_appid,
                title=data.title,
                capsule_url=data.capsule_url,
                publisher=data.publisher,
                developer=data.developer,
                is_removed=data.is_removed,
                edition_label=primary_offer.edition_label if primary_offer else "Standard",
                base_game_appid=primary_offer.base_game_appid if primary_offer else None,
                value_score=primary_offer.value_score if primary_offer else Decimal("1.00"),
            )
            session.add(game)
            session.flush()
        else:
            game.title = data.title or game.title
            game.capsule_url = data.capsule_url or game.capsule_url
            game.publisher = data.publisher or game.publisher
            game.developer = data.developer or game.developer
            game.is_removed = data.is_removed
            if primary_offer:
                game.edition_label = primary_offer.edition_label or game.edition_label
                game.value_score = primary_offer.value_score or game.value_score
                if primary_offer.base_game_appid:
                    game.base_game_appid = primary_offer.base_game_appid

        for offer in data.offers:
            mapping = session.scalars(
                select(SourceGameMapping).where(
                    SourceGameMapping.source_name == offer.source_name,
                    SourceGameMapping.source_game_id == offer.source_game_id,
                )
            ).first()
            if mapping is None:
                session.add(
                    SourceGameMapping(
                        steam_appid=data.steam_appid,
                        source_name=offer.source_name,
                        source_game_id=offer.source_game_id,
                        source_url=offer.source_url,
                        is_primary=offer.source_name == "steam",
                    )
                )
            else:
                mapping.steam_appid = data.steam_appid
                mapping.source_url = offer.source_url

            latest = session.scalars(
                select(PriceSnapshot)
                .where(
                    PriceSnapshot.steam_appid == data.steam_appid,
                    PriceSnapshot.source_name == offer.source_name,
                )
                .order_by(PriceSnapshot.observed_at.desc())
            ).first()
            if (
                latest is not None
                and latest.current_price == offer.current_price
                and latest.original_price == offer.original_price
                and latest.discount_percent == offer.discount_percent
                and latest.currency == offer.currency
                and latest.is_available == offer.is_available
            ):
                continue

            session.add(
                PriceSnapshot(
                    steam_appid=data.steam_appid,
                    source_name=offer.source_name,
                    source_game_id=offer.source_game_id,
                    source_url=offer.source_url,
                    original_price=offer.original_price,
                    current_price=offer.current_price,
                    discount_percent=offer.discount_percent,
                    currency=offer.currency,
                    is_available=offer.is_available,
                )
            )
