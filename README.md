# RachTrader for Polymarket

> **A research-first, risk-governed operating system for prediction-market trading.**
>
> RachTrader turns the daily Polymarket workflow—market discovery, thesis formation, execution-quality checks, position sizing, exit discipline, and audit logging—into a deterministic process. It is designed to make the *decision process* more rigorous before it ever attempts to make a trade.

**RachTrader for Polymarket** is a purpose-built operating framework for binary and multi-outcome prediction markets. It combines Polymarket-native market data, outcome-token mechanics, resolution-aware risk controls, and a deliberately conservative execution gate in one auditable workflow.

The project is intentionally opinionated: language models can help investigate and explain a market, but they do not get to override arithmetic, risk limits, or execution safeguards. Every important number comes from a script. Every decision is recorded. And the default mode is always `dry_run`.

---

## The principle

Prediction markets are not ordinary equities with different ticker symbols. An outcome token has a bounded payoff, a written resolution criterion, often-fragile liquidity, and a hard deadline at which the market resolves. A compelling narrative is therefore insufficient: it must be evaluated against the exact settlement language, the executable price in the order book, the remaining time to resolution, and a portfolio-level risk budget.

RachTrader is built around one simple separation of responsibilities:

| Layer | Responsibility | May override risk rules? |
|---|---|---|
| **Research** | Find potentially mispriced outcomes and articulate a falsifiable thesis | No |
| **Market data** | Retrieve live market, book, and position information | No |
| **Risk engine** | Apply hard limits for sizing, concentration, loss, stops, and exits | No |
| **Execution gate** | Price orders and enforce the selected execution mode | No |
| **Human operator** | Own capital, configure limits, and explicitly authorize live trading | Yes—by editing configuration deliberately |

The result is not a promise of alpha. It is an operating discipline: good stories are allowed to propose trades; they are never allowed to waive controls.

---

## What it does

RachTrader supports the full pre-trade and post-trade operating loop for Polymarket:

- Screens live Polymarket markets using liquidity, volume, spread, entry-price, and time-to-resolution constraints.
- Treats each **outcome token** as a separate tradeable instrument—e.g. YES and NO are evaluated independently.
- Checks real order-book depth and estimates average fill, shares, and slippage before a position is considered actionable.
- Guides structured research around the market's exact resolution criterion, implied probability, evidence, falsifier, and time risk.
- Sizes positions mechanically with account caps, concurrent-position limits, minimum cash reserves, and conviction-weighted allocation.
- Applies stop-loss and tiered take-profit logic on every cycle, independently of new research narratives.
- Prevents accidental ownership of both sides of the same `condition_id`, a direct route to a guaranteed loss when total acquisition cost exceeds the fixed $1 settlement payout.
- Settles resolved positions before evaluating new entries, keeping realized P&L and position capacity honest.
- Produces an append-only decision log so accepted, rejected, dry-run, and blocked decisions can all be audited later.

## What it deliberately does *not* do

- It does not claim to predict outcomes or provide a proven trading edge.
- It does not treat an LLM thesis as a substitute for verification.
- It does not silently relax filters to manufacture more trades.
- It does not send live orders in its current form.
- It does not change `execution.mode`, alter risk controls, or represent dry-run pricing as an executed trade.

That last point matters. The included workflow fully exercises screening, thesis writing, re-verification, risk enforcement, sizing, and execution-quality estimation. Live order placement remains deliberately blocked until a funded Polymarket Deposit Wallet and a signed `@polymarket/client` execution layer are integrated.

---

## System architecture

```text
Live Polymarket APIs
       │
       ▼
┌─────────────────────┐
│ Phase A: Discovery  │  Mechanical screen → book check → research thesis
└─────────┬───────────┘
          │ proposals.jsonl
          ▼
┌─────────────────────┐
│ Phase B: Enforcement│  Re-price → settle → risk limits → size → gate
└─────────┬───────────┘
          │
          ├── dry_run: price + log, no order sent
          └── live: currently blocked pending supported signer integration
          │
          ▼
   append-only trade_log.jsonl
```

