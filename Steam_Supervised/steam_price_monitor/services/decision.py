from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from decimal import Decimal

from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from ..models import GameCanonical, PriceSnapshot, WatchItem
from ..schemas import DecisionResponse, EditionRecommendation


ZERO = Decimal("0.00")


def _as_naive_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value
    return value.astimezone(UTC).replace(tzinfo=None)


@dataclass(slots=True)
class VariantState:
    game: GameCanonical
    current_snapshot: PriceSnapshot | None
    historical_low_90d: Decimal | None
    historical_low_180d: Decimal | None
    normalized_price: Decimal | None
    recent_sample_count_180d: int


class DecisionService:
    def evaluate(
        self, session: Session, steam_appid: int, watch_item: WatchItem | None = None
    ) -> DecisionResponse:
        game = session.get(GameCanonical, steam_appid)
        if game is None:
            raise ValueError(f"Unknown Steam appid {steam_appid}")

        variants = self._collect_variants(session, game)
        variant_states = [self._variant_state(session, variant) for variant in variants]
        current_state = next(
            (state for state in variant_states if state.game.steam_appid == steam_appid),
            None,
        )
        if current_state is None:
            current_state = VariantState(
                game=game,
                current_snapshot=None,
                historical_low_90d=None,
                historical_low_180d=None,
                normalized_price=None,
                recent_sample_count_180d=0,
            )

        recommended = min(
            (
                state
                for state in variant_states
                if state.current_snapshot is not None
                and state.current_snapshot.current_price is not None
            ),
            key=lambda state: (
                state.normalized_price is None,
                state.normalized_price or Decimal("999999"),
                state.current_snapshot.current_price,
            ),
            default=current_state,
        )

        target_price = watch_item.target_price if watch_item else None
        current_price = (
            current_state.current_snapshot.current_price if current_state.current_snapshot else None
        )
        current_discount = (
            current_state.current_snapshot.discount_percent if current_state.current_snapshot else 0
        )
        low_180 = current_state.historical_low_180d
        low_90 = current_state.historical_low_90d
        gap = (
            (current_price - low_180).quantize(Decimal("0.01"))
            if current_price is not None and low_180 is not None
            else None
        )
        near_low_margin = (
            max(Decimal("3.00"), (low_180 * Decimal("0.05")).quantize(Decimal("0.01")))
            if low_180 is not None
            else Decimal("3.00")
        )
        is_near_low = bool(
            current_price is not None
            and low_180 is not None
            and current_price <= low_180 + near_low_margin
        )
        meets_target = bool(
            current_price is not None
            and target_price is not None
            and current_price <= target_price
        )

        enough_history = current_state.recent_sample_count_180d >= 2

        if current_price is None:
            status = "Watch"
            reason = "当前还没有可用价格数据，系统会继续定时检测。"
        elif meets_target and (is_near_low or not enough_history):
            status = "Buy"
            reason = (
                f"当前 {current_price} 元，已低于你的目标价 {target_price} 元，满足入手条件。"
            )
        elif enough_history and is_near_low and (
            current_discount >= 25 or current_price == low_180
        ):
            status = "Buy"
            reason = f"当前 {current_price} 元，已达到监控期内低位区间，适合入手。"
        elif current_discount > 0:
            status = "Wait"
            if gap is not None and gap > ZERO:
                reason = (
                    f"当前 {current_price} 元，较近 180 天最低价高 {gap} 元，先加入候选更稳妥。"
                )
            else:
                reason = f"当前 {current_price} 元，虽然有折扣，但还没到明确的最佳买点。"
        else:
            status = "Watch"
            if target_price is not None:
                reason = f"当前 {current_price} 元，尚未触达你的目标价 {target_price} 元。"
            else:
                reason = "当前没有足够强的折扣信号，继续观察后续促销窗口。"

        alternatives = [
            EditionRecommendation(
                steam_appid=state.game.steam_appid,
                title=state.game.title,
                edition_label=state.game.edition_label,
                current_price=state.current_snapshot.current_price
                if state.current_snapshot
                else None,
                historical_low_90d=state.historical_low_90d,
                historical_low_180d=state.historical_low_180d,
                discount_percent=state.current_snapshot.discount_percent
                if state.current_snapshot
                else 0,
                best_source=state.current_snapshot.source_name if state.current_snapshot else None,
                value_score=state.game.value_score,
                normalized_price=state.normalized_price,
            )
            for state in sorted(
                variant_states,
                key=lambda state: (
                    state.normalized_price is None,
                    state.normalized_price or Decimal("999999"),
                    state.game.title,
                ),
            )
        ]

        recommended_snapshot = recommended.current_snapshot if recommended else None
        return DecisionResponse(
            steam_appid=steam_appid,
            title=game.title,
            status=status,
            reason=reason,
            current_price=current_price,
            currency=current_state.current_snapshot.currency
            if current_state.current_snapshot
            else None,
            historical_low_90d=low_90,
            historical_low_180d=low_180,
            delta_to_180d_low=gap,
            target_price=target_price,
            recommended_purchase_appid=recommended.game.steam_appid if recommended else None,
            recommended_purchase_title=recommended.game.title if recommended else None,
            recommended_source=recommended_snapshot.source_name if recommended_snapshot else None,
            alternatives=alternatives,
        )

    def _collect_variants(self, session: Session, game: GameCanonical) -> list[GameCanonical]:
        root_appid = game.base_game_appid or game.steam_appid
        variants = session.scalars(
            select(GameCanonical).where(
                or_(
                    GameCanonical.steam_appid == root_appid,
                    GameCanonical.base_game_appid == root_appid,
                )
            )
        ).all()
        if not variants:
            return [game]
        unique = {variant.steam_appid: variant for variant in variants}
        if game.steam_appid not in unique:
            unique[game.steam_appid] = game
        return list(unique.values())

    def _variant_state(self, session: Session, variant: GameCanonical) -> VariantState:
        snapshots = session.scalars(
            select(PriceSnapshot)
            .where(PriceSnapshot.steam_appid == variant.steam_appid)
            .order_by(PriceSnapshot.observed_at.desc())
        ).all()
        latest_per_source: dict[str, PriceSnapshot] = {}
        for snapshot in snapshots:
            latest_per_source.setdefault(snapshot.source_name, snapshot)

        current_snapshot = min(
            (
                snapshot
                for snapshot in latest_per_source.values()
                if snapshot.current_price is not None
            ),
            key=lambda snapshot: snapshot.current_price,
            default=None,
        )
        now = datetime.now(UTC).replace(tzinfo=None)
        ninety_days = now - timedelta(days=90)
        one_eighty_days = now - timedelta(days=180)
        recent_90 = [
            snapshot.current_price
            for snapshot in snapshots
            if snapshot.current_price is not None
            and _as_naive_utc(snapshot.observed_at) >= ninety_days
        ]
        recent_180 = [
            snapshot.current_price
            for snapshot in snapshots
            if snapshot.current_price is not None
            and _as_naive_utc(snapshot.observed_at) >= one_eighty_days
        ]
        low_90 = min(recent_90) if recent_90 else None
        low_180 = min(recent_180) if recent_180 else None
        normalized = None
        if current_snapshot is not None and current_snapshot.current_price is not None:
            normalized = (
                current_snapshot.current_price / (variant.value_score or Decimal("1.00"))
            ).quantize(Decimal("0.01"))
        return VariantState(
            game=variant,
            current_snapshot=current_snapshot,
            historical_low_90d=low_90,
            historical_low_180d=low_180,
            normalized_price=normalized,
            recent_sample_count_180d=len(recent_180),
        )
