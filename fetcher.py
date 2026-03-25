"""
NEPSE Background ETL Daemon
============================
• Runs silently in the background (no terminal UI)
• Automatically waits until 11:00 AM NPT, then starts fetching
• Polls merolagani chart API every 3–5 minutes (cache-matched jitter)
• Appends every fetch to  uncleaned.csv  in the same directory as this script
• Automatically stops at 15:00 NPT (or earlier on ±10% circuit breaker)
• Handles Nepali public holidays and non-trading days (Fri/Sat)
• Detects circuit breakers (±4% / ±6% halts, ±10% day close)
• Writes a human-readable log to  nepse_daemon.log

Usage:
    # Foreground (you see log output):
        python nepse_daemon.py

    # Background (detached from terminal):
        nohup python nepse_daemon.py &

    # Or using the bundled launcher script:
        bash start_nepse.sh

Stop:
    kill $(cat nepse_daemon.pid)          # if using the launcher
    Ctrl+C                                # if running in foreground
"""

import csv
import logging
import os
import random
import signal
import sys
import time
from datetime import date,datetime, timezone, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

import requests

UTC = timezone.utc

# ── Paths ──────────────────────────────────────────────────────────────────────
BASE_DIR   = Path(__file__).parent.resolve()
CSV_PATH   = BASE_DIR / "uncleaned.csv"
LOG_PATH   = BASE_DIR / "nepse_daemon.log"
PID_PATH   = BASE_DIR / "nepse_daemon.pid"

# ── Timezone ───────────────────────────────────────────────────────────────────
NPT = ZoneInfo("Asia/Kathmandu")

# ── Market constants ───────────────────────────────────────────────────────────
MARKET_OPEN_H,  MARKET_OPEN_M  = 11, 0
MARKET_CLOSE_H, MARKET_CLOSE_M = 15, 0
POLL_MIN = 180   # 3 minutes
POLL_MAX = 300   # 5 minutes

# ── Circuit breaker tiers ──────────────────────────────────────────────────────
# (abs_pct_threshold, halt_minutes, closes_day)
CIRCUIT_BREAKERS = [
    (10.0,  0,  True),
    ( 6.0, 40, False),
    ( 4.0, 20, False),
]

# ── Nepali public holidays (AD dates, YYYY-MM-DD) ──────────────────────────────
NEPALI_HOLIDAYS = {
    "2026-01-14",  # Maghe Sankranti
    "2026-02-07",  # Sonam Losar
    "2026-02-26",  # Maha Shivaratri
    "2026-03-04",  # Fagu Purnima
    "2026-04-14",  # Nepali New Year
    "2026-05-01",  # Labour Day
    "2026-05-29",  # Republic Day
    "2026-05-31",  # Buddha Jayanti
    "2026-08-28",  # Janai Purnima
    "2026-09-04",  # Krishna Janmashtami
    "2026-09-19",  # Constitution Day
    "2026-10-11",  # Ghatasthapana
    "2026-10-17",  # Phulpati
    "2026-10-19",  # Maha Astami
    "2026-10-20",  # Maha Nawami
    "2026-10-21",  # Vijaya Dashami
    "2026-10-22",  # Ekadashi
    "2026-10-23",  # Duwadashi
    "2026-11-08",  # Laxmi Puja
    "2026-11-09",  # Govardhan Puja
    "2026-11-10",  # Bhai Tika
    "2026-11-15",  # Chhath Parva
    "2026-12-30",  # Tamu Lhosar
}

# ── CSV columns ────────────────────────────────────────────────────────────────
CSV_FIELDNAMES = [
    "fetched_at_npt",   # timestamp of the fetch  (HH:MM:SS)
    "fetch_date",       # date of the fetch        (YYYY-MM-DD)
    "symbol",
    "candle_date",      # date of the OHLCV candle (YYYY-MM-DD)
    "open",
    "high",
    "low",
    "close",
    "volume",
    "prev_close",
    "pct_change",
    "poll_number",
    "circuit_status",   # "none" / "halt_4" / "halt_6" / "day_close"
]

