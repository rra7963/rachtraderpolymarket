#!/usr/bin/env python3
# Part of FriesTrader-Polymarket, adapted from FriesTrader
# (https://github.com/YizhiSong/FriesTrader) -- MIT License, see LICENSE
"""Shared stdlib-only HTTP helpers for Polymarket's public REST APIs.

Polymarket has no MCP server, so where upstream FriesTrader called
Robinhood MCP tools, this fork calls these endpoints directly. Kept to
the standard library on purpose, matching the rest of scripts/.

Endpoints used:
  Gamma  https://gamma-api.polymarket.com  -- market metadata, screening
  CLOB   https://clob.polymarket.com       -- order book, tick size, resolution
  Data   https://data-api.polymarket.com   -- positions, activity

All three reject requests without a User-Agent (403), so one is always
sent. Proxies are picked up from the usual http_proxy/https_proxy env
vars by urllib's default opener.
"""
import json
import time
import urllib.error
import urllib.parse
import urllib.request

GAMMA = "https://gamma-api.polymarket.com"
CLOB = "https://clob.polymarket.com"
DATA = "https://data-api.polymarket.com"

_UA = "FriesTrader-Polymarket/1.0"
_TIMEOUT = 25


class ApiError(RuntimeError):
    pass


def get_json(url, params=None, retries=2):
    """GET and parse JSON, with a couple of retries on transient failures."""
    if params:
        clean = {k: v for k, v in params.items() if v is not None}
        url = url + "?" + urllib.parse.urlencode(clean, doseq=True)

    last = None
    for attempt in range(retries + 1):
        req = urllib.request.Request(
            url, headers={"User-Agent": _UA, "Accept": "application/json"}
        )
        try:
            with urllib.request.urlopen(req, timeout=_TIMEOUT) as resp:
                return json.loads(resp.read())
        except urllib.error.HTTPError as e:
            # 4xx other than rate-limiting won't fix itself; fail fast
            if e.code != 429 and 400 <= e.code < 500:
                raise ApiError("HTTP %d from %s" % (e.code, url)) from e
            last = e
        except Exception as e:  # noqa: BLE001 - network layer, retry anything
            last = e
        if attempt < retries:
            time.sleep(1.5 * (attempt + 1))
    raise ApiError("%s failed after %d attempts: %s" % (url, retries + 1, last))


def parse_json_field(value, default=None):
    """Gamma returns several fields as JSON-encoded strings, e.g.
    outcomePrices='["0.62","0.38"]'. Decode those without exploding on
    the ones that are already lists."""
    if value is None:
        return default
    if isinstance(value, (list, dict)):
        return value
    try:
        return json.loads(value)
    except (TypeError, ValueError):
        return default


def clob_market(condition_id):
    """Authoritative market state, including resolution.

    ⚠️ Do NOT use gamma-api for this. Its conditionId filter is silently
    ignored -- it returns an unrelated market, so `closed` ends up being
    some other market's. Verified the hard way: querying a LoL match
    returned `xi-jinping-out-before-2027`.
    """
    return get_json("%s/markets/%s" % (CLOB, condition_id))


def order_book(token_id):
    return get_json("%s/book" % CLOB, {"token_id": token_id})


def best_bid_ask(token_id):
    """Top of book as (best_bid, best_ask). Either may be None if that
    side is empty -- an empty side means you cannot get out at any price,
    which the caller must treat as a hard reject, not as zero spread."""
    book = order_book(token_id)
    bids = book.get("bids") or []
    asks = book.get("asks") or []
    best_bid = max((float(b["price"]) for b in bids), default=None)
    best_ask = min((float(a["price"]) for a in asks), default=None)
    return best_bid, best_ask


def positions(wallet):
    return get_json("%s/positions" % DATA, {"user": wallet, "sizeThreshold": 0.01})
