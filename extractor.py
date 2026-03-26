"""
extractor.py  ─  Stage 1: Extract
Polls merolagani chart API and appends rows to data/raw.csv.

raw.csv accumulates ALL rows from the current trading session.
It is only archived and reset at the start of the NEXT trading day.
Restarting mid-session is safe — it keeps appending, no data lost.
"""
import time
import random
import signal
import csv
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

log     = get_logger("extractor")
SESSION = requests.Session()
SESSION.headers.update(HTTP_HEADERS)
UTC     = timezone.utc

_stop          = False
MAX_RETRIES    = 4
BASE_BACKOFF_S = 2

# Rolling buffer of recent close prices per symbol (for MA calculation)
_close_buf: dict[str, deque] = defaultdict(lambda: deque(maxlen=20))

FIELDNAMES = [
    "fetched_at", "symbol", "date", "open", "high",
    "low", "close", "volume", "prev_close", "pct_change",
    "ma5", "ma10", "ma20",
]

# Stamp file: records which trading-day raw.csv belongs to.
# Used to archive once per day and not on every restart.
_SESSION_STAMP = RAW_CSV.parent / ".raw_session_date"


# ─── Small helpers ─────────────────────────────────────────────────────────────

def now_npt() -> datetime:
    return datetime.now(NPT)

def to_unix(d: str) -> int:
    return int(datetime.strptime(d, "%Y-%m-%d").timestamp())

def is_trading_day(d: date | None = None) -> bool:
    d = d or now_npt().date()
    return d.isoweekday() not in (5, 6) and d.strftime("%Y-%m-%d") not in NEPALI_HOLIDAYS

def market_status() -> str:
    t = (now_npt().hour, now_npt().minute)
    if t < MARKET_OPEN:   return "before"
    if t >= MARKET_CLOSE: return "after"
    return "open"

def _ma(buf: deque, n: int) -> float | None:
    """Rolling average of last n values. Returns None if not enough data."""
    return round(sum(list(buf)[-n:]) / n, 2) if len(buf) >= n else None


# ─── Session stamp ─────────────────────────────────────────────────────────────

def _read_stamp() -> str:
    try:
        return _SESSION_STAMP.read_text().strip()
    except FileNotFoundError:
        return ""

def _write_stamp(date_str: str):
    _SESSION_STAMP.write_text(date_str)


# ─── Archive & reset raw.csv at the start of each new trading day ─────────────

def _archive_and_reset():
    """
    Called once at the start of every new trading day.
    - Copies old raw.csv into data/archive/raw_YYYY-MM-DD.csv
    - Starts a fresh empty raw.csv
    - Updates the stamp so this won't repeat until tomorrow
    """
    today = now_npt().strftime("%Y-%m-%d")
    if _read_stamp() == today:
        log.debug("Session stamp matches today — raw.csv already fresh.")
        return

    archive_dir = RAW_CSV.parent / "archive"
    archive_dir.mkdir(exist_ok=True)

    if RAW_CSV.exists() and RAW_CSV.stat().st_size > 0:
        try:
            with open(RAW_CSV, newline="", encoding="utf-8") as f:
                rows = list(csv.DictReader(f))
            old_date = (rows[0].get("date", "")[:10] if rows else "") or "unknown"
        except Exception:
            rows, old_date = [], "unknown"

        if rows:
            archive_path = archive_dir / f"raw_{old_date}.csv"
            mode, write_header = ("a", False) if archive_path.exists() else ("w", True)
            try:
                with open(archive_path, mode, newline="", encoding="utf-8") as f:
                    w = csv.DictWriter(f, fieldnames=FIELDNAMES, extrasaction="ignore")
                    if write_header:
                        w.writeheader()
                    w.writerows(rows)
                log.info(f"Archived {len(rows)} rows → {archive_path.name}")
            except Exception as e:
                log.error(f"Archive failed: {e}")

    # Write a fresh empty raw.csv with headers only
    with open(RAW_CSV, "w", newline="", encoding="utf-8") as f:
        csv.DictWriter(f, fieldnames=FIELDNAMES).writeheader()
    log.info("raw.csv reset for new session.")
    _write_stamp(today)


# ─── Schema migration (one-time fix for old files missing MA columns) ──────────

def _ensure_schema():
    if not RAW_CSV.exists():
        return
    try:
        with open(RAW_CSV, "r", newline="", encoding="utf-8") as f:
            existing = csv.DictReader(f).fieldnames or []
        if "ma5" in existing:
            return  # already up to date
        with open(RAW_CSV, "r", newline="", encoding="utf-8") as f:
            rows = list(csv.DictReader(f))
        merged = list(dict.fromkeys(list(existing) + ["ma5", "ma10", "ma20"]))
        with open(RAW_CSV, "w", newline="", encoding="utf-8") as f:
            w = csv.DictWriter(f, fieldnames=merged, extrasaction="ignore")
            w.writeheader()
            for r in rows:
                r.setdefault("ma5", "")
                r.setdefault("ma10", "")
                r.setdefault("ma20", "")
                w.writerow(r)
        log.info("raw.csv schema migrated — added ma5/ma10/ma20 columns.")
    except Exception as e:
        log.error(f"Schema migration failed: {e}")


