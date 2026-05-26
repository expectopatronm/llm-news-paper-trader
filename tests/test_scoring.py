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
            buy_dip_enabled=True,
            buy_dip_min_drop_1d=-0.03,
            buy_dip_min_relative_drop_spy=-0.02,
            buy_dip_min_relative_drop_qqq_5d=-0.03,
            buy_dip_volume_ratio_min=1.10,
            buy_dip_confidence_boost=0.18,
            buy_dip_position_multiplier=0.55,
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

    def test_buy_the_dip_can_buy_without_bullish_news(self):
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
            buy_dip_enabled=True,
            buy_dip_min_drop_1d=-0.03,
            buy_dip_min_relative_drop_spy=-0.02,
            buy_dip_min_relative_drop_qqq_5d=-0.03,
            buy_dip_volume_ratio_min=1.10,
            buy_dip_confidence_boost=0.18,
            buy_dip_position_multiplier=0.55,
        )
        item = SourceItem(
            ticker="AAPL",
            source="yahoo_rss",
            source_id="dip",
            title="Apple shares fall despite no company-specific thesis break",
            url="https://example.com",
            published_at="2026-05-26",
            raw_text="Shares fell with broad concern, but no guidance cut or regulatory filing was cited.",
        )
        features = MarketFeatures(
            symbol="AAPL",
            latest_price=100.0,
            return_1d=-0.045,
            return_5d=-0.06,
            return_20d=0.02,
            relative_return_1d_spy=-0.032,
            relative_return_5d_spy=-0.04,
            relative_return_5d_qqq=-0.05,
            volume_ratio_20d=1.35,
        )
        signal = build_signal(
            item,
            {"event_type": "other", "directional_bias": "unclear", "confidence": 0.5, "source_reliability": "medium"},
            features,
            trading,
            portfolio_equity=1000.0,
            existing_quantity=0.0,
            upcoming_events=[],
        )
        self.assertEqual(signal.action, "buy")
        self.assertEqual(signal.components["buy_dip_active"], "true")
        self.assertGreater(signal.target_notional, 0)

    def test_buy_the_dip_blocks_bearish_thesis_break(self):
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
            buy_dip_enabled=True,
            buy_dip_min_drop_1d=-0.03,
            buy_dip_min_relative_drop_spy=-0.02,
            buy_dip_min_relative_drop_qqq_5d=-0.03,
            buy_dip_volume_ratio_min=1.10,
            buy_dip_confidence_boost=0.18,
            buy_dip_position_multiplier=0.55,
        )
        item = SourceItem(
            ticker="AAPL",
            source="sec_edgar",
            source_id="bad-dip",
            title="Apple files 8-K after cutting guidance",
            url="https://example.com",
            published_at="2026-05-26",
            raw_text="The company cuts guidance.",
        )
        features = MarketFeatures(
            symbol="AAPL",
            latest_price=100.0,
            return_1d=-0.06,
            return_5d=-0.08,
            return_20d=-0.01,
            relative_return_1d_spy=-0.05,
            relative_return_5d_spy=-0.06,
            relative_return_5d_qqq=-0.07,
            volume_ratio_20d=1.8,
        )
        signal = build_signal(
            item,
            {"event_type": "guidance", "directional_bias": "bearish", "confidence": 0.8, "source_reliability": "high"},
            features,
            trading,
            portfolio_equity=1000.0,
            existing_quantity=0.0,
            upcoming_events=[],
        )
        self.assertEqual(signal.components["buy_dip_active"], "false")
        self.assertNotEqual(signal.action, "buy")


if __name__ == "__main__":
    unittest.main()
