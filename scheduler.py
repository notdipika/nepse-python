"""
scheduler.py  ─  Stage 5: Automate
Runs the full ETL pipeline automatically on every trading day:
  • Waits until 11:00 AM NPT
  • Extracts until 3:00 PM NPT
  • Transforms, visualises, and generates PDF report
  • Repeats next trading day

Usage:
    python scheduler.py                    # live scheduler
    python scheduler.py --once            # run once immediately (for testing)
"""
import time
import argparse
from datetime import datetime, timedelta

from config import NPT, MARKET_OPEN, NEPALI_HOLIDAYS, DEFAULT_SYMBOLS
from logger import get_logger

log = get_logger("scheduler")


def now_npt() -> datetime:
    return datetime.now(NPT)

def is_trading_day() -> bool:
    d = now_npt().date()
    if d.isoweekday() in (5, 6):
        return False
    if d.strftime("%Y-%m-%d") in NEPALI_HOLIDAYS:
        return False
    return True

def next_open_dt() -> datetime:
    n = now_npt()
    d = n.date()
    # If today is trading day and before open
    if is_trading_day():
        t = (n.hour, n.minute)
        if t < MARKET_OPEN:
            return datetime(d.year, d.month, d.day,
                            MARKET_OPEN[0], MARKET_OPEN[1], tzinfo=NPT)
    # Find next trading day
    d += timedelta(days=1)
    while True:
        if d.isoweekday() not in (5, 6) and d.strftime("%Y-%m-%d") not in NEPALI_HOLIDAYS:
            break
        d += timedelta(days=1)
    return datetime(d.year, d.month, d.day,
                    MARKET_OPEN[0], MARKET_OPEN[1], tzinfo=NPT)


def wait_for_open():
    """Block until the next market open, logging countdown."""
    while True:
        n   = now_npt()
        nxt = next_open_dt()
        delta = (nxt - n).total_seconds()
        if delta <= 0:
            return
        h, rem = divmod(int(delta), 3600)
        m, s   = divmod(rem, 60)
        log.info(f"Market opens at {nxt.strftime('%a %d %b %Y  11:00 AM NPT')} "
                 f"({h}h {m:02d}m {s:02d}s)")
        # Sleep in chunks so the log isn't flooded
        sleep_s = min(delta, 600)   # check every 10 min max
        time.sleep(sleep_s)


def run_trading_day(symbols: list[str]):
    """Run the full pipeline for one trading day."""
    from pipeline import stage_extract, stage_transform, stage_load, stage_report
    import pandas as pd

    log.info("=" * 60)
    log.info(f"TRADING DAY  {now_npt().strftime('%a %d %b %Y')}")
    log.info("=" * 60)

    # Stage 1 — Extract (runs until 3 PM or _stop)
    stage_extract(symbols)

    # Stage 2 — Transform
    try:
        df = stage_transform()
    except FileNotFoundError:
        log.error("raw.csv not found after extraction — aborting day.")
        return

    # Stage 3/4 — Load + Visualise
    charts = stage_load(df)

    # Stage 5 — Report
    report_path = stage_report(charts, df)
    log.info(f"Day complete. Report: {report_path}")


def scheduler_loop(symbols: list[str]):
    log.info("NEPSE ETL Scheduler started. Running daily, Sun–Thu, 11AM–3PM NPT.")
    while True:
        if not is_trading_day():
            log.info(f"Today ({now_npt().strftime('%A')}) is not a trading day.")
            wait_for_open()
        
        n = now_npt()
        t = (n.hour, n.minute)
        if t < MARKET_OPEN:
            wait_for_open()
        
        # It's a trading day at or after market open — run the day
        run_trading_day(symbols)

        # After day completes, sleep until next open
        log.info("Waiting for next trading day …")
        wait_for_open()


def main():
    parser = argparse.ArgumentParser(description="NEPSE ETL Scheduler")
    parser.add_argument("--symbols", nargs="+", default=DEFAULT_SYMBOLS)
    parser.add_argument("--once",    action="store_true",
                        help="Run pipeline once right now (skip time checks)")
    args = parser.parse_args()

    if args.once:
        log.info("--once flag: running pipeline immediately.")
        run_trading_day(args.symbols)
    else:
        scheduler_loop(args.symbols)


if __name__ == "__main__":
    main()
