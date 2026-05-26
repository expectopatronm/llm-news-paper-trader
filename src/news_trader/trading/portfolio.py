from __future__ import annotations

from dataclasses import dataclass

from news_trader.sources import market_data
from news_trader.storage import Store


@dataclass(frozen=True)
class PortfolioMark:
    cash: float
    equity: float
    gross_exposure: float
    prices: dict[str, float]


def mark_to_market(store: Store, price_overrides: dict[str, float | None] | None = None) -> PortfolioMark:
    cash = store.cash()
    equity = cash
    gross = 0.0
    prices: dict[str, float] = {}
    overrides = price_overrides or {}
    for row in store.all_positions():
        ticker = row["ticker"]
        price = overrides.get(ticker)
        if price is None:
            price = market_data.latest_price(ticker)
        if price is None:
            price = float(row["avg_price"])
        qty = float(row["quantity"])
        prices[ticker] = price
        equity += qty * price
        gross += abs(qty * price)
    return PortfolioMark(cash=cash, equity=equity, gross_exposure=gross, prices=prices)
