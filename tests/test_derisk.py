from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from news_trader.config import TradingConfig
from news_trader.signals.derisk import apply_drawdown_derisk
from news_trader.storage import Store
from news_trader.trading.paper_broker import LocalPaperBroker
from news_trader.trading.portfolio import mark_to_market


def trading_config() -> TradingConfig:
    return TradingConfig(
        starting_cash_usd=1000.0,
        base_position_pct=0.15,
        max_position_pct=0.30,
        max_short_position_pct=0.25,
        max_gross_exposure_pct=1.50,
        max_new_trades_per_day=0,
        min_confidence=0.55,
        max_drawdown_pct=0.10,
        allow_shorts=True,
        allow_fractional=True,
        min_notional_usd=10.0,
        paper_broker="local",
        pead_follow_through_weight=0.10,
        priced_in_penalty_weight=0.10,
        buy_dip_enabled=True,
        buy_dip_min_drop_1d=-0.025,
        buy_dip_min_relative_drop_spy=-0.015,
        buy_dip_min_relative_drop_qqq_5d=-0.025,
        buy_dip_volume_ratio_min=1.05,
        buy_dip_confidence_boost=0.22,
        buy_dip_position_multiplier=0.70,
        derisk_enabled=True,
        derisk_drawdown_pct=0.03,
        derisk_target_gross_exposure_pct=1.10,
        derisk_step_exposure_pct=0.25,
        derisk_min_position_loss_pct=0.01,
    )


class DeriskTests(unittest.TestCase):
    def test_drawdown_derisk_trims_losing_position(self):
        with TemporaryDirectory() as tmp:
            store = Store(Path(tmp) / "bot.sqlite", 1000.0)
            try:
                broker = LocalPaperBroker(store, allow_fractional=True)
                self.assertTrue(broker.submit("AAPL", "buy", 100.0, 500.0, "open long").submitted)
                self.assertTrue(broker.submit("MSFT", "short", 100.0, 500.0, "open short").submitted)
                store.set_state("peak_equity_usd", "1100.0")
                mark = mark_to_market(store, {"AAPL": 80.0, "MSFT": 120.0})

                result = apply_drawdown_derisk(store, broker, trading_config(), mark)

                self.assertTrue(result.triggered)
                self.assertTrue(result.submitted)
                self.assertLess(result.mark.gross_exposure, mark.gross_exposure)
                position = store.position("AAPL")
                self.assertIsNotNone(position)
                self.assertLess(float(position["quantity"]), 5.0)
            finally:
                store.close()

    def test_derisk_does_not_fire_below_drawdown_threshold(self):
        with TemporaryDirectory() as tmp:
            store = Store(Path(tmp) / "bot.sqlite", 1000.0)
            try:
                broker = LocalPaperBroker(store, allow_fractional=True)
                self.assertTrue(broker.submit("AAPL", "buy", 100.0, 500.0, "open long").submitted)
                store.set_state("peak_equity_usd", "1000.0")
                mark = mark_to_market(store, {"AAPL": 99.0})

                result = apply_drawdown_derisk(store, broker, trading_config(), mark)

                self.assertFalse(result.triggered)
                self.assertFalse(result.submitted)
            finally:
                store.close()


if __name__ == "__main__":
    unittest.main()
