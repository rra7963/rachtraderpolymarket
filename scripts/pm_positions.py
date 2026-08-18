#!/usr/bin/env python3
# Part of FriesTrader-Polymarket, adapted from FriesTrader
# (https://github.com/YizhiSong/FriesTrader) -- MIT License, see LICENSE
"""Phase B Step 0/4 state: open positions, their live marks, and whether
their market has resolved. Replaces upstream's get_equity_positions.

Resolution status comes from the CLOB, never from gamma-api -- gamma
silently ignores its conditionId filter and hands back an unrelated
market, so `closed` would be some other market's. Once a market is
closed, tokens[].winner gives the exact settlement value (1 or 0), which
is what Phase B books instead of trying to sell into a dead market.

Usage:
  python3 scripts/pm_positions.py --wallet 0xYourWallet
  python3 scripts/pm_positions.py --wallet 0xYourWallet --resolved-only
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
        end = datetime.fromisoformat(str(iso_str).replace("Z", "+00:00"))
    except ValueError:
        return None
    return (end - datetime.now(timezone.utc)).total_seconds() / 86400.0


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--wallet", required=True)
    p.add_argument("--resolved-only", action="store_true",
                   help="only emit positions whose market has resolved and is awaiting settlement")
    args = p.parse_args()

    raw = pm_api.positions(args.wallet)
    if not isinstance(raw, list):
        print(json.dumps({"error": "unexpected positions payload", "payload": str(raw)[:200]}),
              file=sys.stderr)
        sys.exit(1)

    out = []
    for pos in raw:
        token_id = pos.get("asset") or pos.get("tokenId")
        condition_id = pos.get("conditionId")
        size = float(pos.get("size") or 0)
        if size <= 0 or not token_id or not condition_id:
            continue

        avg_price = float(pos.get("avgPrice") or 0)
        record = {
            "token_id": str(token_id),
            "condition_id": condition_id,
            "slug": pos.get("slug"),
            "title": pos.get("title"),
            "outcome": pos.get("outcome"),
            "size": size,
            "avg_price": round(avg_price, 4),
            "cost_usd": round(avg_price * size, 2),
        }

        try:
            market = pm_api.clob_market(condition_id)
        except pm_api.ApiError as e:
            record["error"] = "market lookup failed: %s" % e
            out.append(record)
            continue

        closed = bool(market.get("closed"))
        record["market_closed"] = closed
        record["days_to_resolution"] = (
            round(days_until(market.get("end_date_iso")), 3)
            if days_until(market.get("end_date_iso")) is not None else None
        )

        token = next((t for t in market.get("tokens", [])
                      if str(t.get("token_id")) == str(token_id)), None)

        if closed and token is not None:
            settle = 1.0 if token.get("winner") else 0.0
            record["settlement_price"] = settle
            record["settlement_value_usd"] = round(settle * size, 2)
            record["realized_pnl_usd"] = round(settle * size - avg_price * size, 2)
            record["action_required"] = "settle"
        elif not closed:
            # Mark to the bid: what you could actually get out at, not the
            # midpoint. On a thin book those differ a lot.
            try:
                bid, ask = pm_api.best_bid_ask(token_id)
            except pm_api.ApiError:
                bid = ask = None
            record["best_bid"] = bid
            record["best_ask"] = ask
            mark = bid if bid is not None else avg_price
            record["mark_price"] = round(mark, 4)
            record["market_value_usd"] = round(mark * size, 2)
            record["unrealized_pnl_usd"] = round((mark - avg_price) * size, 2)
            record["unrealized_pnl_pct"] = (
                round((mark - avg_price) / avg_price, 4) if avg_price > 0 else None
            )
            record["exitable"] = bid is not None
            record["action_required"] = "evaluate"

        if args.resolved_only and record.get("action_required") != "settle":
            continue
        out.append(record)

    print(json.dumps(out, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