The design intentionally puts execution last. A candidate must survive screening, book-quality review, resolution-criterion analysis, fresh re-pricing, portfolio constraints, and the opposite-side guard before it reaches an order gate.

---

## Prediction-market-native controls

RachTrader models prediction markets as their own instrument class, with controls designed around executable liquidity, bounded payoffs, explicit settlement rules, and finite resolution timelines.

| Control | Purpose |
|---|---|
| Live outcome-token screening | `pm_screen.py` discovers candidates directly from active Polymarket markets |
| Liquidity and timing filters | Evaluates 24-hour volume, spread, available liquidity, entry price, and time to resolution |
| CLOB execution-quality review | `pm_order.py` walks the actual order book and reports executable pricing |
| Opposite-side protection | Blocks conflicting exposure at the `condition_id` level |
| Event-driven signal detection | Tracks short-horizon price moves, volume spikes, and proximity to 0 or 1 |
| Resolution-aware risk management | Applies bounded-price stop logic while accounting for closed and imminent-resolution markets |

A key distinction is that a prediction market resolves. A token that cannot be exited before resolution is no longer a conventional trade; it is an exposure to a particular settlement outcome. RachTrader's `min_days_to_resolution` and resolution-aware stop handling reduce this risk, but they cannot eliminate it.

---

## The entry-price discipline

The default universe includes an entry band of **0.45–0.85**. This is not presented as a universal law or a permanent edge. It is a cautious prior based on 46 settled paper trades from a separate copy-trading strategy:

| Entry price | Trades | Win rate | Return |
|---:|---:|---:|---:|
| 0.00–0.35 | 8 | 12% | **-64%** |
| 0.35–0.50 | 9 | 22% | **-65%** |
| 0.50–0.65 | 19 | 68% | +17% |
| 0.65–0.80 | 7 | 100% | +35% |
| 0.80–1.00 | 3 | 67% | -6% |

The sample is small, short-lived, and derived from a different strategy. It should be treated as a hypothesis to revalidate through `dry_run`, not as an established statistical advantage. Its operational value is practical: avoid treating very cheap long shots as automatically attractive, and avoid paying nearly full settlement value for limited remaining upside.

---

## Repository map

```text
risk_rules.json             Immutable-by-agent numeric risk boundaries
PHASE_A_TASK.md             Screening and thesis protocol; no orders
PHASE_B_TASK.md             Re-verification, enforcement, gate, and logging protocol
trade_log_template.jsonl    Starting schema for the append-only decision journal

scripts/
  pm_api.py                 Shared stdlib HTTP helpers for Polymarket APIs
  pm_screen.py              Live-market candidate screen
  pm_positions.py           Open positions, marks, and resolution state
  pm_order.py               Order-book pricing and execution-mode gate
  position_sizing.py        Allocation, concentration, and cash-buffer logic
  stop_loss.py              Resolution-aware stop evaluation
  take_profit.py            Tiered partial-exit calculation
  pnl_pct.py                Daily and weekly realized-loss guardrails
  rank_candidates.py        Conviction, risk-flag, and liquidity ranking
```

The project uses Python's standard library only—no pip install is required for screening and dry-run workflows.

---

## Getting started: research before risk

### Prerequisites

- Python 3.9 or later.
- A Polygon wallet address for position reads; screening itself requires no wallet.
- An LLM workflow capable of following the Phase A and Phase B task specifications.
- For any future live execution: a funded Polymarket Deposit Wallet and a compatible Node-based signing/execution layer. This is **not included**.

### 1. Configure the operator-owned inputs

Open `risk_rules.json` and set:

1. `wallet_address` to the wallet you want to monitor.
2. `starting_capital_usd` to net capital contributed—deposits less withdrawals, not current portfolio value.
3. Any risk thresholds you personally wish to change.

The agent must never edit this file. It is the operator's explicit contract with the system.

### 2. Create the decision journal

```bash
cp trade_log_template.jsonl trade_log.jsonl
```

The journal is append-only. Rejected candidates and blocked orders belong in it alongside approved dry-run decisions; otherwise it cannot reveal whether the process itself is working.

