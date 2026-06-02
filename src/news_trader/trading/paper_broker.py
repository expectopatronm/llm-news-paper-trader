from __future__ import annotations

from dataclasses import dataclass

from news_trader.storage import Store


@dataclass(frozen=True)
class OrderResult:
    submitted: bool
    reason: str


class LocalPaperBroker:
    def __init__(self, store: Store, allow_fractional: bool):
        self.store = store
        self.allow_fractional = allow_fractional

    def submit(self, ticker: str, action: str, price: float | None, notional_usd: float, reason: str) -> OrderResult:
        if price is None or price <= 0:
            return OrderResult(False, "No valid market price available")
        action = action.lower()
        if action == "buy":
            return self._buy(ticker, price, notional_usd, reason)
        if action == "sell":
            return self._sell(ticker, price, notional_usd, reason)
        if action == "short":
            return self._short(ticker, price, notional_usd, reason)
        if action == "cover":
            return self._cover(ticker, price, notional_usd, reason)
        return OrderResult(False, "Decision was hold")

    def _buy(self, ticker: str, price: float, notional_usd: float, reason: str) -> OrderResult:
        cash = self.store.cash()
        notional = min(cash, notional_usd)
        if notional < 5:
            return OrderResult(False, "Not enough cash or position budget")
        qty = notional / price
        if not self.allow_fractional:
            qty = int(qty)
        if qty <= 0:
            return OrderResult(False, "Quantity rounded to zero")
        existing = self.store.position(ticker)
        old_qty = float(existing["quantity"]) if existing else 0.0
        if old_qty < 0:
            return OrderResult(False, "Existing short must be covered before opening a long")
        old_avg = float(existing["avg_price"]) if existing else 0.0
        new_qty = old_qty + qty
        new_avg = ((old_qty * old_avg) + (qty * price)) / new_qty
        self.store.set_cash(cash - qty * price)
        self.store.upsert_position(ticker, new_qty, new_avg)
        self.store.insert_trade(ticker, "buy", qty, price, reason)
        return OrderResult(True, f"Bought {qty:.4f} {ticker} at {price:.2f}")

    def _sell(self, ticker: str, price: float, notional_usd: float, reason: str) -> OrderResult:
        existing = self.store.position(ticker)
        if not existing:
            return OrderResult(False, "No existing position to sell")
        qty = float(existing["quantity"])
        if qty <= 0:
            return OrderResult(False, "No long position to sell")
        if notional_usd > 0:
            qty = min(qty, notional_usd / price)
            if not self.allow_fractional:
                qty = int(qty)
            if qty <= 0:
                return OrderResult(False, "Quantity rounded to zero")
        cash = self.store.cash()
        self.store.set_cash(cash + qty * price)
        remaining = float(existing["quantity"]) - qty
        self.store.upsert_position(ticker, remaining, float(existing["avg_price"]) if remaining > 0 else 0)
        self.store.insert_trade(ticker, "sell", qty, price, reason)
        return OrderResult(True, f"Sold {qty:.4f} {ticker} at {price:.2f}")

    def _short(self, ticker: str, price: float, notional_usd: float, reason: str) -> OrderResult:
        if notional_usd < 5:
            return OrderResult(False, "Short notional below budget")
        qty = notional_usd / price
        if not self.allow_fractional:
            qty = int(qty)
        if qty <= 0:
            return OrderResult(False, "Quantity rounded to zero")
        existing = self.store.position(ticker)
        old_qty = float(existing["quantity"]) if existing else 0.0
        if old_qty > 0:
            return OrderResult(False, "Existing long must be sold before opening a short")
        old_avg = float(existing["avg_price"]) if existing else 0.0
        new_qty = old_qty - qty
        new_avg = ((abs(old_qty) * old_avg) + (qty * price)) / abs(new_qty)
        cash = self.store.cash()
        self.store.set_cash(cash + qty * price)
        self.store.upsert_position(ticker, new_qty, new_avg)
        self.store.insert_trade(ticker, "short", -qty, price, reason)
        return OrderResult(True, f"Shorted {qty:.4f} {ticker} at {price:.2f}")

    def _cover(self, ticker: str, price: float, notional_usd: float, reason: str) -> OrderResult:
        existing = self.store.position(ticker)
        if not existing:
            return OrderResult(False, "No existing short to cover")
        qty = float(existing["quantity"])
        if qty >= 0:
            return OrderResult(False, "No short position to cover")
        cover_qty = abs(qty)
        if notional_usd > 0:
            cover_qty = min(cover_qty, notional_usd / price)
            if not self.allow_fractional:
                cover_qty = int(cover_qty)
            if cover_qty <= 0:
                return OrderResult(False, "Quantity rounded to zero")
        cost = cover_qty * price
        cash = self.store.cash()
        if cash < cost:
            return OrderResult(False, "Not enough cash to cover short")
        self.store.set_cash(cash - cost)
        remaining = float(existing["quantity"]) + cover_qty
        self.store.upsert_position(ticker, remaining, float(existing["avg_price"]) if remaining < 0 else 0)
        self.store.insert_trade(ticker, "cover", cover_qty, price, reason)
        return OrderResult(True, f"Covered {cover_qty:.4f} {ticker} at {price:.2f}")
