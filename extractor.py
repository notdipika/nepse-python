"""
extractor.py  ─  Stage 1: Extract
Polls merolagani chart API and appends rows to data/raw.csv
Auto-runs from 11:00 AM to 3:00 PM NPT on trading days.
"""
import time
import random
import signal
import csv
from datetime import datetime, date, timedelta, timezone
from pathlib import Path

import requests

UTC = timezone.utc

from config import (
    NPT, MARKET_OPEN, MARKET_CLOSE, POLL_MIN, POLL_MAX,
    CHART_URL, HTTP_HEADERS, NEPALI_HOLIDAYS,
    CIRCUIT_BREAKERS, RAW_CSV, DEFAULT_SYMBOLS,
)
from logger import get_logger

log = get_logger("extractor")

SESSION = requests.Session()
SESSION.headers.update(HTTP_HEADERS)

_stop = False

# ─── Helpers ──────────────────────────────────────────────────────────────────

def now_npt() -> datetime:
    return datetime.now(NPT)

def to_unix(d: str) -> int:
    return int(datetime.strptime(d, "%Y-%m-%d").timestamp())

def is_trading_day(d: date | None = None) -> bool:
    if d is None:
        d = now_npt().date()
    if d.isoweekday() in (5, 6):
        return False
    if d.strftime("%Y-%m-%d") in NEPALI_HOLIDAYS:
        return False
    return True

def market_status() -> str:
    t = (now_npt().hour, now_npt().minute)
    if t < MARKET_OPEN:
        return "before"
    if t >= MARKET_CLOSE:
        return "after"
    return "open"

# ─── Fetch single symbol ──────────────────────────────────────────────────────

def fetch_ohlcv(symbol: str) -> dict | None:
    n   = now_npt()
    td  = n.strftime("%Y-%m-%d")
    yd  = (n.date() - timedelta(days=10)).strftime("%Y-%m-%d")
    url = CHART_URL.format(sym=symbol, fr=to_unix(yd), to=to_unix(td) + 86400)

    try:
        r = SESSION.get(url, timeout=20)
        r.raise_for_status()
        data = r.json()
    except Exception as e:
        log.warning(f"[{symbol}] fetch error: {e}")
        return None

    if data.get("s") != "ok" or not data.get("t"):
        log.warning(f"[{symbol}] no data returned")
        return None

    try:
        c_list = data["c"]
        last   = len(c_list) - 1
        close  = float(c_list[last])
        prev   = float(c_list[last - 1]) if last > 0 else None
        pct    = round((close - prev) / prev * 100, 2) if prev and prev > 0 else None
        ts     = data["t"][last]
        day    = datetime.fromtimestamp(ts, UTC).strftime("%Y-%m-%d")

        return {
            "fetched_at": now_npt().strftime("%Y-%m-%d %H:%M:%S"),
            "symbol":     symbol,
            "date":       day,
            "open":       float(data["o"][last]),
            "high":       float(data["h"][last]),
            "low":        float(data["l"][last]),
            "close":      close,
            "volume":     int(data["v"][last]),
            "prev_close": prev,
            "pct_change": pct,
        }
    except Exception as e:
        log.error(f"[{symbol}] parse error: {e}")
        return None

# ─── Write to CSV ─────────────────────────────────────────────────────────────

FIELDNAMES = [
    "fetched_at", "symbol", "date", "open", "high",
    "low", "close", "volume", "prev_close", "pct_change",
]

def append_rows(rows: list[dict]):
    exists = RAW_CSV.exists()
    with open(RAW_CSV, "a", newline="") as f:
        w = csv.DictWriter(f, fieldnames=FIELDNAMES)
        if not exists:
            w.writeheader()
        for r in rows:
            if r:
                w.writerow(r)
    log.info(f"Appended {len([r for r in rows if r])} row(s) to {RAW_CSV.name}")

# ─── Circuit breaker ─────────────────────────────────────────────────────────

def check_circuit(rows: list[dict]) -> tuple[bool, str | None, int]:
    """Returns (day_closed, halt_message, halt_minutes)"""
    nepse_row = next((r for r in rows if r and r["symbol"] == "NEPSE"), None)
    if not nepse_row or nepse_row.get("pct_change") is None:
        return False, None, 0
    pct = abs(float(nepse_row["pct_change"]))
    for threshold, halt_min, closes in CIRCUIT_BREAKERS:
        if pct >= threshold:
            msg = f"NEPSE {nepse_row['pct_change']:+.2f}% — {'CLOSED for day' if closes else f'{halt_min}-min halt'}"
            return closes, msg, halt_min
    return False, None, 0

# ─── Main loop ────────────────────────────────────────────────────────────────

def run_extractor(symbols: list[str] | None = None):
    global _stop
    _stop = False

    if symbols is None:
        symbols = DEFAULT_SYMBOLS

    def handle_exit(sig, frame):
        global _stop
        _stop = True
        log.info("Extractor shutting down …")

    signal.signal(signal.SIGINT, handle_exit)
    signal.signal(signal.SIGTERM, handle_exit)

    log.info(f"Extractor started. Watchlist: {symbols}")
    poll = 0
    halt_until: datetime | None = None
    day_closed = False

    while not _stop:
        if not is_trading_day():
            log.info("Not a trading day. Sleeping 1 hour …")
            time.sleep(3600)
            continue

        st = market_status()
        if st == "before":
            n = now_npt()
            open_dt = datetime(n.year, n.month, n.day,
                               MARKET_OPEN[0], MARKET_OPEN[1], tzinfo=NPT)
            wait_s = max(0, int((open_dt - n).total_seconds()))
            log.info(f"Market not yet open. Waiting {wait_s}s …")
            time.sleep(min(wait_s, 60))
            continue

        if st == "after" or day_closed:
            log.info("Market closed for today. Exiting extractor loop.")
            break

        now = now_npt()
        if halt_until and now < halt_until:
            rem = int((halt_until - now).total_seconds())
            log.info(f"Circuit breaker halt active. Resuming in {rem}s …")
            time.sleep(30)
            continue
        elif halt_until and now >= halt_until:
            halt_until = None
            log.info("Circuit breaker halt lifted. Resuming polling.")

        # Fetch
        poll += 1
        log.info(f"Poll #{poll} — fetching {len(symbols)} symbol(s) …")
        rows = [fetch_ohlcv(sym) for sym in symbols]
        append_rows(rows)

        # Circuit breaker
        day_closed, halt_msg, halt_min = check_circuit(rows)
        if day_closed:
            log.warning(f"CIRCUIT BREAKER: {halt_msg}")
            break
        if halt_msg:
            halt_until = now_npt() + timedelta(minutes=halt_min)
            log.warning(f"CIRCUIT BREAKER: {halt_msg}")

        # Sleep until next poll
        interval = random.randint(POLL_MIN, POLL_MAX)
        log.info(f"Next poll in {interval}s …")
        for _ in range(interval):
            if _stop or market_status() == "after":
                break
            time.sleep(1)

    log.info("Extractor finished.")


if __name__ == "__main__":
    run_extractor()
