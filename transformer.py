"""
transformer.py  ─  Stage 2: Transform & Enrich
Reads data/raw.csv → cleans → enriches → writes data/cleaned.csv
"""
import pandas as pd
import numpy as np
from pathlib import Path

from config import RAW_CSV, CLEANED_CSV
from logger import get_logger

log = get_logger("transformer")


def transform(raw_path: Path = RAW_CSV, out_path: Path = CLEANED_CSV) -> pd.DataFrame:
    """Read raw.csv, clean and enrich it, write cleaned.csv."""
    if not raw_path.exists():
        raise FileNotFoundError(raw_path)

    df = pd.read_csv(raw_path)
    if df.empty:
        raise ValueError("raw.csv is empty")

    log.info(f"Loaded {len(df)} rows, {df['symbol'].nunique()} symbol(s)")

    # ── 1. Coerce types ────────────────────────────────────────────────────────
    df["fetched_at"] = pd.to_datetime(df["fetched_at"], errors="coerce")
    df["date"]       = pd.to_datetime(df["date"],       errors="coerce")
    for col in ("open","high","low","close","prev_close","pct_change","ma5","ma10","ma20"):
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors="coerce")
    df["volume"] = pd.to_numeric(df.get("volume", 0), errors="coerce").fillna(0).astype(int)

    # ── 2. Deduplicate ─────────────────────────────────────────────────────────
    before = len(df)
    df = df.drop_duplicates(subset=["symbol","fetched_at"])
    log.info(f"Removed {before - len(df)} duplicate rows")

    # ── 3. Drop missing OHLC / invalid rows ───────────────────────────────────
    df = df.dropna(subset=["open","high","low","close"])
    df = df[
        (df["high"]  >= df["low"])   & (df["high"]  >= df["open"])  &
        (df["high"]  >= df["close"]) & (df["low"]   <= df["open"])  &
        (df["low"]   <= df["close"]) & (df["close"] >  0)           &
        (df["volume"] >= 0)
    ]

    # ── 4. Sort + derive prev_close ───────────────────────────────────────────
    df = df.sort_values(["symbol","fetched_at"]).reset_index(drop=True)
    derived = df.groupby("symbol")["close"].shift(1)
    df["prev_close_derived"] = derived.where(derived.notna(), df["prev_close"])

    # ── 5. Feature engineering ─────────────────────────────────────────────────
    df["pct_change_calc"] = np.where(
        df["prev_close_derived"] > 0,
        ((df["close"] - df["prev_close_derived"]) / df["prev_close_derived"] * 100).round(2),
        df["pct_change"],
    )
    df["range"]        = (df["high"] - df["low"]).round(2)
    df["range_pct"]    = (df["range"] / df["low"] * 100).round(2)
    df["body"]         = (df["close"] - df["open"]).round(2)
    df["upper_shadow"] = (df["high"] - df[["open","close"]].max(axis=1)).round(2)
    df["lower_shadow"] = (df[["open","close"]].min(axis=1) - df["low"]).round(2)
    df["direction"]    = np.where(df["close"] >= df["open"], "UP", "DOWN")
    df["close_scaled"] = (
        df.groupby("symbol")["close"]
          .transform(lambda x: ((x - x.min()) / (x.max() - x.min() + 1e-9)).round(4))
    )
    df["cum_return_pct"] = df.groupby("symbol")["pct_change_calc"].transform("cumsum").round(2)
    df["fetch_hour"]     = df["fetched_at"].dt.hour

    for n, col in [(5,"ma5"),(10,"ma10"),(20,"ma20")]:
        computed = df.groupby("symbol")["close"].transform(
            lambda x: x.rolling(n, min_periods=1).mean().round(2))
        df[col] = df[col].fillna(computed) if col in df.columns else computed

    df["pct_change_calc"] = df["pct_change_calc"].fillna(0.0)
    df["cum_return_pct"]  = df["cum_return_pct"].fillna(0.0)

    # ── 6. Save ────────────────────────────────────────────────────────────────
    df.to_csv(out_path, index=False)
    log.info(f"Saved {len(df)} rows → {out_path}")
    return df


if __name__ == "__main__":
    df = transform()
    print(df.head(20).to_string())
    print(f"\nShape: {df.shape}  |  Symbols: {list(df['symbol'].unique())}")
