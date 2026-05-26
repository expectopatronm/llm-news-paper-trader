from __future__ import annotations

import csv
from dataclasses import dataclass
from functools import lru_cache
from io import StringIO

from news_trader.sources.http import fetch_text


@dataclass(frozen=True)
class MarketBar:
    date: str
    open: float
    high: float
    low: float
    close: float
    volume: float


@dataclass(frozen=True)
class MarketFeatures:
    symbol: str
    latest_price: float | None
    return_1d: float | None
    return_5d: float | None
    return_20d: float | None
    relative_return_1d_spy: float | None
    relative_return_5d_spy: float | None
    relative_return_5d_qqq: float | None
    volume_ratio_20d: float | None


def _stooq_symbol(symbol: str) -> str:
    return symbol.replace(".", "-").lower() + ".us"


@lru_cache(maxsize=128)
def latest_price(symbol: str) -> float | None:
    url = f"https://stooq.com/q/l/?s={_stooq_symbol(symbol)}&f=sd2t2ohlcv&h&e=csv"
    text = fetch_text(url, {"User-Agent": "llm-news-paper-trader/0.1"})
    rows = list(csv.DictReader(StringIO(text)))
    if not rows:
        return None
    close = rows[0].get("Close")
    if not close or close == "N/D":
        bars = daily_history(symbol, limit=1)
        return bars[-1].close if bars else None
    return _safe_float(close)


@lru_cache(maxsize=128)
def daily_history(symbol: str, limit: int = 80) -> list[MarketBar]:
    url = f"https://stooq.com/q/d/l/?s={_stooq_symbol(symbol)}&i=d"
    text = fetch_text(url, {"User-Agent": "llm-news-paper-trader/0.1"})
    bars: list[MarketBar] = []
    for row in csv.DictReader(StringIO(text)):
        close = _safe_float(row.get("Close"))
        open_ = _safe_float(row.get("Open"))
        high = _safe_float(row.get("High"))
        low = _safe_float(row.get("Low"))
        volume = _safe_float(row.get("Volume"))
        if close is None or open_ is None or high is None or low is None or volume is None:
            continue
        bars.append(MarketBar(row["Date"], open_, high, low, close, volume))
    return bars[-limit:]


def market_features(symbol: str) -> MarketFeatures:
    bars = daily_history(symbol)
    spy = daily_history("SPY")
    qqq = daily_history("QQQ")

    return_1d = _return_over(bars, 1)
    return_5d = _return_over(bars, 5)
    return_20d = _return_over(bars, 20)
    spy_1d = _return_over(spy, 1)
    spy_5d = _return_over(spy, 5)
    qqq_5d = _return_over(qqq, 5)

    return MarketFeatures(
        symbol=symbol,
        latest_price=bars[-1].close if bars else latest_price(symbol),
        return_1d=return_1d,
        return_5d=return_5d,
        return_20d=return_20d,
        relative_return_1d_spy=_diff(return_1d, spy_1d),
        relative_return_5d_spy=_diff(return_5d, spy_5d),
        relative_return_5d_qqq=_diff(return_5d, qqq_5d),
        volume_ratio_20d=_volume_ratio(bars, 20),
    )


def _safe_float(value: str | None) -> float | None:
    if value in {None, "", "N/D"}:
        return None
    try:
        return float(value)
    except ValueError:
        return None


def _return_over(bars: list[MarketBar], days: int) -> float | None:
    if len(bars) <= days:
        return None
    start = bars[-days - 1].close
    end = bars[-1].close
    if start <= 0:
        return None
    return (end / start) - 1.0


def _volume_ratio(bars: list[MarketBar], days: int) -> float | None:
    if len(bars) <= days:
        return None
    prior = [bar.volume for bar in bars[-days - 1 : -1] if bar.volume > 0]
    if not prior:
        return None
    avg = sum(prior) / len(prior)
    if avg <= 0:
        return None
    return bars[-1].volume / avg


def _diff(left: float | None, right: float | None) -> float | None:
    if left is None or right is None:
        return None
    return left - right
