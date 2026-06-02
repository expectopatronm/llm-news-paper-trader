from __future__ import annotations

from dataclasses import dataclass

from news_trader.config import TradingConfig
from news_trader.storage import Store
from news_trader.trading.paper_broker import LocalPaperBroker
from news_trader.trading.portfolio import PortfolioMark, mark_to_market


@dataclass(frozen=True)
class DeriskResult:
    triggered: bool
    submitted: bool
    reason: str
    mark: PortfolioMark


@dataclass(frozen=True)
class PositionRisk:
    ticker: str
    quantity: float
    avg_price: float
    price: float
    notional: float
    open_pnl: float
    loss_pct: float


def apply_drawdown_derisk(
    store: Store,
    broker: LocalPaperBroker,
    trading: TradingConfig,
    mark: PortfolioMark,
) -> DeriskResult:
    if not trading.derisk_enabled:
        return DeriskResult(False, False, "De-risking disabled", mark)
    if mark.equity <= 0:
        return DeriskResult(False, False, "No positive equity", mark)

    peak = float(store.get_state("peak_equity_usd") or mark.equity)
    drawdown = max(0.0, (peak - mark.equity) / peak) if peak > 0 else 0.0
    target_gross = mark.equity * trading.derisk_target_gross_exposure_pct
    excess_gross = mark.gross_exposure - target_gross
    if drawdown < trading.derisk_drawdown_pct:
        return DeriskResult(False, False, f"Drawdown {drawdown:.2%} below de-risk threshold", mark)
    if excess_gross <= trading.min_notional_usd:
        return DeriskResult(False, False, "Drawdown active but gross exposure is already near target", mark)

    candidates = _position_risks(store, mark.prices)
    if not candidates:
        return DeriskResult(True, False, "Drawdown active but no positions are available to reduce", mark)

    losing = [pos for pos in candidates if pos.loss_pct <= -trading.derisk_min_position_loss_pct]
    ranked = sorted(losing or candidates, key=lambda pos: (pos.loss_pct, -pos.notional))
    step_notional = min(excess_gross, mark.equity * trading.derisk_step_exposure_pct)
    for pos in ranked:
        action = "sell" if pos.quantity > 0 else "cover"
        notional = min(pos.notional, step_notional)
        if action == "cover":
            notional = min(notional, store.cash())
        if notional < trading.min_notional_usd:
            continue
        reason = (
            f"automatic de-risk: drawdown {drawdown:.2%} from peak ${peak:.2f}; "
            f"gross exposure {mark.gross_exposure / mark.equity:.2f}x above target "
            f"{trading.derisk_target_gross_exposure_pct:.2f}x; "
            f"trimming {pos.ticker} open P/L ${pos.open_pnl:.2f}"
        )
        result = broker.submit(pos.ticker, action, pos.price, notional, reason)
        updated = mark_to_market(store, mark.prices)
        if result.submitted:
            return DeriskResult(True, True, result.reason, updated)
        return DeriskResult(True, False, result.reason, updated)

    return DeriskResult(True, False, "Drawdown active but no reducible notional passed minimum/cash checks", mark)


def _position_risks(store: Store, prices: dict[str, float]) -> list[PositionRisk]:
    risks: list[PositionRisk] = []
    for row in store.all_positions():
        ticker = row["ticker"]
        price = prices.get(ticker)
        if price is None or price <= 0:
            continue
        quantity = float(row["quantity"])
        avg_price = float(row["avg_price"])
        if avg_price <= 0 or abs(quantity) <= 0:
            continue
        open_pnl = (price - avg_price) * quantity
        notional = abs(quantity * price)
        if quantity > 0:
            loss_pct = (price / avg_price) - 1.0
        else:
            loss_pct = (avg_price / price) - 1.0
        risks.append(PositionRisk(ticker, quantity, avg_price, price, notional, open_pnl, loss_pct))
    return risks
