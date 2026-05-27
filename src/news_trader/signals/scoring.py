from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date

from news_trader.config import TradingConfig
from news_trader.signals.adaptive import AdaptiveState
from news_trader.signals.dip import evaluate_buy_the_dip
from news_trader.sources.event_calendar import UpcomingEvent
from news_trader.sources.market_data import MarketFeatures
from news_trader.storage import SourceItem


@dataclass(frozen=True)
class TradeSignal:
    ticker: str
    action: str
    confidence: float
    target_notional: float
    reason: str
    components: dict[str, float | str | None] = field(default_factory=dict)


SOURCE_RELIABILITY = {
    "sec_edgar": 0.24,
    "manual_calendar": 0.22,
    "event_calendar": 0.18,
    "company_ir": 0.24,
    "yahoo_rss": 0.14,
}

EVENT_IMPORTANCE = {
    "earnings": 0.22,
    "guidance": 0.24,
    "legal": 0.20,
    "analyst": 0.17,
    "product": 0.16,
    "capital_return": 0.16,
    "m_and_a": 0.22,
    "macro": 0.14,
    "filing": 0.10,
    "other": 0.08,
}

BULLISH = [
    "beat",
    "beats",
    "raises guidance",
    "raised guidance",
    "upgrade",
    "upgraded",
    "record revenue",
    "buyback",
    "repurchase",
    "dividend increase",
    "acquisition",
    "approval",
    "wins",
    "buy",
    "boost",
    "rebound",
    "record high",
    "cheap",
    "perfect time",
    "well-positioned",
    "demand",
    "expansion",
    "lead",
]

BEARISH = [
    "miss",
    "misses",
    "cuts guidance",
    "cut guidance",
    "downgrade",
    "downgraded",
    "investigation",
    "lawsuit",
    "probe",
    "antitrust",
    "subpoena",
    "resigns",
    "recall",
    "delay",
    "decline",
    "falls",
    "slump",
    "pressure",
    "risk",
    "warning",
    "struggling",
]


def build_signal(
    item: SourceItem,
    classification: dict,
    features: MarketFeatures,
    trading: TradingConfig,
    portfolio_equity: float,
    existing_quantity: float,
    upcoming_events: list[UpcomingEvent],
    adaptive: AdaptiveState | None = None,
) -> TradeSignal:
    adaptive = adaptive or AdaptiveState(0.0, 1.0, 1.0, "No adaptive review yet.")
    event_type = str(classification.get("event_type") or _event_type(item))
    source_score = SOURCE_RELIABILITY.get(item.source, 0.06)
    importance = EVENT_IMPORTANCE.get(event_type, EVENT_IMPORTANCE["other"])
    surprise = _surprise_score(item, classification)
    llm_conf = _bounded(float(classification.get("confidence", 0.5) or 0.5), 0, 1)
    price_confirmation = _price_confirmation(surprise, features)
    pead = _pead_score(event_type, surprise, features, trading.pead_follow_through_weight)
    priced_in_penalty = _priced_in_penalty(item, surprise, features, upcoming_events, trading.priced_in_penalty_weight)
    pre_event_boost = _pre_event_boost(item, upcoming_events)
    dip_signal = evaluate_buy_the_dip(item, classification, features, trading)

    confidence = _bounded(
        0.18
        + source_score
        + importance
        + (abs(surprise) * 0.14)
        + (llm_conf * 0.08)
        + price_confirmation
        + pead
        + pre_event_boost
        + dip_signal.confidence_boost
        - priced_in_penalty
        + adaptive.confidence_adjustment,
        0,
        1,
    )
    if dip_signal.active:
        confidence = max(confidence, min(0.74, trading.min_confidence + 0.02))
    direction = max(0.36, _direction(classification, surprise)) if dip_signal.active else _direction(classification, surprise)
    action = _action(direction, confidence, trading, existing_quantity)
    target_notional = _target_notional(confidence, trading, portfolio_equity, item.source) * adaptive.position_size_multiplier
    if dip_signal.active and action == "buy":
        target_notional *= dip_signal.position_multiplier
    if action == "hold":
        target_notional = 0.0

    reason = _reason(item, event_type, direction, confidence, price_confirmation, priced_in_penalty, pead, dip_signal.reason if dip_signal.active else None)
    return TradeSignal(
        ticker=item.ticker,
        action=action,
        confidence=confidence,
        target_notional=target_notional,
        reason=reason,
        components={
            "event_type": event_type,
            "source_score": round(source_score, 4),
            "event_importance": round(importance, 4),
            "surprise": round(surprise, 4),
            "llm_confidence": round(llm_conf, 4),
            "price_confirmation": round(price_confirmation, 4),
            "pead": round(pead, 4),
            "priced_in_penalty": round(priced_in_penalty, 4),
            "pre_event_boost": round(pre_event_boost, 4),
            "buy_dip_active": "true" if dip_signal.active else "false",
            "buy_dip_confidence_boost": round(dip_signal.confidence_boost, 4),
            "buy_dip_position_multiplier": round(dip_signal.position_multiplier, 4),
            "buy_dip_reason": dip_signal.reason,
            "adaptive_confidence_adjustment": round(adaptive.confidence_adjustment, 4),
            "adaptive_position_size_multiplier": round(adaptive.position_size_multiplier, 4),
            "adaptive_reason": adaptive.reason,
            "return_1d": _round_optional(features.return_1d),
            "return_5d": _round_optional(features.return_5d),
            "relative_return_5d_qqq": _round_optional(features.relative_return_5d_qqq),
            "volume_ratio_20d": _round_optional(features.volume_ratio_20d),
        },
    )


