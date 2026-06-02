from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from news_trader.storage import Store
from news_trader.trading.paper_broker import LocalPaperBroker
from news_trader.trading.portfolio import mark_to_market


class BrokerTests(unittest.TestCase):
    def test_short_and_cover_updates_equity(self):
        with TemporaryDirectory() as tmp:
            store = Store(Path(tmp) / "bot.sqlite", 1000.0)
            try:
                broker = LocalPaperBroker(store, allow_fractional=True)

                short = broker.submit("AAPL", "short", 100.0, 200.0, "test short")
                self.assertTrue(short.submitted)
                mark = mark_to_market(store, {"AAPL": 90.0})
                self.assertAlmostEqual(mark.equity, 1020.0)

                cover = broker.submit("AAPL", "cover", 90.0, 0.0, "test cover")
                self.assertTrue(cover.submitted)
                self.assertIsNone(store.position("AAPL"))
                self.assertAlmostEqual(store.cash(), 1020.0)
            finally:
                store.close()

    def test_partial_sell_and_cover_reduce_positions(self):
        with TemporaryDirectory() as tmp:
            store = Store(Path(tmp) / "bot.sqlite", 1000.0)
            try:
                broker = LocalPaperBroker(store, allow_fractional=True)

                buy = broker.submit("MSFT", "buy", 100.0, 400.0, "open long")
                self.assertTrue(buy.submitted)
                sell = broker.submit("MSFT", "sell", 100.0, 150.0, "trim long")
                self.assertTrue(sell.submitted)
                long_position = store.position("MSFT")
                self.assertIsNotNone(long_position)
                self.assertAlmostEqual(float(long_position["quantity"]), 2.5)

                short = broker.submit("AAPL", "short", 50.0, 200.0, "open short")
                self.assertTrue(short.submitted)
                cover = broker.submit("AAPL", "cover", 50.0, 75.0, "trim short")
                self.assertTrue(cover.submitted)
                short_position = store.position("AAPL")
                self.assertIsNotNone(short_position)
                self.assertAlmostEqual(float(short_position["quantity"]), -2.5)
            finally:
                store.close()


if __name__ == "__main__":
    unittest.main()
