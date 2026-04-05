from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..config import Settings
from ..models import AlertEvent, PriceSnapshot, WatchItem, utc_now
from ..schemas import DecisionResponse
from .notifications import EmailNotifier


class AlertService:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings

    def evaluate_and_send(
        self,
        session: Session,
        watch_item: WatchItem,
        decision: DecisionResponse,
        notifier: EmailNotifier,
    ) -> list[AlertEvent]:
        if decision.current_price is None:
            return []

        candidates: list[tuple[str, str, Decimal | None]] = []
        current_price = decision.current_price
        if decision.target_price is not None and current_price <= decision.target_price:
            candidates.append(
                (
                    "target_price_reached",
                    f"{watch_item.game.title} 当前 {current_price} 元，已经低于你的目标价 {decision.target_price} 元。",
                    current_price,
                )
            )
        if (
            decision.historical_low_180d is not None
            and current_price <= decision.historical_low_180d
        ):
            candidates.append(
                (
                    "new_monitoring_low",
                    f"{watch_item.game.title} 刷新了监控期内新低，目前为 {current_price} 元。",
                    current_price,
                )
            )
        if self._entered_significant_discount(session, watch_item.steam_appid):
            candidates.append(
                (
                    "significant_discount",
                    f"{watch_item.game.title} 首次进入显著折扣区间，值得重点关注。",
                    current_price,
                )
            )
        if watch_item.last_decision_status != "Buy" and decision.status == "Buy":
            candidates.append(
                (
                    "decision_upgrade",
                    f"{watch_item.game.title} 的建议已从观望升级为值得购买。",
                    current_price,
                )
            )

        events: list[AlertEvent] = []
        for alert_type, message, price_amount in candidates:
            fingerprint = f"{watch_item.steam_appid}:{alert_type}:{price_amount}"
            if self._is_duplicate(session, fingerprint):
                continue
            event = AlertEvent(
                steam_appid=watch_item.steam_appid,
                watch_item_id=watch_item.id,
                alert_type=alert_type,
                alert_key=f"{alert_type}:{watch_item.steam_appid}",
                fingerprint=fingerprint,
                message=message,
                price_amount=price_amount,
                status="pending",
            )
            session.add(event)
            session.flush()
            self._deliver(event, notifier, watch_item.game.title)
            events.append(event)
        return events

    def retry_failed(self, session: Session, alert_id: int, notifier: EmailNotifier) -> AlertEvent:
        event = session.get(AlertEvent, alert_id)
        if event is None:
            raise ValueError(f"Unknown alert id {alert_id}")
        self._deliver(event, notifier, event.game.title)
        session.commit()
        return event

    def _deliver(self, event: AlertEvent, notifier: EmailNotifier, title: str) -> None:
        try:
            if notifier.enabled:
                notifier.send(f"[Steam Price Monitor] {title}", event.message)
                event.status = "sent"
                event.sent_at = utc_now()
                event.last_error = None
            else:
                event.status = "pending"
                event.last_error = None
        except Exception as exc:  # pragma: no cover
            event.status = "failed"
            event.last_error = str(exc)
            event.sent_at = None

    def _is_duplicate(self, session: Session, fingerprint: str) -> bool:
        threshold = datetime.now(UTC).replace(tzinfo=None) - timedelta(
            hours=self.settings.alert_cooldown_hours
        )
        existing = session.scalars(
            select(AlertEvent).where(
                AlertEvent.fingerprint == fingerprint,
                AlertEvent.triggered_at >= threshold,
            )
        ).first()
        return existing is not None

    def _entered_significant_discount(self, session: Session, steam_appid: int) -> bool:
        snapshots = session.scalars(
            select(PriceSnapshot)
            .where(PriceSnapshot.steam_appid == steam_appid)
            .order_by(PriceSnapshot.observed_at.desc())
        ).all()
        if len(snapshots) < 2:
            return False
        latest = snapshots[0]
        previous = next(
            (
                snapshot
                for snapshot in snapshots[1:]
                if snapshot.source_name == latest.source_name
            ),
            None,
        )
        if previous is None:
            return latest.discount_percent >= 50
        return latest.discount_percent >= 50 and previous.discount_percent < 50
