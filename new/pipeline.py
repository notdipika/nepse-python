"""
pipeline.py  ─  Master Orchestrator

raw.csv lifetime
────────────────
  raw.csv accumulates data throughout the current trading session.
  It is ONLY cleared (and archived) at the very start of the NEXT
  trading day's fetch run.  This means:

    • You can call --report-only at any time — even hours after market
      close — and get a report from today's full session data.
    • Restarting the extractor mid-session does NOT erase data.
    • The next trading morning's first --fetch-only (or full run)
      archives the old session and starts fresh.

Usage
─────
  python pipeline.py                           # full fetch + report + email
  python pipeline.py --fetch-only              # run extractor only (no report)
  python pipeline.py --report-only             # report from current raw.csv NOW
  python pipeline.py --demo                    # synthetic data → full pipeline
  python pipeline.py --symbols NABIL SCB       # override watchlist
  python pipeline.py --email a@x.com b@x.com  # override email recipients
  python pipeline.py --cc mgr@x.com           # add CC recipients
"""
import sys
import argparse
from pathlib import Path
from datetime import datetime

from config import RAW_CSV, CLEANED_CSV, DEFAULT_SYMBOLS, NPT
from logger import get_logger

log = get_logger("pipeline")


# ─── Individual stages ────────────────────────────────────────────────────────

def stage_fetch(symbols: list[str]):
    """Run the intraday polling loop (blocks until market closes)."""
    log.info("=" * 60)
    log.info("STAGE 1: FETCH  (runs until 15:00 NPT or Ctrl+C)")
    log.info("=" * 60)
    from extractor import run_extractor
    run_extractor(symbols)


def stage_transform() -> "pd.DataFrame":
    log.info("=" * 60)
    log.info("STAGE 2: TRANSFORM")
    log.info("=" * 60)
    from transformer import transform
    return transform()


def stage_load(df: "pd.DataFrame") -> dict:
    log.info("=" * 60)
    log.info("STAGE 3: VISUALISE")
    log.info("=" * 60)
    from report import generate_all_charts
    return generate_all_charts(df)


def stage_report(
    charts: dict,
    df: "pd.DataFrame",
    email_recipients: list[str] | None = None,
    email_cc: list[str] | None = None,
) -> Path:
    log.info("=" * 60)
    log.info("STAGE 4: REPORT + NOTIFY + EMAIL")
    log.info("=" * 60)
    from report import generate_report
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    return generate_report(
        charts, df,
        out_name=f"NEPSE_Report_{ts}.pdf",
        email_recipients=email_recipients,
        email_cc=email_cc,
    )


# ─── High-level helpers ───────────────────────────────────────────────────────

def _load_df_from_csv():
    """Load cleaned.csv (or transform raw.csv on the fly) into a DataFrame."""
    import pandas as pd

    if not RAW_CSV.exists() or RAW_CSV.stat().st_size == 0:
        log.error("raw.csv does not exist or is empty — nothing to report.")
        return None

    try:
        df = stage_transform()
    except Exception as e:
        log.error(f"Transform failed: {e}")
        # Fall back to last cleaned.csv if available
        if CLEANED_CSV.exists():
            log.warning("Falling back to existing cleaned.csv …")
            df = pd.read_csv(CLEANED_CSV, parse_dates=["fetched_at", "date"])
        else:
            return None
    return df


def generate_report_now(
    email_recipients: list[str] | None = None,
    email_cc: list[str] | None = None,
) -> Path | None:
    """
    Generate a report from whatever data is currently in raw.csv.
    Does NOT start any fetch or wait for market hours.
    Safe to call at any time — during the session, after close, next morning.
    """
    log.info("Generating report from current raw.csv data …")

    df = _load_df_from_csv()
    if df is None:
        return None

    charts      = stage_load(df)
    report_path = stage_report(charts, df,
                               email_recipients=email_recipients,
                               email_cc=email_cc)
    log.info(f"Report ready: {report_path}")
    return report_path


# ─── Full pipeline ────────────────────────────────────────────────────────────

def run_pipeline(
    symbols: list[str] | None = None,
    fetch:   bool = True,
    report:  bool = True,
    email_recipients: list[str] | None = None,
    email_cc: list[str] | None = None,
) -> Path | None:
    """
    fetch=True  → run the intraday polling loop first, THEN generate report.
    fetch=False → generate report from whatever is already in raw.csv.
    """
    if symbols is None:
        symbols = DEFAULT_SYMBOLS

    log.info("NEPSE ETL Pipeline starting …")
    log.info(f"Symbols : {symbols}")
    log.info(f"Fetch   : {fetch}")
    log.info(f"Report  : {report}")

    if fetch:
        stage_fetch(symbols)
        # After fetch loop exits (market closed), fall through to report

    if report:
        return generate_report_now(email_recipients=email_recipients,
                                   email_cc=email_cc)

    log.info("Pipeline complete (fetch only — no report generated).")
    return None