### 3. Screen the live universe

```bash
python3 scripts/pm_screen.py --rules risk_rules.json --stats
```

This prints eligible outcome tokens and reports, on standard error, how many markets were rejected at each mechanical gate. A small candidate set is an acceptable outcome. Filters should not be loosened merely to produce more ideas.

### 4. Inspect executable price, not screen price

```bash
python3 scripts/pm_order.py --rules risk_rules.json \
  --token-id <token_id> --side BUY --usd 25
```

The command walks the live book and returns the estimated share count, average fill price, and slippage versus top-of-book. In default `dry_run` mode, it sends nothing.

### 5. Run the two-phase operating cycle

- **Phase A** uses the screened universe to write a resolution-aware, falsifiable thesis into `proposals.jsonl`.
- **Phase B** settles resolved positions, re-prices proposals, applies loss limits and position controls, then routes every resulting decision through the order gate.

Run both phases manually for multiple cycles before automating them. The configuration defaults to a minimum of ten completed dry-run cycles before live mode could even be considered—and the present execution layer still blocks live placement.

---

## How a candidate earns a place

RachTrader treats a trade proposal as a structured argument, not a headline reaction. For each candidate, Phase A must capture:

- The exact resolution criterion, explained in plain language.
- The executable implied probability from the fresh order-book estimate.
- An independently estimated probability and the evidence supporting it.
- The specific facts that would falsify the thesis.
- Time risk relative to the market's resolution date.
- A conviction level and explicit risk flags, such as thin depth, ambiguous wording, or single-source evidence.

Phase B then asks a different question: *even if the thesis is sound, is the trade still permitted at this price, at this size, in this portfolio, at this moment?*

The answer can be no. That is a successful risk-control outcome.

---

## Guardrails that matter

### Hard configuration boundary

`risk_rules.json` contains numeric limits that reasoning cannot override. A persuasive thesis cannot exceed concentration caps, ignore a daily loss halt, or change the execution mode.

### Fresh-book re-verification

Prices move between research and action. Phase B re-prices every proposal and rejects it if the executable fill price leaves the entry band, moves materially against the original thesis price, exhausts available depth, or approaches resolution too closely.

### Opposite-side guard

Holding both sides of a binary condition can lock in a loss. Buying YES at 0.65 and NO at 0.54 costs 1.19 for a combined payoff of exactly 1.00. The guard blocks new buys on the other token of an already-held `condition_id`; it never interferes with risk-reducing sells.

### Resolution-first accounting

Resolved markets are settled before stops, take-profits, new sizing, or position-count checks. This avoids proposing an impossible exit and prevents resolved positions from falsely consuming risk capacity.

### Execution truthfulness

`dry_run_priced` means an order was priced. `blocked` means it was blocked. Neither means an order was placed. The workflow records that distinction explicitly.

---

## Automation model

The system is designed for a daily or periodic schedule, whether that is cron, GitHub Actions, or an agent scheduler:

1. Run **Phase A** to screen, examine books, research, and write proposals.
2. Run **Phase B** later to refresh pricing, enforce portfolio constraints, evaluate open-position exits, and log the outcome.

Keeping these phases separate is a feature. It prevents a thesis written at one price from quietly becoming an order at another, and it creates a natural checkpoint between idea generation and capital allocation.

---

## Safety and risk disclosure

This repository is research infrastructure, not investment advice and not a guarantee of profitability. Prediction markets carry meaningful risks, including loss of the entire amount committed to an outcome, poor liquidity, execution slippage, ambiguous settlement interpretation, and resolution events that outpace any attempted exit.

Do not enable or build live execution until you have:

- Completed a meaningful dry-run history and reviewed its results.
- Validated every limit in `risk_rules.json` against your own loss tolerance.
- Confirmed the exact market-resolution rules you are trading.
- Implemented and independently tested a secure funded Deposit Wallet and signed order workflow.
- Accepted that no screen, model, or thesis removes market risk.

The aim is not to automate confidence. It is to make uncertainty visible, bounded, and reviewable.

---

## License

Released under the MIT License. See `LICENSE` for details.
