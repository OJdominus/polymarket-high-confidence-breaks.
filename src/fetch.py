"""
Data acquisition from the Polymarket public APIs, with check-before-fetch
caching. Every fetch writes its result to data/ and returns the cached
copy on the next run, so the second run is instant and offline.

Two stages:
  fetch_resolved_markets()  -> data/resolved_markets.csv      (Gamma API)
  fetch_snapshots(df)       -> data/markets_with_snapshots.csv (CLOB API)

Standard library only; no third-party packages. Network access to
gamma-api.polymarket.com and clob.polymarket.com is required on the first
run only.

API constraints handled here (the things that cost time to rediscover):
  - Gamma /events caps offset at 10,000, so we chunk the pull by month.
  - The CLOB price-history endpoint needs fidelity=720 for resolved
    markets and returns 12-hour bins; finer granularity is not available
    after resolution.
  - Both endpoints are rate-limited, so we sleep between calls and back
    off on HTTP 429.
"""

import csv
import json
import os
import time
from datetime import datetime, timezone
from urllib.parse import urlencode
from urllib.request import Request, urlopen
from urllib.error import URLError, HTTPError

from src.utils import (
    RAW_MARKETS, SNAPSHOTS, DATA_DIR,
    DATE_FROM, DATE_TO, MIN_EVENT_VOLUME, SNAPSHOT_COLS, to_float,
)

GAMMA_API = "https://gamma-api.polymarket.com"
CLOB_API = "https://clob.polymarket.com"

PAGE_LIMIT = 100
OFFSET_CAP = 10_000
SLEEP_BETWEEN_PAGES = 0.2
SLEEP_BETWEEN_MONTHS = 0.5
CLOB_FIDELITY = 720  # required for resolved markets; yields 12h bins


# ---------------------------------------------------------------------------
# HTTP helper with retry/backoff.
# ---------------------------------------------------------------------------

def _http_get_json(url, params=None, timeout=30, max_retries=3):
    if params:
        url = f"{url}?{urlencode(params)}"
    last_err = None
    for attempt in range(max_retries + 1):
        try:
            req = Request(url, headers={"User-Agent": "polymarket-breaks/1.0"})
            with urlopen(req, timeout=timeout) as resp:
                return json.loads(resp.read().decode("utf-8"))
        except HTTPError as e:
            if e.code == 422:      # Gamma offset cap; caller handles it
                raise
            if e.code == 429:      # rate limited; back off harder
                time.sleep(2 ** attempt + 1)
                last_err = e
                continue
            last_err = e
            if attempt < max_retries:
                time.sleep(2 ** attempt)
        except (URLError, TimeoutError, json.JSONDecodeError) as e:
            last_err = e
            if attempt < max_retries:
                time.sleep(2 ** attempt)
    raise RuntimeError(f"GET {url} failed after {max_retries} retries: {last_err}")


# ---------------------------------------------------------------------------
# Field parsing.
# ---------------------------------------------------------------------------

def _parse_json_list(raw):
    if raw is None:
        return None
    if isinstance(raw, str):
        try:
            raw = json.loads(raw)
        except (json.JSONDecodeError, TypeError):
            return None
    return raw if isinstance(raw, list) and raw else None


def _parse_dt(s):
    if not s:
        return None
    try:
        dt = datetime.fromisoformat(s.replace("Z", "+00:00"))
        return dt.replace(tzinfo=timezone.utc) if dt.tzinfo is None else dt
    except (ValueError, TypeError):
        return None


def _infer_resolution(prices):
    """A binary market resolves YES if the YES price settled near 1, NO near 0."""
    if not prices or len(prices) < 2:
        return None
    yes, no = prices[0], prices[1]
    if yes > 0.95 and no < 0.05:
        return "YES"
    if no > 0.95 and yes < 0.05:
        return "NO"
    return None


def _month_chunks(date_from, date_to):
    cur = date_from.replace(day=1)
    while cur < date_to:
        nxt = (cur.replace(year=cur.year + 1, month=1) if cur.month == 12
               else cur.replace(month=cur.month + 1))
        yield cur.strftime("%Y-%m-%d"), min(nxt, date_to).strftime("%Y-%m-%d")
        cur = nxt


# ---------------------------------------------------------------------------
# Stage 1: resolved markets from Gamma.
# ---------------------------------------------------------------------------

_RAW_FIELDS = [
    "event_id", "event_title", "category", "event_volume", "neg_risk",
    "end_date", "closed_time", "market_id", "market_question", "market_volume",
    "yes_token_id", "no_token_id", "resolution", "final_yes_price", "final_no_price",
]


def _event_to_rows(ev, seen_ids, dfrom, dto):
    end_dt = _parse_dt(ev.get("endDate") or ev.get("closedTime"))
    if end_dt and dfrom and end_dt < dfrom:
        return []
    if end_dt and dto and end_dt > dto:
        return []
    if float(ev.get("volume") or 0) < MIN_EVENT_VOLUME:
        return []
    markets = ev.get("markets") or []
    if not markets:
        return []

    rows = []
    for m in markets:
        mid = str(m.get("id", ""))
        if not mid or mid in seen_ids or not m.get("closed"):
            continue
        prices = _parse_json_list(m.get("outcomePrices"))
        prices = [float(p) for p in prices] if prices else None
        resolution = _infer_resolution(prices)
        if resolution is None:
            continue
        tokens = _parse_json_list(m.get("clobTokenIds"))
        if not tokens or len(tokens) < 2:
            continue
        seen_ids.add(mid)
        rows.append({
            "event_id": str(ev.get("id", "")),
            "event_title": ev.get("title", ""),
            "category": ev.get("category") or "",
            "event_volume": float(ev.get("volume") or 0),
            "neg_risk": bool(ev.get("negRisk", False)),
            "end_date": ev.get("endDate", ""),
            "closed_time": ev.get("closedTime", ""),
            "market_id": mid,
            "market_question": m.get("question", ""),
            "market_volume": float(m.get("volume") or 0),
            "yes_token_id": str(tokens[0]),
            "no_token_id": str(tokens[1]),
            "resolution": resolution,
            "final_yes_price": prices[0] if prices else None,
            "final_no_price": prices[1] if prices and len(prices) >= 2 else None,
        })
    return rows


