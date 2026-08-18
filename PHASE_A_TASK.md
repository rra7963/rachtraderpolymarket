# Phase A — Screening & Thesis Only (Automated Daily Task)

You are screening Polymarket prediction markets and writing theses. You
place no orders in this phase and you touch no money. Phase B does that,
separately, and only under its own gate.

Read `risk_rules.json` first. Every number in it is a hard limit. Your
reasoning may never override one, no matter how good the thesis sounds.

Scripts do the arithmetic. You do not compute sizing, stops, or
percentages in prose — call the script and use its number.

---

## Step 1 — Build the candidate list

```bash
python3 scripts/pm_screen.py --rules risk_rules.json --stats
```

This replaces the equity original's watchlist + scan. It applies every
`universe` filter mechanically and emits one JSON object per **outcome
token**, not per market.

That distinction matters: "buy YES at 0.62" and "buy NO at 0.38" are two
different trades. Only one of them can clear `min_entry_price`, and
proposing both is the opposite-side mistake Phase B will block anyway.

Read the `--stats` line on stderr. If almost everything died at one gate,
say so in your output — a screen that returns two candidates because
`max_spread` is too tight is worth reporting, not silently working around.

**Do not widen a filter to get more candidates.** Returning three
candidates is a valid result. Returning twenty by relaxing the rules is
not.

## Step 2 — Confirm the book before spending a news search

For every candidate you intend to write a thesis on:

```bash
python3 scripts/pm_order.py --rules risk_rules.json \
    --token-id <token_id> --side BUY --usd <intended_size>
```

You are reading three fields:

- `slippage_vs_top_pct` — what the book actually costs you. On a 0-1
  instrument, 3% slippage on a 0.60 entry is a fifth of a typical edge.
- `book_exhausted` — true means the depth cannot absorb your size. That
  is a reject, not a smaller-size negotiation, unless the reduced size
  still clears `min_order_usd` and you say so explicitly.
- `avg_fill_price` — the price your thesis has to beat. Not the screen's
  `price`, and not the midpoint.

If a candidate fails here, drop it before spending news budget on it.

## Step 3 — Research and write the thesis

Budget: `cadence.news_search_budget_per_cycle` searches for the whole
cycle. Spend them on candidates with `has_notable_signal: true` first;
currently-held positions are exempt from the signal gate and always get a
thesis.

A prediction market resolves against a specific written criterion, so the
thesis question is not "will this go up" but **"is the market's implied
probability wrong about this specific resolution criterion, and why"**.

For each candidate, write:

- **The resolution criterion, in your own words.** Read it. Markets are
  routinely mispriced by people trading the headline rather than the
  wording — "by September 30" and "announced by September 30" settle
  differently.
- **The implied probability** (`avg_fill_price` from Step 2) and what you
  think the real one is.
- **What would have to be true** for the market to be wrong, and what
  recent information supports that.
- **What would falsify it.** If you cannot name a concrete observable
  that would make you exit, you do not have a thesis, you have a hope.
- **Time risk.** `days_to_resolution` is in the candidate. A thesis that
  needs three weeks to play out in a market resolving in two days is not
  actionable.
- **conviction**: `high` / `medium` / `low`. Phase B sizes off this.
- **risk_flags**: a list. Thin book, ambiguous resolution wording,
  single-source news, an event date that could slip, neg-risk market.
  Count matters — Phase B ranks on it.

Be willing to write "no actionable candidates this cycle". That is a
result, and a cycle that produces nothing is cheaper than a cycle that
produces a bad position.

---

## Output

Append one JSON object per proposal to `proposals.jsonl`, plus a short
prose summary for the human.

```json
{
  "cycle_utc": "2026-08-18T13:00:00Z",
  "token_id": "1032...",
  "condition_id": "0xd838...",
  "slug": "atp-fonseca-oconnel-2026-08-18",
  "outcome": "Joao Fonseca",
  "action": "long",
  "conviction": "medium",
  "screen_price": 0.505,
  "avg_fill_price": 0.512,
  "implied_probability": 0.512,
  "estimated_probability": 0.60,
  "days_to_resolution": 7.32,
  "liquidity_usd": 274208.61,
  "spread": 0.01,
  "risk_flags": ["single_source_news"],
  "signals": ["price_move_24h", "volume_spike"],
  "thesis": "...",
  "falsifier": "...",
  "resolution_criterion": "..."
}
```

`action` is one of `long`, `avoid`, `exit_existing`.

---

## Hard stop

- You do **not** place, review, or price orders for execution in this
  phase. Step 2's `pm_order.py` call is read-only pricing; `execution.mode`
  stays untouched.
- You do **not** edit `risk_rules.json`. Not one field, not
  `execution.mode`, not a threshold you disagree with. If a rule looks
  wrong, say so in your summary and leave it alone.
- You do **not** carry a thesis over from a previous cycle without
  re-verifying its price and book today.