def _event_type(item: SourceItem) -> str:
    text = f"{item.title} {item.raw_text}".lower()
    if "earnings" in text or "eps" in text or "quarterly results" in text:
        return "earnings"
    if "guidance" in text or "outlook" in text:
        return "guidance"
    if any(word in text for word in ["lawsuit", "investigation", "probe", "antitrust", "subpoena"]):
        return "legal"
    if any(word in text for word in ["upgrade", "downgrade", "price target", "analyst"]):
        return "analyst"
    if any(word in text for word in ["buyback", "repurchase", "dividend"]):
        return "capital_return"
    if any(word in text for word in ["merger", "acquisition", "acquires", "takeover"]):
        return "m_and_a"
    if any(word in text for word in ["product", "launch", "chip", "ai", "export control"]):
        return "product"
    if item.source == "sec_edgar":
        return "filing"
    return "other"


def _surprise_score(item: SourceItem, classification: dict) -> float:
    bias = str(classification.get("directional_bias", "")).lower()
    if bias == "bullish":
        score = 0.55
    elif bias == "bearish":
        score = -0.55
    else:
        score = 0.0
    text = f"{item.title} {item.raw_text}".lower()
    score += 0.20 * sum(1 for word in BULLISH if word in text)
    score -= 0.20 * sum(1 for word in BEARISH if word in text)
    if "better than expected" in text or "above expectations" in text:
        score += 0.25
    if "worse than expected" in text or "below expectations" in text:
        score -= 0.25
    return _bounded(score, -1, 1)


def _direction(classification: dict, surprise: float) -> float:
    bias = str(classification.get("directional_bias", "")).lower()
    if bias == "bullish":
        return max(0.35, surprise)
    if bias == "bearish":
        return min(-0.35, surprise)
    return surprise


def _action(direction: float, confidence: float, trading: TradingConfig, existing_quantity: float) -> str:
    if confidence < trading.min_confidence or abs(direction) < 0.35:
        return "hold"
    if direction > 0:
        return "cover" if existing_quantity < 0 else "buy"
    if existing_quantity > 0:
        return "sell"
    return "short" if trading.allow_shorts else "hold"


def _target_notional(confidence: float, trading: TradingConfig, portfolio_equity: float, source: str) -> float:
    confidence_lift = max(0.0, confidence - trading.min_confidence)
    pct = trading.base_position_pct + min(0.10, confidence_lift * 0.35)
    if source in {"event_calendar", "manual_calendar"}:
        pct *= 0.5
    pct = min(pct, trading.max_position_pct)
    return max(0.0, portfolio_equity * pct)


def _price_confirmation(surprise: float, features: MarketFeatures) -> float:
    if surprise == 0 or features.return_1d is None:
        return 0.0
    volume_bonus = 0.03 if (features.volume_ratio_20d or 0) >= 1.2 else 0.0
    if surprise > 0 and features.return_1d > 0:
        return 0.05 + volume_bonus
    if surprise < 0 and features.return_1d < 0:
        return 0.05 + volume_bonus
    if abs(features.return_1d) > 0.03:
        return -0.03
    return 0.0


def _pead_score(event_type: str, surprise: float, features: MarketFeatures, weight: float) -> float:
    if event_type not in {"earnings", "guidance"} or surprise == 0:
        return 0.0
    if features.return_1d is None:
        return 0.0
    aligned = (surprise > 0 and features.return_1d > 0) or (surprise < 0 and features.return_1d < 0)
    return weight if aligned else 0.0


def _priced_in_penalty(
    item: SourceItem,
    surprise: float,
    features: MarketFeatures,
    upcoming_events: list[UpcomingEvent],
    weight: float,
) -> float:
    if surprise <= 0:
        return 0.0
    has_near_event = bool(_near_events(upcoming_events, days=5))
    runup = max(features.return_5d or 0.0, features.return_20d or 0.0, features.relative_return_5d_qqq or 0.0)
    if item.source in {"event_calendar", "manual_calendar"}:
        has_near_event = True
    if has_near_event and runup >= 0.06:
        return weight
    if runup >= 0.12:
        return weight * 0.75
    return 0.0


def _pre_event_boost(item: SourceItem, upcoming_events: list[UpcomingEvent]) -> float:
    if item.source in {"event_calendar", "manual_calendar"}:
        return 0.0
    return 0.03 if _near_events(upcoming_events, days=3) else 0.0


def _near_events(upcoming_events: list[UpcomingEvent], days: int) -> list[UpcomingEvent]:
    today = date.today()
    return [event for event in upcoming_events if 0 <= (event.date - today).days <= days]


def _reason(
    item: SourceItem,
    event_type: str,
    direction: float,
    confidence: float,
    price_confirmation: float,
    priced_in_penalty: float,
    pead: float,
    dip_reason: str | None = None,
) -> str:
    direction_text = "bullish" if direction > 0 else "bearish" if direction < 0 else "unclear"
    parts = [
        f"{item.source} {event_type} event classified as {direction_text}",
        f"confidence {confidence:.2f}",
    ]
    if price_confirmation > 0:
        parts.append("price/volume reaction confirms direction")
    if pead > 0:
        parts.append("earnings/guidance follow-through boost applied")
    if priced_in_penalty > 0:
        parts.append("priced-in run-up penalty applied")
    if dip_reason:
        parts.append(dip_reason)
    parts.append(item.title)
    return "; ".join(parts)


def _bounded(value: float, low: float, high: float) -> float:
    return max(low, min(high, value))


def _round_optional(value: float | None) -> float | None:
    return round(value, 4) if value is not None else None
