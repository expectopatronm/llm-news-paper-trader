import unittest

from news_trader.llm.schema import normalize_classification


class ClassificationSchemaTests(unittest.TestCase):
    def test_normalizer_preserves_source_event_ticker(self):
        classification = normalize_classification(
            {
                "ticker": "MSFT",
                "event_type": "product",
                "summary": "Supplier headline mentions another ticker.",
                "source_reliability": "medium",
                "market_relevance": 45,
                "directional_bias": "unclear",
                "confidence": 0.4,
                "requires_human_review": True,
                "evidence": ["ambiguous company reference"],
            },
            "AAPL",
            "yahoo_rss",
        )

        self.assertEqual(classification["ticker"], "AAPL")


if __name__ == "__main__":
    unittest.main()
