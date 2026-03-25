"""
config.py  ─  NEPSE ETL Project Configuration
"""
import os
from pathlib import Path
from zoneinfo import ZoneInfo

# ── Paths ─────────────────────────────────────────────────────────────────────
BASE_DIR     = Path(__file__).parent
DATA_DIR     = BASE_DIR / "data"
LOGS_DIR     = BASE_DIR / "logs"
REPORTS_DIR  = BASE_DIR / "reports"

RAW_CSV      = DATA_DIR / "raw.csv"
CLEANED_CSV  = DATA_DIR / "cleaned.csv"

for d in (DATA_DIR, LOGS_DIR, REPORTS_DIR):
    d.mkdir(exist_ok=True)

# ── Time ──────────────────────────────────────────────────────────────────────
NPT          = ZoneInfo("Asia/Kathmandu")
MARKET_OPEN  = (11, 0)   # 11:00 AM NPT
MARKET_CLOSE = (15, 0)   # 03:00 PM NPT
POLL_MIN     = 180       # 3 min
POLL_MAX     = 300       # 5 min

# ── Default watchlist (edit or override via CLI) ───────────────────────────────
DEFAULT_SYMBOLS = [
    "NEPSE", "NABIL", "ADBL", "NTC", "NICA",
    "UPPER", "SCB", "EBL", "SBL", "GBIME",
]

# ── API ───────────────────────────────────────────────────────────────────────
CHART_URL = (
    "https://www.merolagani.com/handlers/TechnicalChartHandler.ashx"
    "?type=get_advanced_chart&symbol={sym}&resolution=1D"
    "&rangeStartDate={fr}&rangeEndDate={to}"
    "&from=&isAdjust=1&currencyCode=NPR"
)

HTTP_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
    "Accept": "*/*",
    "Origin": "https://www.merolagani.com",
    "Referer": "https://www.merolagani.com/",
}

# ── Nepali holidays (AD dates) ─────────────────────────────────────────────────
NEPALI_HOLIDAYS = {
    "2026-01-14", "2026-02-07", "2026-02-26", "2026-03-04",
    "2026-04-14", "2026-05-01", "2026-05-29", "2026-05-31",
    "2026-08-28", "2026-09-04", "2026-09-19",
    "2026-10-11", "2026-10-17", "2026-10-19", "2026-10-20",
    "2026-10-21", "2026-10-22", "2026-10-23",
    "2026-11-08", "2026-11-09", "2026-11-10", "2026-11-15",
    "2026-12-30",
}

# ── Circuit breaker tiers ─────────────────────────────────────────────────────
CIRCUIT_BREAKERS = [
    (10.0,  0,  True),
    ( 6.0, 40, False),
    ( 4.0, 20, False),
]
