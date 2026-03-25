"""
pipeline.py  ─  Master Orchestrator
Runs: Extract → Transform → Load (Visualise) → Report
Can be run directly or imported and called programmatically.

Usage:
    python pipeline.py                        # full ETL + report (demo mode if no data)
    python pipeline.py --transform-only       # transform + visualise existing raw.csv
    python pipeline.py --report-only          # generate report from existing cleaned.csv
    python pipeline.py --symbols NABIL SCB    # override watchlist
"""
import sys
import argparse
from pathlib import Path
from datetime import datetime

from config import RAW_CSV, CLEANED_CSV, REPORTS_DIR, DEFAULT_SYMBOLS
from logger import get_logger

log = get_logger("pipeline")


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
    """
    Generate synthetic OHLCV data so the pipeline can be fully demonstrated
    without a live market session. Creates data/raw.csv.
    """
    import pandas as pd
    import numpy as np
    import csv
    from config import RAW_CSV
    from datetime import datetime, timedelta
    from zoneinfo import ZoneInfo

    if symbols is None:
        symbols = DEFAULT_SYMBOLS

    NPT = ZoneInfo("Asia/Kathmandu")
    base_prices = {
        "NEPSE": 2100, "NABIL": 1050, "ADBL": 520,
        "NTC":   850,  "NICA":  680,  "UPPER": 340,
        "SCB":   780,  "EBL":   910,  "SBL":   430,
        "GBIME": 360,
    }

    rows = []
    # Simulate 8 polls from 11:00 to 14:00, every 3-5 min
    base_time = datetime(2026, 3, 25, 11, 0, 0, tzinfo=NPT)
    for p in range(10):
        fetch_time = base_time + timedelta(minutes=p * 20 + np.random.randint(0, 5))
        for sym in symbols:
            bp = base_prices.get(sym, 500)
            rng = bp * 0.02
            open_p = round(bp + np.random.uniform(-rng, rng), 2)
            close_p = round(open_p + np.random.uniform(-rng * 1.5, rng * 1.5), 2)
            high_p  = round(max(open_p, close_p) + abs(np.random.normal(0, rng * 0.5)), 2)
            low_p   = round(min(open_p, close_p) - abs(np.random.normal(0, rng * 0.5)), 2)
            prev_c  = round(bp + np.random.uniform(-rng * 0.5, rng * 0.5), 2)
            pct     = round((close_p - prev_c) / prev_c * 100, 2)
            vol     = int(abs(np.random.normal(50000, 20000)))
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
            })
            # Drift price for next poll
            base_prices[sym] = close_p

    FIELDNAMES = [
        "fetched_at", "symbol", "date", "open", "high",
        "low", "close", "volume", "prev_close", "pct_change",
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
        # Full live pipeline
        run_pipeline(syms, extract=True, transform=True, load=True, report=True)


if __name__ == "__main__":
    main()
