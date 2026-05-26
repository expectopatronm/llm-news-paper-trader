import unittest

from news_trader.config import TradingConfig
from news_trader.signals.scoring import build_signal
from news_trader.sources.market_data import MarketFeatures
from news_trader.storage import SourceItem


class ScoringTests(unittest.TestCase):
    def test_positive_earnings_surprise_can_buy(self):
        trading = TradingConfig(
            starting_cash_usd=1000.0,
            base_position_pct=0.12,
            max_position_pct=0.25,
            max_short_position_pct=0.20,
            max_gross_exposure_pct=1.25,
            max_new_trades_per_day=0,
            min_confidence=0.68,
            max_drawdown_pct=0.10,
            allow_shorts=True,
            allow_fractional=True,
            min_notional_usd=10.0,
            paper_broker="local",
            pead_follow_through_weight=0.08,
            priced_in_penalty_weight=0.12,
        )
        item = SourceItem(
            ticker="NVDA",
            source="yahoo_rss",
            source_id="1",
            title="NVIDIA beats expectations and raises guidance",
            url="https://example.com",
            published_at="2026-05-25",
            raw_text="Revenue beat expectations and the company raises guidance.",
        )
        features = MarketFeatures(
            symbol="NVDA",
            latest_price=100.0,
            return_1d=0.03,
            return_5d=0.01,
            return_20d=0.04,
            relative_return_1d_spy=0.02,
            relative_return_5d_spy=0.01,
            relative_return_5d_qqq=0.0,
            volume_ratio_20d=1.5,
        )
        signal = build_signal(
            item,
            {"event_type": "earnings", "directional_bias": "bullish", "confidence": 0.72},
            features,
            trading,
            portfolio_equity=1000.0,
            existing_quantity=0.0,
            upcoming_events=[],
        )
        self.assertEqual(signal.action, "buy")
        self.assertGreaterEqual(signal.confidence, trading.min_confidence)


if __name__ == "__main__":
    unittest.main()
