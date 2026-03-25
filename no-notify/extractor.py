"""
extractor.py  ─  Stage 1: Extract
Polls merolagani chart API and appends rows to data/raw.csv
Auto-runs from 11:00 AM to 3:00 PM NPT on trading days.

Improvements v2:
  • Retry logic with exponential back-off (up to 4 attempts per symbol)
  • Date-aware CSV rotation: stale rows archived to data/archive/raw_YYYY-MM-DD.csv
    raw.csv is NEVER deleted; historical data is always preserved
  • Moving averages (ma5, ma10, ma20) computed from rolling intraday closes
  • Schema auto-migration for older raw.csv files
"""
import time
import random
import signal
import csv
import math
from collections import defaultdict, deque
from datetime import datetime, date, timedelta, timezone
from pathlib import Path

import requests

from config import (
    NPT, MARKET_OPEN, MARKET_CLOSE, POLL_MIN, POLL_MAX,
    CHART_URL, HTTP_HEADERS, NEPALI_HOLIDAYS,
    CIRCUIT_BREAKERS, RAW_CSV, DEFAULT_SYMBOLS,
)
from logger import get_logger

log = get_logger("extractor")

SESSION = requests.Session()
SESSION.headers.update(HTTP_HEADERS)

UTC = timezone.utc

_stop = False

# ── Retry config ──────────────────────────────────────────────────────────────
MAX_RETRIES    = 4
BASE_BACKOFF_S = 2    # doubles each retry: 2, 4, 8, 16 s

# ── In-memory rolling close buffer for moving averages ───────────────────────
_close_buf: dict[str, deque] = defaultdict(lambda: deque(maxlen=20))

# ── CSV field names (extended with MA columns) ────────────────────────────────
FIELDNAMES = [
    "fetched_at", "symbol", "date", "open", "high",
    "low", "close", "volume", "prev_close", "pct_change",
    "ma5", "ma10", "ma20",
]


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
    if t < MARKET_OPEN:  return "before"
    if t >= MARKET_CLOSE: return "after"
    return "open"

def _ma(buf: deque, n: int) -> float | None:
    if len(buf) < n:
        return None
    return round(sum(list(buf)[-n:]) / n, 2)


# ─── Fetch with retry ─────────────────────────────────────────────────────────

def fetch_ohlcv(symbol: str) -> dict | None:
    n   = now_npt()
    td  = n.strftime("%Y-%m-%d")
    yd  = (n.date() - timedelta(days=10)).strftime("%Y-%m-%d")
    url = CHART_URL.format(sym=symbol, fr=to_unix(yd), to=to_unix(td) + 86400)

    data = None
    for attempt in range(1, MAX_RETRIES + 1):
        try:
            r = SESSION.get(url, timeout=20)
            r.raise_for_status()
            data = r.json()
            break
        except Exception as e:
            if attempt < MAX_RETRIES:
                sleep_s = BASE_BACKOFF_S * (2 ** (attempt - 1)) + random.uniform(0, 1)
                log.warning(f"[{symbol}] attempt {attempt}/{MAX_RETRIES} failed: {e} "
                            f"— retry in {sleep_s:.1f}s")
                time.sleep(sleep_s)
            else:
                log.error(f"[{symbol}] all {MAX_RETRIES} attempts failed: {e}")
                return None

    if not data or data.get("s") != "ok" or not data.get("t"):
        log.warning(f"[{symbol}] no valid data (status={data.get('s') if data else 'none'})")
        return None

    try:
        c_list = data["c"]
        last   = len(c_list) - 1
        close  = float(c_list[last])
        prev   = float(c_list[last - 1]) if last > 0 else None
        pct    = round((close - prev) / prev * 100, 2) if prev and prev > 0 else None
        ts     = data["t"][last]
        day    = datetime.fromtimestamp(ts, UTC).strftime("%Y-%m-%d")

        today = now_npt().strftime("%Y-%m-%d")
        if day != today:
            log.info(f"[{symbol}] latest candle is {day}, not today ({today}) — skipping")
            return None

        # Update rolling MA buffer
        _close_buf[symbol].append(close)
        buf = _close_buf[symbol]

        return {
            "fetched_at": now_npt().strftime("%Y-%m-%d %H:%M:%S"),
            "symbol":     symbol,
            "date":       day,
            "open":       float(data["o"][last]),
            "high":       float(data["h"][last]),
            "low":        float(data["l"][last]),
            "close":      close,
            "volume":     int(data["v"][last]),
            "prev_close": prev if prev is not None else "",
            "pct_change": pct  if pct  is not None else "",
            "ma5":        _ma(buf, 5)  if _ma(buf, 5)  is not None else "",
            "ma10":       _ma(buf, 10) if _ma(buf, 10) is not None else "",
            "ma20":       _ma(buf, 20) if _ma(buf, 20) is not None else "",
        }
    except Exception as e:
        log.error(f"[{symbol}] parse error: {e}")
        return None


# ─── Date-aware CSV rotation ─────────────────────────────────────────────────

