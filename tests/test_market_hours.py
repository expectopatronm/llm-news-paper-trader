from datetime import datetime
from datetime import timezone
import unittest

from news_trader.market_hours import is_us_market_open


class MarketHoursTests(unittest.TestCase):
    def test_market_open_during_regular_hours(self):
        dt = datetime(2026, 5, 26, 14, 0, tzinfo=timezone.utc)
        self.assertTrue(is_us_market_open(dt))

    def test_market_closed_on_weekend(self):
        dt = datetime(2026, 5, 30, 14, 0, tzinfo=timezone.utc)
        self.assertFalse(is_us_market_open(dt))


if __name__ == "__main__":
    unittest.main()
