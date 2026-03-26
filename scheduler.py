"""
scheduler.py  ─  Automated daily scheduler

Behaviour:
  • AUTO FETCH : Starts the intraday extractor at 11:00 NPT (Sun–Thu),
                 runs in the background until market closes at 15:00 NPT.
                 raw.csv accumulates data automatically throughout.

  • AUTO REPORT: At 15:15 NPT, automatically runs transformer → report
                 → desktop notification → email, then exits.

  • MANUAL     : Use pipeline.py (or --report-now below) at any time to
                 run transformer/report/logger/notifier manually.

Usage:
  python scheduler.py                # run forever (daily loop)
  python scheduler.py --once         # run today then exit
  python scheduler.py --report-now   # report from raw.csv right now
  python scheduler.py --email a@x.com b@x.com  # override recipients

Cron alternatives (from project root):
  # Auto-start fetch at 10:55 AM every trading day (Sun–Thu)
  55 10 * * 0-4  cd /path/to/project && python scheduler.py --once >> logs/cron.log 2>&1
  # Fallback report trigger at 15:15 NPT
  15 15 * * 0-4  cd /path/to/project && python scheduler.py --report-now >> logs/cron.log 2>&1
"""
import time
import argparse
from datetime import datetime, timedelta

from config import (
    NPT, MARKET_OPEN, MARKET_CLOSE, NEPALI_HOLIDAYS,
    DEFAULT_SYMBOLS, REPORT_DELAY_MINUTES,
)
from logger import get_logger

log = get_logger("scheduler")

# Report fires REPORT_DELAY_MINUTES after MARKET_CLOSE (default: 15 mins → 15:15 NPT)
_REPORT_HOUR   = MARKET_CLOSE[0] + (MARKET_CLOSE[1] + REPORT_DELAY_MINUTES) // 60
_REPORT_MINUTE = (MARKET_CLOSE[1] + REPORT_DELAY_MINUTES) % 60


# ── Time helpers ───────────────────────────────────────────────────────────────

def now_npt() -> datetime:
    return datetime.now(NPT)

def is_trading_day(d=None) -> bool:
    d = d or now_npt().date()
    return d.isoweekday() not in (5, 6) and d.strftime("%Y-%m-%d") not in NEPALI_HOLIDAYS

def market_status() -> str:
    t = (now_npt().hour, now_npt().minute)
    if t < MARKET_OPEN:   return "before"
    if t >= MARKET_CLOSE: return "after"
    return "open"

def next_open_dt() -> datetime:
    d = now_npt().date()
    if is_trading_day(d) and (now_npt().hour, now_npt().minute) < MARKET_OPEN:
        return now_npt().replace(hour=MARKET_OPEN[0], minute=MARKET_OPEN[1], second=0, microsecond=0)
    d += timedelta(days=1)
    while not is_trading_day(d):
        d += timedelta(days=1)
    return datetime(d.year, d.month, d.day, MARKET_OPEN[0], MARKET_OPEN[1], tzinfo=NPT)

def _fmt_wait(target: datetime) -> str:
    secs = max(0, int((target - now_npt()).total_seconds()))
    h, r = divmod(secs, 3600); m, s = divmod(r, 60)
    return f"{h}h {m:02d}m {s:02d}s" if h else f"{m:02d}m {s:02d}s"

def wait_until(target: datetime, label: str = ""):
    """Block until target datetime, logging progress every 10 minutes."""
    while True:
        remaining = (target - now_npt()).total_seconds()
        if remaining <= 0:
            return
        if label:
            log.info(f"Waiting for {label} in {_fmt_wait(target)} …")
        time.sleep(min(remaining, 600))


# ── Core runners ───────────────────────────────────────────────────────────────

def run_fetch(symbols: list[str]):
    """
    Stage 1: Run the intraday extractor loop.
    Blocks until market closes (15:00 NPT) or is interrupted.
    DATA IS FETCHED AUTOMATICALLY between 11:00–15:00 NPT.
    """
    log.info("=" * 60)
    log.info("AUTO FETCH  (11:00–15:00 NPT) — running in background")
    log.info("=" * 60)
    from pipeline import stage_fetch
    stage_fetch(symbols)
    log.info("Fetch loop ended (market closed or interrupted).")