def _archive_stale_rows():
    """
    Reads raw.csv, splits by date.
    Past-date rows → archived to data/archive/raw_YYYY-MM-DD.csv
    Today's rows   → kept in raw.csv (header rewritten cleanly)
    No data is ever deleted.
    """
    if not RAW_CSV.exists():
        return

    today = now_npt().strftime("%Y-%m-%d")

    try:
        with open(RAW_CSV, newline="", encoding="utf-8") as f:
            reader    = csv.DictReader(f)
            all_rows  = list(reader)
            file_fns  = list(reader.fieldnames or FIELDNAMES)
    except Exception as e:
        log.error(f"Could not read raw.csv for rotation: {e}")
        return

    stale = [r for r in all_rows if r.get("date", "")[:10] != today]
    fresh = [r for r in all_rows if r.get("date", "")[:10] == today]

    if not stale:
        return

    by_date: dict[str, list] = defaultdict(list)
    for row in stale:
        by_date[row.get("date", "unknown")[:10]].append(row)

    archive_dir = RAW_CSV.parent / "archive"
    archive_dir.mkdir(exist_ok=True)

    for d_str, rows in by_date.items():
        archive_path = archive_dir / f"raw_{d_str}.csv"
        exists       = archive_path.exists()
        with open(archive_path, "a", newline="", encoding="utf-8") as f:
            w = csv.DictWriter(f, fieldnames=file_fns, extrasaction="ignore")
            if not exists:
                w.writeheader()
            w.writerows(rows)
        log.info(f"Archived {len(rows)} rows → {archive_path.name}")

    # Rewrite raw.csv with only today's rows
    merged_fns = list(dict.fromkeys(file_fns + [c for c in FIELDNAMES if c not in file_fns]))
    with open(RAW_CSV, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=merged_fns, extrasaction="ignore")
        w.writeheader()
        w.writerows(fresh)

    log.info(f"raw.csv rotated — {len(fresh)} today-rows kept, {len(stale)} archived.")


def _ensure_schema():
    """Migrate raw.csv to include ma5/ma10/ma20 columns if missing."""
    if not RAW_CSV.exists():
        return
    try:
        with open(RAW_CSV, "r", newline="", encoding="utf-8") as f:
            existing_fn = csv.DictReader(f).fieldnames or []
        if "ma5" not in existing_fn:
            with open(RAW_CSV, "r", newline="", encoding="utf-8") as f:
                rows = list(csv.DictReader(f))
            with open(RAW_CSV, "w", newline="", encoding="utf-8") as f:
                merged = list(dict.fromkeys(list(existing_fn) + ["ma5", "ma10", "ma20"]))
                w = csv.DictWriter(f, fieldnames=merged, extrasaction="ignore")
                w.writeheader()
                for r in rows:
                    r.setdefault("ma5", ""); r.setdefault("ma10", ""); r.setdefault("ma20", "")
                    w.writerow(r)
            log.info("raw.csv schema migrated — added ma5/ma10/ma20 columns.")
    except Exception as e:
        log.error(f"Schema migration failed: {e}")


def append_rows(rows: list[dict]):
    valid  = [r for r in rows if r]
    if not valid:
        return
    exists = RAW_CSV.exists()
    _ensure_schema()
    with open(RAW_CSV, "a", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=FIELDNAMES, extrasaction="ignore")
        if not exists:
            w.writeheader()
        w.writerows(valid)
    log.info(f"Appended {len(valid)} row(s) to {RAW_CSV.name}")


# ─── Circuit breaker ─────────────────────────────────────────────────────────

def check_circuit(rows: list[dict]) -> tuple[bool, str | None, int]:
    nepse_row = next((r for r in rows if r and r.get("symbol") == "NEPSE"), None)
    if not nepse_row or nepse_row.get("pct_change") in (None, ""):
        return False, None, 0
    pct = abs(float(nepse_row["pct_change"]))
    for threshold, halt_min, closes in CIRCUIT_BREAKERS:
        if pct >= threshold:
            msg = (f"NEPSE {float(nepse_row['pct_change']):+.2f}% — "
                   f"{'CLOSED for day' if closes else f'{halt_min}-min halt'}")
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

    signal.signal(signal.SIGINT,  handle_exit)
    signal.signal(signal.SIGTERM, handle_exit)

    log.info(f"Extractor started. Watchlist: {symbols}")

    # On startup: archive any stale rows and migrate schema
    _archive_stale_rows()
    _ensure_schema()

    poll       = 0
    halt_until: datetime | None = None
    day_closed = False

    while not _stop:
        if not is_trading_day():
            log.info("Not a trading day. Sleeping 1 hour …")
            time.sleep(3600)
            continue

        st = market_status()
        if st == "before":
            n       = now_npt()
            open_dt = datetime(n.year, n.month, n.day,
                               MARKET_OPEN[0], MARKET_OPEN[1], tzinfo=NPT)
            wait_s  = max(0, int((open_dt - n).total_seconds()))
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

        poll += 1
        log.info(f"Poll #{poll} — fetching {len(symbols)} symbol(s) …")
        rows = [fetch_ohlcv(sym) for sym in symbols]
        append_rows(rows)

        day_closed, halt_msg, halt_min = check_circuit(rows)
        if day_closed:
            log.warning(f"CIRCUIT BREAKER: {halt_msg}")
            break
        if halt_msg:
            halt_until = now_npt() + timedelta(minutes=halt_min)
            log.warning(f"CIRCUIT BREAKER: {halt_msg}")

        interval = random.randint(POLL_MIN, POLL_MAX)
        log.info(f"Next poll in {interval}s …")
        for _ in range(interval):
            if _stop or market_status() == "after":
                break
            time.sleep(1)

    log.info("Extractor finished.")


if __name__ == "__main__":
    run_extractor()
