# Phase B — Re-verify, Risk Enforcement, Order Gate, and Logging (Automated Daily Task)

Phase A proposed. You decide, enforce, and record. Read
`risk_rules.json` first; every number in it is binding.

You compute nothing in prose. Sizing, stops, take-profit, loss limits —
each has a script, each produces the same number from the same inputs,
and a good story never changes one.

---

## Step 0 — Load state

1. Read `risk_rules.json`.
2. Read today's `proposals.jsonl` entries from Phase A.
3. Pull live state:

```bash
python3 scripts/pm_positions.py --wallet <wallet_address>
```

4. Count `dry_run` cycles completed so far from `trade_log.jsonl`. If
   `execution.mode` is `live` but completed cycles are still under
   `execution.dry_run_min_cycles_before_live`, treat this cycle as
   `dry_run` and say so in the log.

## Step 1 — Settle resolved markets first

Before any stop-loss or take-profit evaluation, handle every position
where `action_required` is `settle`.

These markets have already resolved. `settlement_price` is 1 or 0, taken
from the CLOB's own `tokens[].winner`, and `realized_pnl_usd` is final.
Book them into `trade_log.jsonl` as realized and remove them from the
open-position set.

Doing this first is not tidiness. A resolved position cannot be sold
into, so evaluating a stop on it produces an order that would be
rejected, and leaving it in the position count wrongly consumes a
`max_concurrent_positions` slot that a live candidate could use.

> Never use gamma-api to check resolution. Its `conditionId` filter is
> silently ignored and returns an unrelated market — a LoL match query
> came back as `xi-jinping-out-before-2027`. `pm_positions.py` already
> reads the CLOB; trust it, don't second-source it with gamma.

## Step 2 — Re-verify proposals against fresh data

Phase A ran earlier. Prices move.

For every proposal, re-price it now:

```bash
python3 scripts/pm_order.py --rules risk_rules.json \
    --token-id <token_id> --side BUY --usd <intended_size>
```

Reject the proposal if any of these is true:

- `avg_fill_price` has moved outside `universe.min_entry_price` /
  `max_entry_price`.
- `avg_fill_price` has moved more than 5% against Phase A's number. The
  thesis was written about a different price; it needs re-writing, not
  re-using.
- `book_exhausted` is true at the intended size.
- The market's `days_to_resolution` has dropped below
  `universe.min_days_to_resolution`.
- The book's relevant side is empty.

## Step 3 — Loss limits

```bash
python3 scripts/pnl_pct.py \
    --daily-realized-usd <sum of today's realized from trade_log.jsonl> \
    --weekly-realized-usd <sum of this week's realized> \
    --starting-capital-usd <risk_rules starting_capital_usd> \
    --daily-limit-pct <loss_limits.daily_loss_limit_pct_of_account> \
    --weekly-limit-pct <loss_limits.weekly_loss_limit_pct_of_account>
```

Realized P&L includes Step 1's settlements — that is the whole point of
settling first.

If the script halts entries, **no new positions and no top-ups this
cycle**. Stops and take-profits still run: risk reduction is never
halted by a loss limit.

## Step 4 — Per-position risk enforcement

For every open position, every cycle, regardless of any new thesis:

**Stop-loss**

```bash
python3 scripts/stop_loss.py \
    --average-cost <avg_price> --current-price <mark_price> \
    --mode <stop_loss.mode> --hard-stop-pct <stop_loss.hard_stop_pct> \
    --days-to-resolution <days_to_resolution> \
    [--market-closed]
```

`action: settled_no_action` means Step 1 should already have handled it.
`resolution_imminent: true` means the stop is decorative — the event will
decide the position first. Note it; do not act on it as if it were a
stop.

Also check `exitable`. A position with no bid cannot be sold at any
price, so a triggered stop on it is a plan, not an exit. Log it as
`stop_triggered_unfillable` rather than pretending an order went out.

**Take-profit**

```bash
python3 scripts/take_profit.py --average-cost <avg_price> \
    --current-price <mark_price> --quantity <size> \
    --tiers <from take_profit.tiers> --fired-tiers <from trade_log>
```

Both run independent of any narrative. A good new story cancels neither.

## Step 5 — Size the new entries

Rank first, then size — sizing compounds down the list, so order matters:

```bash
cat candidates.json | python3 scripts/rank_candidates.py | \
python3 scripts/position_sizing.py \
    --total-value <account value> --cash-start <available cash> \
    --concurrent-positions-start <open count after Step 1> \
    --max-position-pct <position_sizing.max_position_pct_of_account> \
    --max-concurrent-positions <position_sizing.max_concurrent_positions> \
    --min-cash-buffer-pct <position_sizing.min_cash_buffer_pct> \
    --min-top-up-usd <position_sizing.min_top_up_usd> \
    --min-top-up-pct-of-target <position_sizing.min_top_up_pct_of_target> \
    --min-order-usd <position_sizing.min_order_usd> \
    --conviction-pct high:1.0,medium:0.6,low:0.3
```

**Opposite-side guard.** Before accepting any BUY, check whether an open
position already exists on a different token of the same `condition_id`.
If so, reject it.

This is not theoretical. YES at 0.65 plus NO at 0.54 costs 1.19 to buy
something that pays exactly 1.00 — a locked-in 19% loss regardless of
outcome. It was observed live when two separately well-ranked traders
took opposite sides of the same market minutes apart. The guard blocks
BUYS only; it never blocks a stop-loss or take-profit sell.

## Step 6 — The order gate

Every order, dry-run or live, goes through:

```bash
python3 scripts/pm_order.py --rules risk_rules.json \
    --token-id <token_id> --side <BUY|SELL> --usd <amount>
```

- `execution.mode` is `dry_run` → the script prices it and sends nothing.
  Record the priced order in the log as a dry-run decision.
- `execution.mode` is `live` → the script currently **blocks with
  `status: blocked`** and exits non-zero.

That block is real, not a stub. Polymarket rejects EOA makers outright
("maker address not allowed, please use the deposit wallet flow") and
has moved collateral from USDC.e to pUSD. Live orders need a funded
Deposit Wallet and EIP-712 signing through `@polymarket/client`.

**When you hit that block: log it and stop.** Do not attempt to route
around it, do not hand-craft a signed order, and do not report a trade as
placed. Everything up to this line — screening, thesis, re-verification,
risk enforcement, sizing — is fully exercised without it.

## Step 7 — Logging

Append to `trade_log.jsonl`, one object per decision, approved or
rejected. Append-only; never rewrite a past line.

Every rejection records which rule rejected it and the script output that
produced the number. The log's job is to let a human check whether the
reasoning was sound — a log that only records the trades you liked cannot
do that.

---

## Hard rules

- **Never change `execution.mode`.** Only the human sets it to `live`.
  If you believe the system is ready, say so in your summary and leave
  the field alone.
- **Never edit `risk_rules.json`.** Not a threshold, not a limit, not a
  comment.
- **Never skip Step 1.** Settling resolved markets before evaluating
  risk is what keeps position counts and P&L honest.
- **Never claim an order was placed** unless the script returned a real
  confirmation. `dry_run_priced` and `blocked` are not placements.
- **A thesis never overrides a mechanical rule.** Stops, take-profits,
  loss limits, sizing caps, and the opposite-side guard all outrank your
  reasoning, every cycle, without exception.
