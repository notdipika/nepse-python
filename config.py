"""
config.py  ─  NEPSE ETL Project Configuration
"""
import os
from pathlib import Path
from datetime import datetime
from zoneinfo import ZoneInfo

# ── Paths ──────────────────────────────────────────────────────────────────────
BASE_DIR    = Path(__file__).parent
DATA_DIR    = BASE_DIR / "data"
LOGS_DIR    = BASE_DIR / "logs"
REPORTS_DIR = BASE_DIR / "reports"

RAW_CSV     = DATA_DIR / "raw.csv"
CLEANED_CSV = DATA_DIR / "cleaned.csv"

for _d in (DATA_DIR, LOGS_DIR, REPORTS_DIR):
    _d.mkdir(exist_ok=True)

# ── Time ───────────────────────────────────────────────────────────────────────
NPT          = ZoneInfo("Asia/Kathmandu")
MARKET_OPEN  = (11, 0)   # 11:00 AM NPT
MARKET_CLOSE = (15, 0)   # 03:00 PM NPT
POLL_MIN     = 180       # seconds (3 min)
POLL_MAX     = 300       # seconds (5 min)

# ── Session directories ────────────────────────────────────────────────────────
def get_session_dirs(date_str: str | None = None) -> tuple[Path, Path]:
    """Returns (graphs_dir, reports_dir) for the given date (YYYY-MM-DD)."""
    date_str   = date_str or datetime.now(NPT).strftime("%Y-%m-%d")
    session_dir = BASE_DIR / "reports" / date_str
    graphs_dir  = session_dir / "graphs"
    session_dir.mkdir(parents=True, exist_ok=True)
    graphs_dir.mkdir(parents=True, exist_ok=True)
    return graphs_dir, session_dir

def today_dirs() -> tuple[Path, Path]:
    return get_session_dirs()

# ── Default watchlist ──────────────────────────────────────────────────────────
DEFAULT_SYMBOLS = [
    "NEPSE", "NABIL", "ADBL", "NTC", "NICA",
    "UPPER", "SCB",   "EBL",  "SBL", "GBIME",
]

# ── API ────────────────────────────────────────────────────────────────────────
CHART_URL = (
    "https://www.merolagani.com/handlers/TechnicalChartHandler.ashx"
    "?type=get_advanced_chart&symbol={sym}&resolution=1D"
    "&rangeStartDate={fr}&rangeEndDate={to}"
    "&from=&isAdjust=1&currencyCode=NPR"
)

HTTP_HEADERS = {
    "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36",
    "Accept": "*/*",
    "Origin": "https://www.merolagani.com",
    "Referer": "https://www.merolagani.com/",
}

# ── Nepali holidays (AD dates) ─────────────────────────────────────────────────
NEPALI_HOLIDAYS = {
    # 2025
    "2025-01-14", "2025-02-19", "2025-03-28", "2025-04-02", "2025-04-14",
    "2025-05-12", "2025-05-29", "2025-07-06", "2025-08-07", "2025-08-08",
    "2025-08-16", "2025-09-22", "2025-10-01", "2025-10-02", "2025-10-08",
    "2025-10-09", "2025-10-10", "2025-10-20", "2025-10-21", "2025-10-22",
    "2025-10-23", "2025-11-05", "2025-12-29",
    # 2026
    "2026-01-14", "2026-02-07", "2026-02-26", "2026-03-04", "2026-04-14",
    "2026-05-01", "2026-05-29", "2026-05-31",
    "2026-08-28", "2026-09-04", "2026-09-19",
    "2026-10-11", "2026-10-17", "2026-10-19", "2026-10-20", "2026-10-21",
    "2026-10-22", "2026-10-23", "2026-11-08", "2026-11-09", "2026-11-10",
    "2026-11-15", "2026-12-30",
}

# ── Circuit breaker tiers ──────────────────────────────────────────────────────
# (threshold_pct, halt_minutes, closes_day)
CIRCUIT_BREAKERS = [
    (10.0,  0, True),   # ±10% → closes the day
    ( 6.0, 40, False),  # ±6%  → 40-min halt
    ( 4.0, 20, False),  # ±4%  → 20-min halt
]

# ── Email ──────────────────────────────────────────────────────────────────────
# HOW TO SET UP (Gmail):
#   1. Go to https://myaccount.google.com/security → enable 2-Step Verification
#   2. Go to https://myaccount.google.com/apppasswords → create a 16-char App Password
#   3. Set the environment variables below (or edit the defaults):
#
#   export NEPSE_EMAIL_ENABLED=true
#   export NEPSE_EMAIL_SENDER=you@gmail.com
#   export NEPSE_EMAIL_PASSWORD=xxxx_xxxx_xxxx_xxxx   ← App Password, NOT your Gmail password
#   export NEPSE_EMAIL_RECIPIENTS=friend@gmail.com,boss@gmail.com
#
# WHY environment variables?
#   Passwords in code are dangerous — anyone who reads your code can steal them.
#   Environment variables keep secrets out of your files.

def _env_list(key: str, default: str = "") -> list[str]:
    """Split a comma-separated env var into a clean list."""
    return [e.strip() for e in os.getenv(key, default).split(",") if e.strip()]

EMAIL_ENABLED      = os.getenv("NEPSE_EMAIL_ENABLED", "true").lower() == "true"
EMAIL_SENDER       = os.getenv("NEPSE_EMAIL_SENDER",    "your_email@gmail.com")
EMAIL_PASSWORD     = os.getenv("NEPSE_EMAIL_PASSWORD",  "your_app_password_here")
EMAIL_RECIPIENTS   = _env_list("NEPSE_EMAIL_RECIPIENTS", "recipient@example.com")
EMAIL_CC           = _env_list("NEPSE_EMAIL_CC")
EMAIL_SMTP_HOST    = os.getenv("NEPSE_SMTP_HOST",  "smtp.gmail.com")
EMAIL_SMTP_PORT    = int(os.getenv("NEPSE_SMTP_PORT", "587"))
EMAIL_SUBJECT_TPL  = "NEPSE ETL Report — {date}"

# ── Report scheduler ───────────────────────────────────────────────────────────
REPORT_DELAY_MINUTES = int(os.getenv("NEPSE_REPORT_DELAY", "5"))