# ─── Fetch one symbol with retry ───────────────────────────────────────────────

def fetch_ohlcv(symbol: str) -> dict | None:
    """Fetch the latest OHLCV candle for a symbol. Returns None on failure."""
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
                wait = BASE_BACKOFF_S * (2 ** (attempt - 1)) + random.uniform(0, 1)
                log.warning(f"[{symbol}] attempt {attempt}/{MAX_RETRIES} failed: {e} — retry in {wait:.1f}s")
                time.sleep(wait)
            else:
                log.error(f"[{symbol}] all {MAX_RETRIES} attempts failed: {e}")
                return None

    if not data or data.get("s") != "ok" or not data.get("t"):
        log.warning(f"[{symbol}] no valid data")
        return None

    try:
        closes = data["c"]
        last   = len(closes) - 1
        close  = float(closes[last])
        prev   = float(closes[last - 1]) if last > 0 else None
        pct    = round((close - prev) / prev * 100, 2) if prev else None
        day    = datetime.fromtimestamp(data["t"][last], UTC).strftime("%Y-%m-%d")

        if day != now_npt().strftime("%Y-%m-%d"):
            log.info(f"[{symbol}] latest candle is {day}, not today — skipping")
            return None

        _close_buf[symbol].append(close)
        buf = _close_buf[symbol]

        return {
            "fetched_at": n.strftime("%Y-%m-%d %H:%M:%S"),
            "symbol":     symbol,
            "date":       day,
            "open":       float(data["o"][last]),
            "high":       float(data["h"][last]),
            "low":        float(data["l"][last]),
            "close":      close,
            "volume":     int(data["v"][last]),
            "prev_close": prev if prev is not None else "",
            "pct_change": pct  if pct  is not None else "",
            "ma5":  _ma(buf,  5) or "",
            "ma10": _ma(buf, 10) or "",
            "ma20": _ma(buf, 20) or "",
        }
    except Exception as e:
        log.error(f"[{symbol}] parse error: {e}")
        return None


# ─── Write rows to raw.csv ─────────────────────────────────────────────────────

def append_rows(rows: list[dict]):
    valid = [r for r in rows if r]
    if not valid:
        return
    file_exists = RAW_CSV.exists()
    _ensure_schema()
    with open(RAW_CSV, "a", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=FIELDNAMES, extrasaction="ignore")
        if not file_exists:
            w.writeheader()
        w.writerows(valid)
    log.info(f"Appended {len(valid)} row(s) to raw.csv")


# ─── Circuit breaker check ─────────────────────────────────────────────────────

def check_circuit(rows: list[dict]) -> tuple[bool, str | None, int]:
    """Check if NEPSE's % change triggered a circuit breaker."""
    nepse = next((r for r in rows if r and r.get("symbol") == "NEPSE"), None)
    if not nepse or nepse.get("pct_change") in (None, ""):
        return False, None, 0
    pct = abs(float(nepse["pct_change"]))
    for threshold, halt_min, closes in CIRCUIT_BREAKERS:
        if pct >= threshold:
            status = "CLOSED for day" if closes else f"{halt_min}-min halt"
            msg = f"NEPSE {float(nepse['pct_change']):+.2f}% — {status}"
            return closes, msg, halt_min
    return False, None, 0


# ─── Main polling loop ─────────────────────────────────────────────────────────

def run_extractor(symbols: list[str] | None = None):
    """
    Poll merolagani every 3–5 minutes during market hours.
    Archives previous session data on first run of a new day.
    Stops automatically when market closes (15:00 NPT).
    """
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
    _archive_and_reset()
    _ensure_schema()

    poll        = 0
    halt_until  = None
    day_closed  = False

    while not _stop:
        if not is_trading_day():
            log.info("Not a trading day. Sleeping 1 hour …")
            time.sleep(3600)
            continue

        st = market_status()
        if st == "before":
            n        = now_npt()
            open_dt  = n.replace(hour=MARKET_OPEN[0], minute=MARKET_OPEN[1], second=0, microsecond=0)
            wait_s   = max(0, int((open_dt - n).total_seconds()))
            log.info(f"Market not yet open. Waiting {wait_s}s …")
            time.sleep(min(wait_s, 60))
            continue

        if st == "after" or day_closed:
            log.info("Market closed for today. Extractor loop done.")
            break

        now = now_npt()
        if halt_until:
            if now < halt_until:
                rem = int((halt_until - now).total_seconds())
                log.info(f"Circuit breaker halt. Resuming in {rem}s …")
                time.sleep(30)
                continue
            else:
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
