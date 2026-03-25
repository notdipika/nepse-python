"""
transformer.py  ─  Stage 2: Transform & Enrich
Reads data/raw.csv → cleans → enriches → saves data/cleaned.csv

v2: Passes through ma5/ma10/ma20 from extractor; also computes
    EMA-style moving averages from the cleaned close series.
"""
import pandas as pd
import numpy as np
from pathlib import Path
from config import RAW_CSV, CLEANED_CSV
from logger import get_logger

log = get_logger("transformer")


class DataCleaningPipeline:
    """Chain-of-responsibility style transform pipeline."""

    def __init__(self, df: pd.DataFrame):
        self.df = df.copy()
        self._steps: list[tuple[str, callable]] = []

    @staticmethod
    def _validate_step(df: pd.DataFrame, step_name: str) -> None:
        if df.empty:
            raise ValueError(f"Step '{step_name}' produced empty DataFrame")
        log.debug(f"[validate] {step_name} → {len(df)} rows OK")

    def run(self) -> pd.DataFrame:
        for name, fn in self._steps:
            log.info(f"Running transform step: {name}")
            self.df = fn(self.df)
            self._validate_step(self.df, name)
        return self.df


def transform(raw_path: Path = RAW_CSV,
              out_path: Path = CLEANED_CSV) -> pd.DataFrame:

    if not raw_path.exists():
        log.error(f"raw.csv not found at {raw_path}")
        raise FileNotFoundError(raw_path)

    df = pd.read_csv(raw_path)
    log.info(f"Loaded raw.csv: {len(df)} rows, {df['symbol'].nunique()} symbols")

    pipeline = DataCleaningPipeline(df)

    # ─── Step 1: Type coercion ────────────────────────────────────────────────
    def coerce_types(df):
        df["fetched_at"] = pd.to_datetime(df["fetched_at"], errors="coerce")
        df["date"]       = pd.to_datetime(df["date"],       errors="coerce")
        for col in ("open", "high", "low", "close", "prev_close", "pct_change",
                    "ma5", "ma10", "ma20"):
            if col in df.columns:
                df[col] = pd.to_numeric(df[col], errors="coerce")
        df["volume"] = pd.to_numeric(df["volume"], errors="coerce").fillna(0).astype(int)
        return df
    pipeline._steps.append(("coerce_types", coerce_types))

    # ─── Step 2: Drop duplicates ──────────────────────────────────────────────
    def drop_duplicates(df):
        before = len(df)
        df = df.drop_duplicates(subset=["symbol", "fetched_at"])
        log.info(f"drop_duplicates: removed {before - len(df)} rows")
        return df
    pipeline._steps.append(("drop_duplicates", drop_duplicates))

    # ─── Step 3: Drop rows with null OHLCV ───────────────────────────────────
    def drop_null_ohlcv(df):
        before = len(df)
        df = df.dropna(subset=["open", "high", "low", "close"])
        log.info(f"drop_null_ohlcv: removed {before - len(df)} rows")
        return df
    pipeline._steps.append(("drop_null_ohlcv", drop_null_ohlcv))

    # ─── Step 4: OHLCV sanity checks ─────────────────────────────────────────
    def sanity_checks(df):
        before = len(df)
        df = df[df["high"] >= df["low"]]
        df = df[df["high"] >= df["open"]]
        df = df[df["high"] >= df["close"]]
        df = df[df["low"]  <= df["open"]]
        df = df[df["low"]  <= df["close"]]
        df = df[df["close"] > 0]
        df = df[df["volume"] >= 0]
        log.info(f"sanity_checks: removed {before - len(df)} invalid rows")
        return df
    pipeline._steps.append(("sanity_checks", sanity_checks))

    # ─── Step 5: Derive prev_close ────────────────────────────────────────────
    def derive_prev_close(df):
        df = df.sort_values(["symbol", "fetched_at"]).reset_index(drop=True)
        df["prev_close_derived"] = df.groupby("symbol")["close"].shift(1)
        mask = df["prev_close_derived"].isna()
        df.loc[mask, "prev_close_derived"] = df.loc[mask, "prev_close"]
        return df
    pipeline._steps.append(("derive_prev_close", derive_prev_close))

    # ─── Step 6: Feature engineering ─────────────────────────────────────────
    def feature_engineering(df):
        df["pct_change_calc"] = np.where(
            df["prev_close_derived"] > 0,
            (df["close"] - df["prev_close_derived"]) / df["prev_close_derived"] * 100,
            df["pct_change"],
        ).round(2)

        df["range"]        = (df["high"] - df["low"]).round(2)
        df["range_pct"]    = (df["range"] / df["low"] * 100).round(2)
        df["body"]         = (df["close"] - df["open"]).round(2)
        df["upper_shadow"] = (df["high"] - df[["open", "close"]].max(axis=1)).round(2)
        df["lower_shadow"] = (df[["open", "close"]].min(axis=1) - df["low"]).round(2)
        df["direction"]    = np.where(df["close"] >= df["open"], "UP", "DOWN")

        df["close_scaled"] = (
            df.groupby("symbol")["close"]
              .transform(lambda x: (x - x.min()) / (x.max() - x.min() + 1e-9))
              .round(4)
        )

        df["cum_return_pct"] = (
            df.groupby("symbol")["pct_change_calc"]
              .transform(lambda x: x.cumsum())
              .round(2)
        )

        df["fetch_hour"] = df["fetched_at"].dt.hour

        # ── Recompute MAs from clean sorted close values ──────────────────────
        # Fills gaps where extractor couldn't compute MA (not enough polls yet)
        for n, col in [(5, "ma5"), (10, "ma10"), (20, "ma20")]:
            computed = (
                df.groupby("symbol")["close"]
                  .transform(lambda x: x.ewm(span=n, adjust=False).mean().round(2))
            )
            if col not in df.columns:
                df[col] = computed
            else:
                # Prefer extractor value; fill NaN with computed
                df[col] = df[col].fillna(computed)

        return df
    pipeline._steps.append(("feature_engineering", feature_engineering))

    # ─── Step 7: Fill remaining nulls ────────────────────────────────────────
    def fill_nulls(df):
        df["pct_change_calc"] = df["pct_change_calc"].fillna(0.0)
        df["cum_return_pct"]  = df["cum_return_pct"].fillna(0.0)
        return df
    pipeline._steps.append(("fill_nulls", fill_nulls))

    # ─── Run pipeline ─────────────────────────────────────────────────────────
    cleaned = pipeline.run()
    cleaned = cleaned.sort_values(["symbol", "fetched_at"]).reset_index(drop=True)

    cleaned.to_csv(out_path, index=False)
    log.info(f"Saved cleaned.csv: {len(cleaned)} rows → {out_path}")
    return cleaned


if __name__ == "__main__":
    df = transform()
    print(df.head(20).to_string())
    print(f"\nShape: {df.shape}")
    print(f"Symbols: {df['symbol'].unique()}")
