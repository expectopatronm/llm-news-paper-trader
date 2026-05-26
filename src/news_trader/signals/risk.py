from __future__ import annotations

from dataclasses import dataclass
from datetime import date

from news_trader.config import TradingConfig
from news_trader.signals.adaptive import AdaptiveState
from news_trader.signals.scoring import TradeSignal
from news_trader.storage import Store


@dataclass(frozen=True)
class RiskDecision:
    allowed: bool
    notional: float
    reason: str


class RiskEngine:
    def __init__(self, store: Store, trading: TradingConfig, adaptive: AdaptiveState | None = None):
        self.store = store
        self.trading = trading
        self.adaptive = adaptive or AdaptiveState(0.0, 1.0, 1.0, "No adaptive review yet.")

    def evaluate(self, signal: TradeSignal, price: float | None, equity: float, gross_exposure: float) -> RiskDecision:
        if signal.action == "hold":
            return RiskDecision(False, 0.0, "Signal is hold")
        if price is None or price <= 0:
            return RiskDecision(False, 0.0, "No valid price")
        if signal.confidence < self.trading.min_confidence:
            return RiskDecision(False, 0.0, "Signal confidence below threshold")
        if signal.action == "short" and not self.trading.allow_shorts:
            return RiskDecision(False, 0.0, "Shorting is disabled")
        if self._drawdown(equity) >= self.trading.max_drawdown_pct:
            return RiskDecision(False, 0.0, "Drawdown limit reached")
        if self._trades_today() >= self.trading.max_new_trades_per_day > 0:
            return RiskDecision(False, 0.0, "Daily trade limit reached")

        max_pct = self.trading.max_short_position_pct if signal.action == "short" else self.trading.max_position_pct
        notional = min(signal.target_notional, equity * max_pct)
        if signal.action in {"sell", "cover"}:
            notional = signal.target_notional
        if signal.action in {"buy", "short"} and notional < self.trading.min_notional_usd:
            return RiskDecision(False, 0.0, "Notional below minimum")

        projected_gross = gross_exposure
        if signal.action in {"buy", "short"}:
            projected_gross += notional
        max_gross = equity * self.trading.max_gross_exposure_pct * self.adaptive.max_gross_exposure_multiplier
        if projected_gross > max_gross:
            return RiskDecision(False, 0.0, "Gross exposure cap reached")
        return RiskDecision(True, notional, "Risk checks passed")

    def update_peak_equity(self, equity: float) -> None:
        peak = float(self.store.get_state("peak_equity_usd") or equity)
        if equity > peak:
            self.store.set_state("peak_equity_usd", f"{equity:.6f}")
        elif self.store.get_state("peak_equity_usd") is None:
            self.store.set_state("peak_equity_usd", f"{peak:.6f}")

    def _drawdown(self, equity: float) -> float:
        peak = float(self.store.get_state("peak_equity_usd") or equity)
        if peak <= 0:
            return 0.0
        return max(0.0, (peak - equity) / peak)

    def _trades_today(self) -> int:
        today_prefix = date.today().isoformat()
        row = self.store.conn.execute(
            "select count(*) as n from trades where substr(created_at, 1, 10) = ?",
            (today_prefix,),
        ).fetchone()
        return int(row["n"])