# ─── Demo data generator ──────────────────────────────────────────────────────

def create_demo_data(symbols: list[str] | None = None):
    """Generate synthetic OHLCV data for testing without live API access."""
    import csv as csv_mod
    import numpy as np
    from datetime import timedelta

    if symbols is None:
        symbols = DEFAULT_SYMBOLS

    base_prices = {
        "NEPSE": 2100, "NABIL": 1050, "ADBL": 520,
        "NTC":    850, "NICA":   680, "UPPER": 340,
        "SCB":    780, "EBL":    910, "SBL":   430,
        "GBIME":  360,
    }

    FIELDNAMES = [
        "fetched_at", "symbol", "date", "open", "high", "low", "close",
        "volume", "prev_close", "pct_change", "ma5", "ma10", "ma20",
    ]

    rows      = []
    close_buf = {s: [] for s in symbols}
    base_time = datetime(2026, 3, 25, 11, 0, 0, tzinfo=NPT)

    for p in range(10):
        fetch_time = base_time + timedelta(minutes=p * 20 + np.random.randint(0, 5))
        for sym in symbols:
            bp      = base_prices.get(sym, 500)
            rng     = bp * 0.02
            open_p  = round(bp + np.random.uniform(-rng, rng), 2)
            close_p = round(open_p + np.random.uniform(-rng * 1.5, rng * 1.5), 2)
            high_p  = round(max(open_p, close_p) + abs(np.random.normal(0, rng * 0.5)), 2)
            low_p   = round(min(open_p, close_p) - abs(np.random.normal(0, rng * 0.5)), 2)
            prev_c  = round(bp + np.random.uniform(-rng * 0.5, rng * 0.5), 2)
            pct     = round((close_p - prev_c) / prev_c * 100, 2)
            vol     = int(abs(np.random.normal(50000, 20000)))

            close_buf[sym].append(close_p)
            buf = close_buf[sym]
            def ma(n): return round(sum(buf[-n:]) / min(n, len(buf)), 2)

            rows.append({
                "fetched_at": fetch_time.strftime("%Y-%m-%d %H:%M:%S"),
                "symbol":     sym,
                "date":       fetch_time.strftime("%Y-%m-%d"),
                "open":  open_p, "high": high_p, "low": low_p, "close": close_p,
                "volume": vol, "prev_close": prev_c, "pct_change": pct,
                "ma5":  ma(5)  if len(buf) >= 2 else "",
                "ma10": ma(10) if len(buf) >= 2 else "",
                "ma20": ma(20) if len(buf) >= 2 else "",
            })
            base_prices[sym] = close_p

    RAW_CSV.parent.mkdir(exist_ok=True)
    with open(RAW_CSV, "w", newline="") as f:
        w = csv_mod.DictWriter(f, fieldnames=FIELDNAMES)
        w.writeheader()
        w.writerows(rows)

    # Mark the stamp so the extractor treats this as a fresh session
    stamp = RAW_CSV.parent / ".raw_session_date"
    stamp.write_text(datetime.now(NPT).strftime("%Y-%m-%d"))

    log.info(f"Demo data: {len(rows)} rows → {RAW_CSV}")


# ─── CLI ──────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(
        description="NEPSE ETL Pipeline",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python pipeline.py                       # fetch all day, then report
  python pipeline.py --fetch-only          # fetch only, no report
  python pipeline.py --report-only         # report from current raw.csv
  python pipeline.py --demo                # synthetic data + report
  python pipeline.py --report-only --email you@gmail.com
""",
    )
    parser.add_argument("--symbols",      nargs="+",  default=None,
                        help="Symbols to track (default: config.DEFAULT_SYMBOLS)")
    parser.add_argument("--email",        nargs="*",  default=None, metavar="ADDR",
                        help="Override email To recipients")
    parser.add_argument("--cc",           nargs="*",  default=None, metavar="ADDR",
                        help="Override email CC recipients")
    parser.add_argument("--fetch-only",   action="store_true",
                        help="Run intraday fetch loop only — no report")
    parser.add_argument("--report-only",  action="store_true",
                        help="Generate report from current raw.csv — no fetch")
    parser.add_argument("--demo",         action="store_true",
                        help="Generate synthetic data then produce a report")
    args = parser.parse_args()

    syms   = args.symbols or DEFAULT_SYMBOLS
    recip  = args.email
    cc     = args.cc

    if args.demo:
        log.info("DEMO MODE — generating synthetic data …")
        create_demo_data(syms)
        generate_report_now(email_recipients=recip, email_cc=cc)

    elif args.fetch_only:
        run_pipeline(syms, fetch=True, report=False)

    elif args.report_only:
        generate_report_now(email_recipients=recip, email_cc=cc)

    else:
        # Default: fetch all day, then report
        run_pipeline(syms, fetch=True, report=True,
                     email_recipients=recip, email_cc=cc)


if __name__ == "__main__":
    main()
