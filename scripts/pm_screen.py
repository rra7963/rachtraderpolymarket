#!/usr/bin/env python3
# Part of FriesTrader-Polymarket, adapted from FriesTrader
# (https://github.com/YizhiSong/FriesTrader) -- MIT License, see LICENSE
"""Build the Phase A candidate list from Polymarket's live markets, per
risk_rules.json `universe` and `signal_thresholds`.

Replaces upstream's Robinhood watchlist + scan. Every filter here is
mechanical -- the model does not get to argue with any of it. Output is
one JSON object per candidate on stdout, ready for Phase A's thesis step.

Each candidate is emitted per *outcome token*, not per market: "buy YES
at 0.62" and "buy NO at 0.38" are different trades with different
entry-price filtering, and only one of them can pass min_entry_price.

Usage:
  python3 scripts/pm_screen.py --rules risk_rules.json
  python3 scripts/pm_screen.py --rules risk_rules.json --pool 400
"""
import argparse
import json
import sys
from datetime import datetime, timezone

sys.path.insert(0, __file__.rsplit("/", 1)[0])
import pm_api  # noqa: E402


def days_until(iso_str):
    if not iso_str:
        return None
    try:
        end = datetime.fromisoformat(iso_str.replace("Z", "+00:00"))
    except ValueError:
        return None
    return (end - datetime.now(timezone.utc)).total_seconds() / 86400.0


def fetch_pool(pool_size):
    """Pull the most active markets, newest volume first. Gamma caps a
    single page well below what we want, so page through it."""
    out, offset, page = [], 0, 100
    while len(out) < pool_size:
        batch = pm_api.get_json(
            pm_api.GAMMA + "/markets",
            {
                "active": "true",
                "closed": "false",
                "archived": "false",
                "limit": page,
                "offset": offset,
                "order": "volume24hr",
                "ascending": "false",
            },
        )
        if not batch:
            break
        out.extend(batch)
        offset += page
        if len(batch) < page:
            break
    return out[:pool_size]


def screen(market, rules):
    """Return (candidates, reject_reason). candidates is a list of
    per-token dicts; reject_reason is set only when the whole market is
    out, so Phase A can report how many died at which gate."""
    u = rules["universe"]
    sig = rules["signal_thresholds"]

    vol24 = float(market.get("volume24hr") or 0)
    if vol24 < u["min_volume_24hr_usd"]:
        return [], "volume24hr"

    liq = float(market.get("liquidityNum") or market.get("liquidity") or 0)
    if liq < u["min_liquidity_usd"]:
        return [], "liquidity"

    if u.get("exclude_negrisk") and market.get("negRisk"):
        return [], "negrisk"

    dtr = days_until(market.get("endDate"))
    if dtr is None or not (u["min_days_to_resolution"] <= dtr <= u["max_days_to_resolution"]):
        return [], "days_to_resolution"

    outcomes = pm_api.parse_json_field(market.get("outcomes"), [])
    prices = pm_api.parse_json_field(market.get("outcomePrices"), [])
    token_ids = pm_api.parse_json_field(market.get("clobTokenIds"), [])
    if not (len(outcomes) == len(prices) == len(token_ids)) or not outcomes:
        return [], "malformed"

    # Signal gate is per-market: cheaper to compute once than per token.
    vol1wk = float(market.get("volume1wk") or 0)
    daily_avg = vol1wk / 7.0 if vol1wk else 0.0
    spike = vol24 / daily_avg if daily_avg > 0 else 0.0
    move24 = abs(float(market.get("oneDayPriceChange") or 0))

    cands = []
    for outcome, price_str, token_id in zip(outcomes, prices, token_ids):
        price = float(price_str)
        if not (u["min_entry_price"] <= price <= u["max_entry_price"]):
            continue

        # Spread is checked on the live book, not Gamma's cached field --
        # an empty side is a hard reject, not a zero spread.
        try:
            bid, ask = pm_api.best_bid_ask(token_id)
        except pm_api.ApiError:
            continue
        if bid is None or ask is None:
            continue
        spread = ask - bid
        if spread > u["max_spread"]:
            continue

        extreme_gap = min(price, 1.0 - price)
        signals = []
        if move24 >= sig["price_move_24h_pct"]:
            signals.append("price_move_24h")
        if spike >= sig["volume_spike_multiple"]:
            signals.append("volume_spike")
        if extreme_gap <= sig["pct_from_price_extreme"]:
            signals.append("near_price_extreme")

        cands.append({
            "token_id": token_id,
            "condition_id": market.get("conditionId"),
            "slug": market.get("slug"),
            "question": market.get("question"),
            "outcome": outcome,
            "price": round(price, 4),
            "best_bid": bid,
            "best_ask": ask,
            "spread": round(spread, 4),
            "volume_24hr_usd": round(vol24, 2),
            "liquidity_usd": round(liq, 2),
            "volume_spike_multiple": round(spike, 2),
            "price_move_24h_pct": round(move24, 4),
            "days_to_resolution": round(dtr, 2),
            "neg_risk": bool(market.get("negRisk")),
            "signals": signals,
            "has_notable_signal": bool(signals),
        })
    return cands, None


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--rules", default="risk_rules.json")
    p.add_argument("--pool", type=int, default=300,
                   help="how many active markets to screen before filtering")
    p.add_argument("--stats", action="store_true",
                   help="also print reject counts per gate to stderr")
    args = p.parse_args()

    rules = json.load(open(args.rules))
    markets = fetch_pool(args.pool)

    rejects, candidates = {}, []
    for m in markets:
        cands, reason = screen(m, rules)
        if reason:
            rejects[reason] = rejects.get(reason, 0) + 1
        candidates.extend(cands)

    # Signal-bearing candidates first, then by liquidity -- Phase A's
    # news budget should be spent where something actually moved.
    candidates.sort(key=lambda c: (not c["has_notable_signal"], -c["liquidity_usd"]))
    candidates = candidates[: rules["universe"]["max_candidates"]]

    if args.stats:
        print("screened %d markets -> %d candidates" % (len(markets), len(candidates)),
              file=sys.stderr)
        for k, v in sorted(rejects.items(), key=lambda kv: -kv[1]):
            print("  rejected %4d at %s" % (v, k), file=sys.stderr)

    for c in candidates:
        print(json.dumps(c, ensure_ascii=False))


if __name__ == "__main__":
    main()
