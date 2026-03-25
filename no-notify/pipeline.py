"""
pipeline.py  ─  Master Orchestrator
Runs: Extract → Transform → Load (Visualise) → Report

Usage:
    python pipeline.py                        # full ETL + report
    python pipeline.py --transform-only       # transform + visualise existing raw.csv
    python pipeline.py --report-only          # generate report from existing cleaned.csv
    python pipeline.py --symbols NABIL SCB    # override watchlist
    python pipeline.py --demo                 # synthetic data, full pipeline
"""
import sys
import argparse
from pathlib import Path
from datetime import datetime

from config import RAW_CSV, CLEANED_CSV, REPORTS_DIR, DEFAULT_SYMBOLS, NPT
from logger import get_logger

log = get_logger("pipeline")

_LAST_RESET_FILE = RAW_CSV.parent / ".last_reset_date"


def _today_str() -> str:
    return datetime.now(NPT).strftime("%Y-%m-%d")


def maybe_reset_csvs():
    """
    If today is a new calendar day, archive stale CSV rows instead of deleting them.
    Delegates to extractor._archive_stale_rows() which handles safe rotation.
    """
    today = _today_str()
    last  = ""
    if _LAST_RESET_FILE.exists():
        last = _LAST_RESET_FILE.read_text().strip()

    if last == today:
        return

    log.info(f"New trading day detected ({today}). Rotating stale CSV rows …")
    try:
        from extractor import _archive_stale_rows, _ensure_schema
        _archive_stale_rows()
        _ensure_schema()
    except Exception as e:
        log.error(f"CSV rotation failed: {e}")

    _LAST_RESET_FILE.write_text(today)
    log.info("CSV rotation complete.")


def stage_extract(symbols: list[str]):
    log.info("=" * 60)
    log.info("STAGE 1: EXTRACT")
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
    log.info("STAGE 3 & 4: LOAD + VISUALISE")
    log.info("=" * 60)
    from loader import generate_all_charts
    return generate_all_charts(df)


def stage_report(charts: dict, df: "pd.DataFrame") -> Path:
    log.info("=" * 60)
    log.info("STAGE 5: REPORT")
    log.info("=" * 60)
    from report_generator import generate_report
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    return generate_report(charts, df, out_name=f"NEPSE_Report_{ts}.pdf")


def run_pipeline(symbols: list[str] | None = None,
                 extract: bool = True,
                 transform: bool = True,
                 load: bool = True,
                 report: bool = True) -> Path | None:

    if symbols is None:
        symbols = DEFAULT_SYMBOLS

    log.info("NEPSE ETL Pipeline starting …")
    log.info(f"Symbols: {symbols}")

    maybe_reset_csvs()

    if extract:
        stage_extract(symbols)

    df = None
    if transform:
        if not RAW_CSV.exists():
            log.error("raw.csv does not exist — run extraction first")
            return None
        df = stage_transform()

    charts = {}
    if load:
        if df is None:
            if not CLEANED_CSV.exists():
                log.error("cleaned.csv does not exist — run transform first")
                return None
            import pandas as pd
            df = pd.read_csv(CLEANED_CSV, parse_dates=["fetched_at", "date"])
        charts = stage_load(df)

    report_path = None
    if report:
        if df is None:
            if not CLEANED_CSV.exists():
                log.error("cleaned.csv does not exist — cannot generate report")
                return None
            import pandas as pd
            df = pd.read_csv(CLEANED_CSV, parse_dates=["fetched_at", "date"])
        report_path = stage_report(charts, df)
        log.info(f"Report saved: {report_path}")

    log.info("Pipeline complete.")
    return report_path


def create_demo_data(symbols: list[str] | None = None):
    """Generate synthetic OHLCV data including MA columns."""
    import pandas as pd
    import numpy as np
    import csv
    from config import RAW_CSV
    from datetime import datetime, timedelta

    if symbols is None:
        symbols = DEFAULT_SYMBOLS

    base_prices = {
        "NEPSE": 2100, "NABIL": 1050, "ADBL": 520,
        "NTC":   850,  "NICA":  680,  "UPPER": 340,
        "SCB":   780,  "EBL":   910,  "SBL":   430,
        "GBIME": 360,
    }

    rows      = []
    close_buf = {s: [] for s in symbols}

    base_time = datetime(2026, 3, 25, 11, 0, 0, tzinfo=NPT)
    for p in range(10):
        fetch_time = base_time + timedelta(minutes=p * 20 + np.random.randint(0, 5))
        for sym in symbols:
            bp     = base_prices.get(sym, 500)
            rng    = bp * 0.02
            open_p = round(bp + np.random.uniform(-rng, rng), 2)
            close_p= round(open_p + np.random.uniform(-rng * 1.5, rng * 1.5), 2)
            high_p = round(max(open_p, close_p) + abs(np.random.normal(0, rng * 0.5)), 2)
            low_p  = round(min(open_p, close_p) - abs(np.random.normal(0, rng * 0.5)), 2)
            prev_c = round(bp + np.random.uniform(-rng * 0.5, rng * 0.5), 2)
            pct    = round((close_p - prev_c) / prev_c * 100, 2)
            vol    = int(abs(np.random.normal(50000, 20000)))

            close_buf[sym].append(close_p)
            buf = close_buf[sym]

            def ma(n): return round(sum(buf[-n:]) / min(n, len(buf)), 2)

            rows.append({
                "fetched_at": fetch_time.strftime("%Y-%m-%d %H:%M:%S"),
                "symbol":     sym,
                "date":       fetch_time.strftime("%Y-%m-%d"),
                "open":       open_p,
                "high":       high_p,
                "low":        low_p,
                "close":      close_p,
                "volume":     vol,
                "prev_close": prev_c,
                "pct_change": pct,
                "ma5":        ma(5)  if len(buf) >= 2 else "",
                "ma10":       ma(10) if len(buf) >= 2 else "",
                "ma20":       ma(20) if len(buf) >= 2 else "",
            })
            base_prices[sym] = close_p

    FIELDNAMES = [
        "fetched_at", "symbol", "date", "open", "high",
        "low", "close", "volume", "prev_close", "pct_change",
        "ma5", "ma10", "ma20",
    ]
    RAW_CSV.parent.mkdir(exist_ok=True)
    with open(RAW_CSV, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=FIELDNAMES)
        w.writeheader()
        w.writerows(rows)

    log.info(f"Demo data written: {len(rows)} rows to {RAW_CSV}")


def main():
    parser = argparse.ArgumentParser(description="NEPSE ETL Pipeline")
    parser.add_argument("--symbols",        nargs="+",       default=None)
    parser.add_argument("--transform-only", action="store_true")
    parser.add_argument("--report-only",    action="store_true")
    parser.add_argument("--demo",           action="store_true",
                        help="Generate synthetic data and run full pipeline (no live fetch)")
    args = parser.parse_args()

    syms = args.symbols or DEFAULT_SYMBOLS

    if args.demo:
        log.info("DEMO MODE — generating synthetic data …")
        create_demo_data(syms)
        run_pipeline(syms, extract=False, transform=True, load=True, report=True)

    elif args.transform_only:
        run_pipeline(syms, extract=False, transform=True, load=True, report=True)

    elif args.report_only:
        run_pipeline(syms, extract=False, transform=False, load=True, report=True)

    else:
        run_pipeline(syms, extract=True, transform=True, load=True, report=True)


if __name__ == "__main__":
    main()