def fetch_resolved_markets(force=False):
    """
    Pull every resolved Polymarket constituent market in the sample window,
    chunked by month to avoid the Gamma offset cap. Caches to
    data/resolved_markets.csv. Returns the path.
    """
    if RAW_MARKETS.exists() and not force:
        n = sum(1 for _ in open(RAW_MARKETS)) - 1
        print(f"[cache] resolved markets: {n:,} rows at {RAW_MARKETS}")
        return RAW_MARKETS

    DATA_DIR.mkdir(exist_ok=True)
    dfrom, dto = _parse_dt(DATE_FROM), _parse_dt(DATE_TO)
    seen_ids = set()
    total = 0
    print(f"[fetch] resolved markets {DATE_FROM}..{DATE_TO}, "
          f"min event volume ${MIN_EVENT_VOLUME:,}")

    with open(RAW_MARKETS, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=_RAW_FIELDS)
        writer.writeheader()
        for cstart, cend in _month_chunks(dfrom, dto):
            offset, events = 0, []
            while True:
                try:
                    page = _http_get_json(f"{GAMMA_API}/events", params={
                        "limit": PAGE_LIMIT, "offset": offset, "closed": "true",
                        "end_date_min": cstart, "end_date_max": cend,
                    })
                except HTTPError as e:
                    if e.code == 422:
                        print(f"    offset cap hit in {cstart}; "
                              f"month may need finer chunking")
                        break
                    raise
                if not page:
                    break
                events.extend(page)
                if len(page) < PAGE_LIMIT or offset >= OFFSET_CAP:
                    break
                offset += PAGE_LIMIT
                time.sleep(SLEEP_BETWEEN_PAGES)

            chunk_rows = 0
            for ev in events:
                for row in _event_to_rows(ev, seen_ids, dfrom, dto):
                    writer.writerow(row)
                    chunk_rows += 1
                    total += 1
            f.flush()
            print(f"    {cstart}: {len(events)} events, +{chunk_rows} markets "
                  f"(total {total:,})")
            time.sleep(SLEEP_BETWEEN_MONTHS)

    print(f"[done] wrote {total:,} markets to {RAW_MARKETS}")
    return RAW_MARKETS


# ---------------------------------------------------------------------------
# Stage 2: price-history snapshots from CLOB.
# ---------------------------------------------------------------------------

def _fetch_price_series(token_id):
    """Return list of (timestamp, price) for a token, or [] on failure."""
    try:
        data = _http_get_json(f"{CLOB_API}/prices-history", params={
            "market": token_id, "interval": "max", "fidelity": CLOB_FIDELITY,
        })
    except (RuntimeError, HTTPError):
        return []
    history = data.get("history") if isinstance(data, dict) else None
    if not history:
        return []
    return [(int(p["t"]), float(p["p"])) for p in history if "t" in p and "p" in p]


def _snapshot_at(series, target_ts):
    """Price from the series bin nearest to (and not after) target_ts."""
    if not series:
        return None
    candidates = [(t, p) for t, p in series if t <= target_ts]
    if not candidates:
        return None
    return min(candidates, key=lambda tp: target_ts - tp[0])[1]


def fetch_snapshots(force=False):
    """
    For each resolved market, add three pre-resolution YES-price snapshots
    (7d, 24h, and final bin before close) from the CLOB API. Caches to
    data/markets_with_snapshots.csv. Returns the path.

    This is the slow stage: one or two API calls per market across ~247K
    markets. The existing project ran it in ~6 hours with parallel workers;
    this reference version is sequential and resumable. For a parallel
    version see fetch_price_history_parallel.py in the project history.
    """
    if SNAPSHOTS.exists() and not force:
        n = sum(1 for _ in open(SNAPSHOTS)) - 1
        print(f"[cache] snapshots: {n:,} rows at {SNAPSHOTS}")
        return SNAPSHOTS
    if not RAW_MARKETS.exists():
        raise FileNotFoundError("run fetch_resolved_markets() first")

    rows = list(csv.DictReader(open(RAW_MARKETS, encoding="utf-8")))
    out_fields = list(rows[0].keys()) + list(SNAPSHOT_COLS)
    done = 0

    with open(SNAPSHOTS, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=out_fields)
        writer.writeheader()
        for r in rows:
            end_dt = _parse_dt(r.get("end_date") or r.get("closed_time"))
            series = _fetch_price_series(r["yes_token_id"]) if end_dt else []
            if end_dt and series:
                end_ts = int(end_dt.timestamp())
                r["snap_final"] = _snapshot_at(series, end_ts)
                r["snap_24h_pre"] = _snapshot_at(series, end_ts - 86_400)
                r["snap_7d_pre"] = _snapshot_at(series, end_ts - 7 * 86_400)
            else:
                r["snap_final"] = r["snap_24h_pre"] = r["snap_7d_pre"] = None
            writer.writerow(r)
            done += 1
            if done % 5000 == 0:
                f.flush()
                print(f"    {done:,} markets snapshotted")
            time.sleep(0.05)

    print(f"[done] wrote {done:,} snapshotted markets to {SNAPSHOTS}")
    return SNAPSHOTS
