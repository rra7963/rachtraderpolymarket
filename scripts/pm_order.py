#!/usr/bin/env python3
# Part of FriesTrader-Polymarket, adapted from FriesTrader
# (https://github.com/YizhiSong/FriesTrader) -- MIT License, see LICENSE
"""The order gate. Replaces upstream's review_equity_order.

In dry_run it prices an order against the live book and reports exactly
what would be sent -- shares, average fill after walking the book,
slippage vs. the top of book, and every rule it was checked against.

In live it refuses, loudly, and explains why. That is not a placeholder:
as of 2026-08 Polymarket rejects EOA makers outright --

    maker address not allowed, please use the deposit wallet flow

-- and has moved collateral from USDC.e to pUSD
(0xC011a7E12a19f7B1f670d46F03B03f3342E82DFB). Signing an order also
needs EIP-712, which is not a stdlib job. So live execution requires a
funded Deposit Wallet plus @polymarket/client, and this script will not
pretend otherwise by emitting a "submitted" that never reached an
exchange. Screening, thesis, risk enforcement and dry_run all work fully
without it.

Usage:
  python3 scripts/pm_order.py --rules risk_rules.json \
      --token-id 1032... --side BUY --usd 25 --dry-run
"""
import argparse
import json
import sys

sys.path.insert(0, __file__.rsplit("/", 1)[0])
import pm_api  # noqa: E402


def walk_book(levels, usd_budget=None, shares_wanted=None, ascending=True):
    """Fill against real depth instead of assuming the whole order clears
    at top of book. Returns (shares, cost_usd, worst_price, exhausted)."""
    levels = sorted(
        ({"price": float(l["price"]), "size": float(l["size"])} for l in levels),
        key=lambda l: l["price"], reverse=not ascending,
    )
    shares = cost = 0.0
    worst = None
    for lvl in levels:
        if usd_budget is not None and cost >= usd_budget - 1e-9:
            break
        if shares_wanted is not None and shares >= shares_wanted - 1e-9:
            break

        take = lvl["size"]
        if usd_budget is not None:
            take = min(take, (usd_budget - cost) / lvl["price"])
        if shares_wanted is not None:
            take = min(take, shares_wanted - shares)
        if take <= 0:
            continue

        shares += take
        cost += take * lvl["price"]
        worst = lvl["price"]

    exhausted = (usd_budget is not None and cost < usd_budget - 0.01) or (
        shares_wanted is not None and shares < shares_wanted - 1e-6
    )
    return shares, cost, worst, exhausted


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--rules", default="risk_rules.json")
    p.add_argument("--token-id", required=True)
    p.add_argument("--side", choices=["BUY", "SELL"], required=True)
    p.add_argument("--usd", type=float, help="order size in USD (BUY)")
    p.add_argument("--shares", type=float, help="share count (SELL)")
    p.add_argument("--dry-run", action="store_true",
                   help="explicit acknowledgement that this only prices the order")
    args = p.parse_args()

    rules = json.load(open(args.rules))
    mode = rules["execution"]["mode"]

    if args.side == "BUY" and args.usd is None:
        sys.exit("--usd is required for BUY")
    if args.side == "SELL" and args.shares is None:
        sys.exit("--shares is required for SELL")

    book = pm_api.order_book(args.token_id)
    levels = book.get("asks" if args.side == "BUY" else "bids") or []
    if not levels:
        print(json.dumps({
            "status": "rejected",
            "reason": "empty %s side of the book -- no counterparty at any price"
                      % ("ask" if args.side == "BUY" else "bid"),
        }, indent=2))
        return

    if args.side == "BUY":
        shares, cost, worst, exhausted = walk_book(levels, usd_budget=args.usd, ascending=True)
        top = min(float(l["price"]) for l in levels)
    else:
        shares, cost, worst, exhausted = walk_book(levels, shares_wanted=args.shares, ascending=False)
        top = max(float(l["price"]) for l in levels)

    avg = cost / shares if shares > 0 else None
    result = {
        "mode": mode,
        "side": args.side,
        "token_id": args.token_id,
        "top_of_book": top,
        "shares": round(shares, 4),
        "notional_usd": round(cost, 2),
        "avg_fill_price": round(avg, 4) if avg else None,
        "worst_level_taken": worst,
        "slippage_vs_top_pct": round(abs(avg - top) / top, 4) if avg and top else None,
        "book_exhausted": exhausted,
    }

    min_order = rules["position_sizing"].get("min_order_usd", 1.00)
    if cost < min_order:
        result["status"] = "rejected"
        result["reason"] = "notional $%.2f below Polymarket minimum $%.2f" % (cost, min_order)
        print(json.dumps(result, indent=2))
        return

    if exhausted:
        result["warning"] = ("book could not absorb the full size; the numbers above are for "
                             "the portion that would fill")

    if mode != "live":
        result["status"] = "dry_run_priced"
        result["note"] = "execution.mode is '%s' -- nothing was sent" % mode
        print(json.dumps(result, indent=2))
        return

    if not args.dry_run:
        deposit_wallet = (rules.get("deposit_wallet_address") or "").strip()
        result["status"] = "blocked"
        result["reason"] = (
            "Polymarket no longer accepts EOA makers ('maker address not allowed, please use "
            "the deposit wallet flow') and settles in pUSD, not USDC.e. Live orders need a "
            "funded Deposit Wallet and EIP-712 signing via @polymarket/client, which this "
            "stdlib script deliberately does not fake."
        )
        result["deposit_wallet_configured"] = bool(deposit_wallet)
        result["next_steps"] = [
            "deploy a Deposit Wallet and record it in risk_rules.json deposit_wallet_address",
            "fund it through Polymarket's own deposit flow (pUSD cannot be self-minted)",
            "run setupTradingApprovals for the current exchange contracts",
            "route this call through @polymarket/client's placeLimitOrder",
        ]
        print(json.dumps(result, indent=2))
        sys.exit(2)

    result["status"] = "dry_run_priced"
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
