from __future__ import annotations

from dataclasses import dataclass

from news_trader.config import TradingConfig
from news_trader.sources.market_data import MarketFeatures
from news_trader.storage import SourceItem


@dataclass(frozen=True)
class DipSignal:
    active: bool
    confidence_boost: float
    position_multiplier: float
    reason: str


HIGH_RELIABILITY_BEARISH_EVENTS = {"filing", "guidance", "legal", "earnings"}


def evaluate_buy_the_dip(
    item: SourceItem,
    classification: dict,
    features: MarketFeatures,
    trading: TradingConfig,
) -> DipSignal:
    if not trading.buy_dip_enabled:
        return DipSignal(False, 0.0, 1.0, "Buy-the-dip module disabled.")
    if str(classification.get("directional_bias", "")).lower() == "bearish":
        return DipSignal(False, 0.0, 1.0, "Bearish classification blocks dip buying.")
    event_type = str(classification.get("event_type", "other")).lower()
    source_reliability = str(classification.get("source_reliability", "")).lower()
    if source_reliability == "high" and event_type in HIGH_RELIABILITY_BEARISH_EVENTS:
        return DipSignal(False, 0.0, 1.0, "High-reliability event could be thesis-breaking.")
    if features.return_1d is None or features.relative_return_1d_spy is None:
        return DipSignal(False, 0.0, 1.0, "Insufficient daily market context for dip signal.")
    dropped_enough = features.return_1d <= trading.buy_dip_min_drop_1d
    underperformed_spy = features.relative_return_1d_spy <= trading.buy_dip_min_relative_drop_spy
    underperformed_qqq = (features.relative_return_5d_qqq or 0.0) <= trading.buy_dip_min_relative_drop_qqq_5d
    volume_confirmation = (features.volume_ratio_20d or 0.0) >= trading.buy_dip_volume_ratio_min
    if not (dropped_enough and underperformed_spy and (underperformed_qqq or volume_confirmation)):
        return DipSignal(False, 0.0, 1.0, "Dip did not clear drop, relative weakness, and volume/context thresholds.")
    return DipSignal(
        True,
        trading.buy_dip_confidence_boost,
        trading.buy_dip_position_multiplier,
        "Potential overreaction dip: sharp 1-day drop, market underperformance, no high-reliability bearish thesis break.",
    )
