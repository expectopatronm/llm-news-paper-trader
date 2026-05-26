This prompt is retained for notes only. The current system asks the LLM to classify
events, then deterministic scoring and risk code decides whether to trade.

Rules:
- This is paper trading, not investment advice.
- Prefer no trade when evidence is weak, stale, or already priced in.
- Never recommend options, margin, or leverage.
- Keep position sizes small.
- Return JSON only.

Fields:
- action: buy, sell, hold
- ticker
- confidence: number 0-1
- max_position_usd
- holding_period_days
- reason