# ── API ────────────────────────────────────────────────────────────────────────
CHART_URL = (
    "https://www.merolagani.com/handlers/TechnicalChartHandler.ashx"
    "?type=get_advanced_chart&symbol={sym}&resolution=1D"
    "&rangeStartDate={fr}&rangeEndDate={to}"
    "&from=&isAdjust=1&currencyCode=NPR"
)

SESSION = requests.Session()
SESSION.headers.update({
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0 Safari/537.36"
    ),
    "Accept":   "*/*",
    "Origin":   "https://www.merolagani.com",
    "Referer":  "https://www.merolagani.com/",
})

# ── Logging setup ──────────────────────────────────────────────────────────────
def setup_logging():
    fmt = "%(asctime)s  %(levelname)-8s  %(message)s"
    datefmt = "%Y-%m-%d %H:%M:%S"
    logging.basicConfig(
        level=logging.INFO,
        format=fmt,
        datefmt=datefmt,
        handlers=[
            logging.FileHandler(LOG_PATH, encoding="utf-8"),
            logging.StreamHandler(sys.stdout),
        ],
    )

log = logging.getLogger("nepse_etl")

# ── Helpers ────────────────────────────────────────────────────────────────────
def now_npt() -> datetime:
    return datetime.now(NPT)

def to_unix(d: str) -> int:
    return int(datetime.strptime(d, "%Y-%m-%d").timestamp())

def is_trading_day(d: date | None = None) -> bool:
    if d is None:
        d = now_npt().date()
    # isoweekday: Mon=1 … Sun=7; NEPSE trades Sun(7)–Thu(4)
    if d.isoweekday() in (5, 6):          # Fri, Sat → closed
        return False
    if d.strftime("%Y-%m-%d") in NEPALI_HOLIDAYS:
        return False
    return True

def market_status() -> str:
    """Return 'before', 'open', or 'after'."""
    n = now_npt()
    t = (n.hour, n.minute)
    if t < (MARKET_OPEN_H,  MARKET_OPEN_M):
        return "before"
    if t >= (MARKET_CLOSE_H, MARKET_CLOSE_M):
        return "after"
    return "open"

def seconds_until_open() -> float:
    """Seconds until the next market open (could be today or a future day)."""
    n = now_npt()
    d = n.date()

    if is_trading_day(d) and market_status() == "before":
        target = datetime(d.year, d.month, d.day,
                          MARKET_OPEN_H, MARKET_OPEN_M, tzinfo=NPT)
    else:
        d += timedelta(days=1)
        while not is_trading_day(d):
            d += timedelta(days=1)
        target = datetime(d.year, d.month, d.day,
                          MARKET_OPEN_H, MARKET_OPEN_M, tzinfo=NPT)

    return max(0.0, (target - n).total_seconds())

