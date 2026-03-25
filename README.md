# NEPSE ETL Project

A fully automated NEPSE stock market ETL pipeline with visualization and PDF reporting.

## Project Structure

```
NEPSE_ETL_PROJECT/
├── config.py           — Central config (symbols, paths, timings, holidays)
├── logger.py           — Rotating log handler
├── extractor.py        — Stage 1: Fetch OHLCV from merolagani API → raw.csv
├── transformer.py      — Stage 2: Clean, validate, enrich → cleaned.csv
├── loader.py           — Stage 3/4: Generate all charts (PNG)
├── report_generator.py — Stage 5: Compile charts + stats → PDF report
├── pipeline.py         — Master orchestrator
├── scheduler.py        — Auto-run daily Sun–Thu 11:00–15:00 NPT
├── requirements.txt
├── data/
│   ├── raw.csv         — Raw fetched data
│   └── cleaned.csv     — Cleaned & enriched data
├── logs/
│   └── nepse_etl.log   — Rotating logs
└── reports/
    ├── *.png           — Generated charts
    └── NEPSE_Report_*.pdf
```

## Quick Start

```bash
pip install -r requirements.txt

# Demo mode (synthetic data, no live market needed)
python pipeline.py --demo

# Full live pipeline (auto-fetches 11AM–3PM NPT, then generates report)
python pipeline.py

# Custom symbols
python pipeline.py --symbols NABIL ADBL NTC NICA SCB

# Daily auto-scheduler
python scheduler.py

# If you already have raw.csv, skip extraction
python pipeline.py --transform-only
```

## Pipeline Stages

| Stage | File | Output |
|-------|------|--------|
| 1 · Extract   | `extractor.py`       | `data/raw.csv`     |
| 2 · Transform | `transformer.py`     | `data/cleaned.csv` |
| 3/4 · Load    | `loader.py`          | `reports/*.png`    |
| 5 · Report    | `report_generator.py`| `reports/*.pdf`    |

## Charts Generated

1. Close Price Line Chart (all symbols)
2. % Change Bar Chart
3. Candlestick Charts (top 4 symbols)
4. Volume Bar Chart
5. Correlation Heatmap
6. Cumulative Return Line
7. OHLCV Summary Table
8. NEPSE Index Intraday Chart

## Market Schedule

- Trading days: **Sunday – Thursday**
- Market hours: **11:00 AM – 3:00 PM NPT**
- Polling interval: **3–5 minutes** (cache-matched to merolagani)
- Circuit breakers: ±4% (20 min halt), ±6% (40 min halt), ±10% (day closed)
