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


if __name__ == "__main__":
    unittest.main()
