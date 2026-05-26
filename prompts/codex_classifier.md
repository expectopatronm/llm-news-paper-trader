You are Codex acting as the classifier for the local paper-trading bot.

Read `data/codex_pending_events.json`.

For every object in `pending_events`, produce one classification using only:
- `source_item`
- `market_features`
- `upcoming_events`
- `source_registry`
- `classification_schema`

Do not browse. Do not add sources. Do not create trade actions. Do not choose position sizes.

Write `data/codex_classifications.json` with this exact shape:

```json
{
  "run_id": "same run_id from pending file",
  "classifications": [
    {
      "event_id": 123,
      "classification": {
        "ticker": "AAPL",
        "event_type": "earnings",
        "summary": "Evidence-based summary.",
        "source_reliability": "medium",
        "market_relevance": 50,
        "directional_bias": "unclear",
        "confidence": 0.5,
        "requires_human_review": true,
        "evidence": ["short source-text evidence"]
      }
    }
  ]
}
```

Use conservative values when evidence is weak, expected, old, duplicated, or already priced in.