# ── CSV ────────────────────────────────────────────────────────────────────────
def ensure_csv_header():
    """Write header row if file is new/empty."""
    if not CSV_PATH.exists() or CSV_PATH.stat().st_size == 0:
        with open(CSV_PATH, "w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=CSV_FIELDNAMES)
            writer.writeheader()
        log.info("Created %s with header.", CSV_PATH.name)

def append_rows(rows: list[dict]):
    """Append a list of row-dicts to uncleaned.csv."""
    with open(CSV_PATH, "a", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=CSV_FIELDNAMES)
        writer.writerows(rows)

# ── Fetch ──────────────────────────────────────────────────────────────────────
def fetch_ohlcv(symbol: str) -> dict | None:
    """
    Fetch latest OHLCV candle for *symbol*.
    Returns a dict on success, or None on failure.
    """
    n   = now_npt()
    td  = n.strftime("%Y-%m-%d")
    yd  = (n.date() - timedelta(days=10)).strftime("%Y-%m-%d")
    fr  = to_unix(yd)
    to_ = to_unix(td) + 86400
    url = CHART_URL.format(sym=symbol, fr=fr, to=to_)

    try:
        r = SESSION.get(url, timeout=20)
        r.raise_for_status()
        data = r.json()
    except Exception as exc:
        log.warning("Fetch error [%s]: %s", symbol, exc)
        return None

    if data.get("s") != "ok" or not data.get("t"):
        log.warning("No data for %s (status=%s)", symbol, data.get("s"))
        return None

    try:
        c_list = data["c"]
        last   = len(c_list) - 1
        close  = float(c_list[last])
        prev   = float(c_list[last - 1]) if last > 0 else None
        pct    = round((close - prev) / prev * 100, 4) if prev and prev > 0 else None
        candle_date = datetime.fromtimestamp(data["t"][last], UTC).strftime("%Y-%m-%d")

        return {
            "symbol":      symbol,
            "candle_date": candle_date,
            "open":        float(data["o"][last]),
            "high":        float(data["h"][last]),
            "low":         float(data["l"][last]),
            "close":       close,
            "volume":      int(data["v"][last]),
            "prev_close":  prev,
            "pct_change":  pct,
        }
    except Exception as exc:
        log.warning("Parse error [%s]: %s", symbol, exc)
        return None

# ── Main daemon loop ───────────────────────────────────────────────────────────
_stop = False

def handle_signal(sig, frame):
    global _stop
    log.info("Signal %s received — shutting down.", sig)
    _stop = True

def run(symbols: list[str]):
    global _stop

    signal.signal(signal.SIGINT,  handle_signal)
    signal.signal(signal.SIGTERM, handle_signal)

    # Write PID file so the launcher/user can stop the process easily
    PID_PATH.write_text(str(os.getpid()))
    log.info("PID %d written to %s", os.getpid(), PID_PATH.name)

    ensure_csv_header()

    log.info("Watchlist: %s", ", ".join(symbols))
    log.info("CSV output: %s", CSV_PATH)
    log.info("Log file:   %s", LOG_PATH)

    poll         = 0
    day_closed   = False
    halt_until   = None   # datetime — when a circuit-breaker halt ends
    circuit_tag  = "none"

    while not _stop:

        # ── Non-trading day ────────────────────────────────────────────────
        if not is_trading_day():
            wait_s = seconds_until_open()
            log.info(
                "Today (%s) is not a trading day. "
                "Sleeping %.0f s until next open.",
                now_npt().strftime("%A %Y-%m-%d"), wait_s,
            )
            _sleep(wait_s)
            day_closed  = False
            halt_until  = None
            circuit_tag = "none"
            continue

        status = market_status()

        # ── Before market open ─────────────────────────────────────────────
        if status == "before":
            wait_s = seconds_until_open()
            log.info(
                "Market opens at 11:00 NPT. Sleeping %.0f s (%.1f min).",
                wait_s, wait_s / 60,
            )
            _sleep(wait_s)
            continue

        # ── Market closed for the day (after 15:00 or day circuit breaker) ─
        if status == "after" or day_closed:
            if day_closed:
                log.info("Day circuit breaker active. Done for today.")
            else:
                log.info("Market closed at 15:00 NPT. Done for today.")

            wait_s = seconds_until_open()
            log.info("Sleeping %.0f s until next trading session.", wait_s)
            _sleep(wait_s)
            day_closed  = False
            halt_until  = None
            circuit_tag = "none"
            continue

        # ── Circuit-breaker halt still active ─────────────────────────────
        if halt_until and now_npt() < halt_until:
            rem = (halt_until - now_npt()).total_seconds()
            log.info("Circuit-breaker halt active. Resuming in %.0f s.", rem)
            _sleep(min(rem, 30))   # wake every 30 s to recheck
            continue
        elif halt_until and now_npt() >= halt_until:
            log.info("Circuit-breaker halt lifted.")
            halt_until  = None
            circuit_tag = "none"

        # ── Fetch cycle ────────────────────────────────────────────────────
        poll += 1
        n_str  = now_npt().strftime("%H:%M:%S")
        d_str  = now_npt().strftime("%Y-%m-%d")
        log.info("Poll #%d — fetching %d symbol(s).", poll, len(symbols))

        rows = []
        for sym in symbols:
            if _stop:
                break
            result = fetch_ohlcv(sym)
            if result:
                rows.append({
                    "fetched_at_npt": n_str,
                    "fetch_date":     d_str,
                    "symbol":         result["symbol"],
                    "candle_date":    result["candle_date"],
                    "open":           result["open"],
                    "high":           result["high"],
                    "low":            result["low"],
                    "close":          result["close"],
                    "volume":         result["volume"],
                    "prev_close":     result["prev_close"],
                    "pct_change":     result["pct_change"],
                    "poll_number":    poll,
                    "circuit_status": circuit_tag,
                })
                log.info(
                    "  %s  close=%.2f  chg=%s%%",
                    sym, result["close"],
                    f"{result['pct_change']:+.2f}" if result["pct_change"] is not None else "N/A",
                )
            else:
                log.warning("  %s  — no data this poll.", sym)

        if rows:
            append_rows(rows)
            log.info("Appended %d row(s) to %s.", len(rows), CSV_PATH.name)

        # ── Circuit breaker check (NEPSE index) ───────────────────────────
        idx = fetch_ohlcv("NEPSE")
        if idx and idx["pct_change"] is not None:
            idx_pct = idx["pct_change"]
            for threshold, halt_min, closes_day in CIRCUIT_BREAKERS:
                if abs(idx_pct) >= threshold:
                    if closes_day:
                        log.warning(
                            "NEPSE %+.2f%% — ±10%% circuit breaker! "
                            "Market closed for the day.", idx_pct,
                        )
                        day_closed  = True
                        circuit_tag = "day_close"
                    else:
                        halt_until  = now_npt() + timedelta(minutes=halt_min)
                        circuit_tag = f"halt_{int(threshold)}"
                        log.warning(
                            "NEPSE %+.2f%% — %d-min circuit-breaker halt. "
                            "Resumes ~%s NPT.",
                            idx_pct, halt_min,
                            halt_until.strftime("%H:%M"),
                        )
                    break

        if day_closed or _stop:
            continue

        # ── Sleep until next poll (3–5 min jitter) ────────────────────────
        interval = random.randint(POLL_MIN, POLL_MAX)
        wake_at  = now_npt() + timedelta(seconds=interval)
        log.info("Next poll at ~%s NPT (%d s).", wake_at.strftime("%H:%M:%S"), interval)
        _sleep(interval)

    log.info("Daemon stopped cleanly.")
    if PID_PATH.exists():
        PID_PATH.unlink()

def _sleep(seconds: float):
    """Interruptible sleep — wakes every second to honour _stop."""
    global _stop
    end = time.monotonic() + max(0.0, seconds)
    while not _stop and time.monotonic() < end:
        time.sleep(min(1.0, end - time.monotonic()))

# ── Entry point ────────────────────────────────────────────────────────────────
def main():
    setup_logging()
    log.info("=" * 60)
    log.info("NEPSE ETL Daemon starting up.")

    # ── Symbol list: pass as CLI args or edit the default list below ──────
    if len(sys.argv) > 1:
        symbols = [s.strip().upper() for s in " ".join(sys.argv[1:]).replace(",", " ").split() if s.strip()]
    else:
        # DEFAULT WATCHLIST — edit to suit your needs
        symbols = [
            "NEPSE",
            "NABIL",
            "ADBL",
            "SCB",
            "NTC",
            "NICA",
            "UPPER",
        ]

    symbols = list(dict.fromkeys(symbols))   # dedupe, preserve order
    log.info("Symbols: %s", symbols)
    run(symbols)

if __name__ == "__main__":
    main()