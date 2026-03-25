"""
scheduler.py  ─  Automated daily scheduler

Behaviour:
  • Waits for each trading morning (Sun–Thu, 11:00 NPT)
  • Runs the intraday fetch loop until market closes (15:00 NPT)
  • Generates report + sends email REPORT_DELAY_MINUTES after close
  • Loops to the next trading day forever (or use --once for a single run)

Usage:
  python scheduler.py                          # run forever (daily loop)
  python scheduler.py --once                   # run today then exit
  python scheduler.py --report-now             # report from raw.csv now
  python scheduler.py --email a@x.com b@x.com # override recipients

Cron alternatives (from project root):
  # Start fetch at 10:50 AM every trading day
  50 10 * * 0-4  cd /path/to/project && python scheduler.py --once >> logs/cron.log 2>&1
  # Safety fallback — report at 15:10 NPT
  10 15 * * 0-4  cd /path/to/project && python scheduler.py --report-now >> logs/cron.log 2>&1
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


# ─── Time helpers ──────────────────────────────────────────────────────────────

def now_npt() -> datetime:
    return datetime.now(NPT)

def is_trading_day() -> bool:
    d = now_npt().date()
    return d.isoweekday() not in (5, 6) and d.strftime("%Y-%m-%d") not in NEPALI_HOLIDAYS

def market_status() -> str:
    t = (now_npt().hour, now_npt().minute)
    if t < MARKET_OPEN:   return "before"
    if t >= MARKET_CLOSE: return "after"
    return "open"

def next_open_dt() -> datetime:
    """Returns the datetime of the next (or current) market open."""
    d = now_npt().date()
    # If today is a trading day and market hasn't opened yet, use today
    if is_trading_day() and (now_npt().hour, now_npt().minute) < MARKET_OPEN:
        return now_npt().replace(hour=MARKET_OPEN[0], minute=MARKET_OPEN[1],
                                 second=0, microsecond=0)
    # Otherwise find the next trading day
    d += timedelta(days=1)
    while d.isoweekday() in (5, 6) or d.strftime("%Y-%m-%d") in NEPALI_HOLIDAYS:
        d += timedelta(days=1)
    return datetime(d.year, d.month, d.day, MARKET_OPEN[0], MARKET_OPEN[1], tzinfo=NPT)

def _countdown(target: datetime) -> str:
    """Format seconds remaining as '2h 05m 30s'."""
    secs = int((target - now_npt()).total_seconds())
    if secs <= 0:
        return "now"
    h, r = divmod(secs, 3600)
    m, s = divmod(r, 60)
    return f"{h}h {m:02d}m {s:02d}s" if h else f"{m:02d}m {s:02d}s"

def wait_for_open():
    """Block until the next market open, logging progress every 10 minutes."""
    while True:
        nxt   = next_open_dt()
        delta = (nxt - now_npt()).total_seconds()
        if delta <= 0:
            return
        log.info(f"Market opens {nxt.strftime('%a %d %b  11:00 AM NPT')} (in {_countdown(nxt)})")
        time.sleep(min(delta, 600))


# ─── Report timing ─────────────────────────────────────────────────────────────

def wait_for_report_time():
    """
    Block until MARKET_CLOSE + REPORT_DELAY_MINUTES.
    Returns immediately if that time has already passed.
    """
    n         = now_npt()
    total_min = MARKET_CLOSE[1] + REPORT_DELAY_MINUTES
    target    = n.replace(
        hour        = MARKET_CLOSE[0] + total_min // 60,
        minute      = total_min % 60,
        second      = 0,
        microsecond = 0,
    )
    if n >= target:
        log.info("Already past report time — proceeding immediately.")
        return

    wait_s = int((target - n).total_seconds())
    log.info(
        f"Report will generate at {target.strftime('%H:%M')} NPT "
        f"(in {wait_s // 60}m {wait_s % 60}s) …"
    )
    while (remaining := int((target - now_npt()).total_seconds())) > 0:
        if remaining % 300 == 0:
            log.info(f"  Waiting … {remaining // 60}m {remaining % 60}s until report.")
        time.sleep(min(30, remaining))
    log.info("Wait complete. Triggering report …")


# ─── Core day runner ───────────────────────────────────────────────────────────

def run_trading_day(
    symbols: list[str],
    email_recipients: list[str] | None = None,
    email_cc: list[str] | None = None,
):
    """
    Full cycle for one trading day:
      1. Run the fetch loop (blocks until 15:00 NPT)
      2. Wait a few minutes for final data
      3. Generate + email the report
    """
    from pipeline import stage_fetch, generate_report_now

    log.info("=" * 60)
    log.info(f"TRADING DAY  {now_npt().strftime('%a %d %b %Y')}")
    log.info("=" * 60)

    stage_fetch(symbols)
    wait_for_report_time()

    report_path = generate_report_now(
        email_recipients=email_recipients,
        email_cc=email_cc,
    )
    if report_path:
        log.info(f"Day complete. Report: {report_path}")
    else:
        log.warning("Day complete but report generation failed.")


def report_now(
    email_recipients: list[str] | None = None,
    email_cc: list[str] | None = None,
):
    """Generate a report right now (waits for market close first if open)."""
    from pipeline import generate_report_now

    if market_status() == "open":
        log.info("Market is still open. Waiting for close first …")
        wait_for_report_time()
    else:
        log.info("Market is closed. Generating report from current raw.csv …")

    generate_report_now(email_recipients=email_recipients, email_cc=email_cc)


# ─── Infinite scheduler ────────────────────────────────────────────────────────

def scheduler_loop(
    symbols: list[str],
    email_recipients: list[str] | None = None,
    email_cc: list[str] | None = None,
):
    log.info("NEPSE ETL Scheduler started. Running daily, Sun–Thu.")
    while True:
        if not is_trading_day():
            log.info(f"Today ({now_npt().strftime('%A')}) is not a trading day.")
            wait_for_open()
            continue

        if market_status() == "before":
            wait_for_open()

        run_trading_day(symbols, email_recipients=email_recipients, email_cc=email_cc)
        log.info("Waiting for next trading day …")
        wait_for_open()


# ─── CLI ───────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="NEPSE ETL Scheduler")
    parser.add_argument("--symbols",    nargs="+", default=DEFAULT_SYMBOLS)
    parser.add_argument("--email",      nargs="*", default=None, metavar="ADDR")
    parser.add_argument("--cc",         nargs="*", default=None, metavar="ADDR")
    parser.add_argument("--once",       action="store_true", help="Run today then exit")
    parser.add_argument("--report-now", action="store_true", help="Report from raw.csv now")
    args = parser.parse_args()

    if args.report_now:
        report_now(email_recipients=args.email, email_cc=args.cc)
    elif args.once:
        run_trading_day(args.symbols, email_recipients=args.email, email_cc=args.cc)
    else:
        scheduler_loop(args.symbols, email_recipients=args.email, email_cc=args.cc)


if __name__ == "__main__":
    main()