def run_post_market(
    email_recipients: list[str] | None = None,
    email_cc: list[str] | None = None,
):
    """
    Stages 2–4 (auto-triggered at 15:15 NPT):
    transformer → report → notification → email
    """
    log.info("=" * 60)
    log.info(f"AUTO REPORT  ({_REPORT_HOUR:02d}:{_REPORT_MINUTE:02d} NPT)")
    log.info("Transformer → Charts → PDF → Notify → Email")
    log.info("=" * 60)
    from pipeline import generate_report_now
    path = generate_report_now(email_recipients=email_recipients, email_cc=email_cc)
    if path:
        log.info(f"Report complete: {path}")
    else:
        log.warning("Report generation failed — check logs.")


def run_trading_day(
    symbols: list[str],
    email_recipients: list[str] | None = None,
    email_cc: list[str] | None = None,
):
    """
    Full day cycle:
      1. Wait for 11:00 NPT, then start fetch (auto, runs until 15:00 NPT)
      2. Wait until 15:15 NPT, then run report pipeline automatically
    """
    log.info("=" * 60)
    log.info(f"TRADING DAY  {now_npt().strftime('%a %d %b %Y')}")
    log.info("=" * 60)

    # Auto-fetch: runs 11:00–15:00 NPT (blocking)
    run_fetch(symbols)

    # Wait for report time (15:15 NPT)
    n      = now_npt()
    target = n.replace(hour=_REPORT_HOUR, minute=_REPORT_MINUTE, second=0, microsecond=0)
    if n < target:
        log.info(f"Market closed. Auto-report will fire at {_REPORT_HOUR:02d}:{_REPORT_MINUTE:02d} NPT …")
        wait_until(target, f"{_REPORT_HOUR:02d}:{_REPORT_MINUTE:02d} NPT")

    # Auto report + notify + email
    run_post_market(email_recipients=email_recipients, email_cc=email_cc)


# ── Scheduler loop ─────────────────────────────────────────────────────────────

def scheduler_loop(
    symbols: list[str],
    email_recipients: list[str] | None = None,
    email_cc: list[str] | None = None,
):
    log.info("NEPSE ETL Scheduler started. Auto-fetching Sun–Thu 11:00–15:00 NPT.")
    log.info(f"Auto-report fires at {_REPORT_HOUR:02d}:{_REPORT_MINUTE:02d} NPT after market close.")
    while True:
        if not is_trading_day():
            log.info(f"Today ({now_npt().strftime('%A')}) is not a trading day.")
            wait_until(next_open_dt(), "next market open")
            continue
        if market_status() == "before":
            wait_until(next_open_dt(), "market open (11:00 NPT)")
        run_trading_day(symbols, email_recipients=email_recipients, email_cc=email_cc)
        log.info("Waiting for next trading day …")
        wait_until(next_open_dt(), "next market open")


# ── CLI ────────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(
        description="NEPSE ETL Scheduler",
        epilog="""
Modes:
  (default)     Loop forever: auto-fetch 11:00-15:00, auto-report at 15:15
  --once        Run today's full cycle then exit
  --report-now  Immediately run transformer + report + notify + email from raw.csv
  --fetch-only  Start fetch loop only (no report)
        """,
    )
    parser.add_argument("--symbols",    nargs="+", default=DEFAULT_SYMBOLS)
    parser.add_argument("--email",      nargs="*", default=None, metavar="ADDR")
    parser.add_argument("--cc",         nargs="*", default=None, metavar="ADDR")
    parser.add_argument("--once",       action="store_true", help="Run today then exit")
    parser.add_argument("--report-now", action="store_true", help="Generate report now from raw.csv")
    parser.add_argument("--fetch-only", action="store_true", help="Run fetch loop only")
    args = parser.parse_args()

    recip = args.email
    cc    = args.cc

    if args.report_now:
        if market_status() == "open":
            log.info("Market is still open — waiting for close before generating report …")
            n = now_npt()
            target = n.replace(hour=_REPORT_HOUR, minute=_REPORT_MINUTE, second=0, microsecond=0)
            wait_until(target, f"{_REPORT_HOUR:02d}:{_REPORT_MINUTE:02d} NPT")
        run_post_market(email_recipients=recip, email_cc=cc)

    elif args.fetch_only:
        run_fetch(args.symbols)

    elif args.once:
        if not is_trading_day():
            log.warning(f"Today ({now_npt().strftime('%A')}) is not a trading day. Exiting.")
            return
        if market_status() == "before":
            wait_until(next_open_dt(), "market open")
        run_trading_day(args.symbols, email_recipients=recip, email_cc=cc)

    else:
        scheduler_loop(args.symbols, email_recipients=recip, email_cc=cc)


if __name__ == "__main__":
    main()
