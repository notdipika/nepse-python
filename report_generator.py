"""
report_generator.py  ─  Stage 4 (output): PDF Report
Compiles all charts + statistics into a professional PDF.
"""
import io
from datetime import datetime
from pathlib import Path

import pandas as pd
from reportlab.lib.pagesizes import A4
from reportlab.lib import colors
from reportlab.lib.units import cm
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.enums import TA_CENTER, TA_LEFT, TA_RIGHT
from reportlab.platypus import (
    SimpleDocTemplate, Paragraph, Spacer, Image, Table,
    TableStyle, PageBreak, HRFlowable,
)
from reportlab.platypus import KeepTogether

from config import CLEANED_CSV, REPORTS_DIR
from logger import get_logger

log = get_logger("report_generator")

# ─── Colour palette ───────────────────────────────────────────────────────────
C_BG     = colors.HexColor("#0D1117")
C_CARD   = colors.HexColor("#161B22")
C_BORDER = colors.HexColor("#30363D")
C_TEXT   = colors.HexColor("#E6EDF3")
C_MUTED  = colors.HexColor("#8B949E")
C_GREEN  = colors.HexColor("#26A69A")
C_RED    = colors.HexColor("#EF5350")
C_BLUE   = colors.HexColor("#0A84FF")
C_GOLD   = colors.HexColor("#FF9F0A")
C_WHITE  = colors.white


def build_styles():
    base = getSampleStyleSheet()

    styles = {
        "Title": ParagraphStyle(
            "NepseTitle",
            parent=base["Normal"],
            fontSize=28, fontName="Helvetica-Bold",
            textColor=C_WHITE, alignment=TA_CENTER,
            spaceAfter=4,
        ),
        "Subtitle": ParagraphStyle(
            "NepseSubtitle",
            parent=base["Normal"],
            fontSize=13, fontName="Helvetica",
            textColor=C_MUTED, alignment=TA_CENTER,
            spaceAfter=2,
        ),
        "SectionHead": ParagraphStyle(
            "SectionHead",
            parent=base["Normal"],
            fontSize=14, fontName="Helvetica-Bold",
            textColor=C_BLUE, spaceBefore=12, spaceAfter=6,
            borderPad=(0, 0, 4, 0),
        ),
        "Body": ParagraphStyle(
            "NepseBody",
            parent=base["Normal"],
            fontSize=9, fontName="Helvetica",
            textColor=C_TEXT, leading=14, spaceAfter=4,
        ),
        "Small": ParagraphStyle(
            "NepseSmall",
            parent=base["Normal"],
            fontSize=7.5, fontName="Helvetica",
            textColor=C_MUTED, leading=11,
        ),
        "Footer": ParagraphStyle(
            "NepseFooter",
            parent=base["Normal"],
            fontSize=7, fontName="Helvetica",
            textColor=C_MUTED, alignment=TA_CENTER,
        ),
        "Metric": ParagraphStyle(
            "NepseMetric",
            parent=base["Normal"],
            fontSize=20, fontName="Helvetica-Bold",
            textColor=C_WHITE, alignment=TA_CENTER,
        ),
        "MetricLabel": ParagraphStyle(
            "NepseMetricLabel",
            parent=base["Normal"],
            fontSize=7.5, fontName="Helvetica",
            textColor=C_MUTED, alignment=TA_CENTER,
        ),
    }
    return styles


def hr(color=C_BORDER, thickness=0.5):
    return HRFlowable(width="100%", thickness=thickness,
                      color=color, spaceAfter=8, spaceBefore=4)


def section_heading(text: str, styles: dict):
    return KeepTogether([
        Paragraph(text, styles["SectionHead"]),
        hr(C_BLUE, 1),
    ])


def add_chart(path: Path, caption: str, styles: dict,
              max_w=17*cm, max_h=11*cm) -> list:
    if not path or not path.exists():
        return [Paragraph(f"[Chart not available: {caption}]",
                          styles["Small"]), Spacer(1, 6)]
    img = Image(str(path))
    iw, ih = img.imageWidth, img.imageHeight
    scale = min(max_w / iw, max_h / ih, 1.0)
    img.drawWidth  = iw * scale
    img.drawHeight = ih * scale
    cap = Paragraph(f"<i>{caption}</i>", styles["Small"])
    return [img, Spacer(1, 3), cap, Spacer(1, 10)]


def kpi_table(metrics: list[tuple], styles: dict) -> Table:
    """metrics: [(value_str, label), ...]"""
    cells = [[Paragraph(v, styles["Metric"]) for v, _ in metrics],
             [Paragraph(l, styles["MetricLabel"]) for _, l in metrics]]
    col_w = [17 * cm / len(metrics)] * len(metrics)
    t = Table(cells, colWidths=col_w)
    t.setStyle(TableStyle([
        ("BACKGROUND",   (0, 0), (-1, -1), C_CARD),
        ("ROUNDEDCORNERS", [6]),
        ("BOX",          (0, 0), (-1, -1), 0.5, C_BORDER),
        ("INNERGRID",    (0, 0), (-1, -1), 0.3, C_BORDER),
        ("TOPPADDING",   (0, 0), (-1, -1), 10),
        ("BOTTOMPADDING",(0, 0), (-1, -1), 10),
        ("ALIGN",        (0, 0), (-1, -1), "CENTER"),
    ]))
    return t


def data_table(df_slice: pd.DataFrame, styles: dict) -> Table:
    """Render a DataFrame slice as a formatted table."""
    header = [Paragraph(f"<b>{c}</b>", styles["Small"]) for c in df_slice.columns]
    rows   = [header]
    for _, row in df_slice.iterrows():
        cells = [Paragraph(str(v), styles["Small"]) for v in row]
        rows.append(cells)

    col_w = [17 * cm / len(df_slice.columns)] * len(df_slice.columns)
    t = Table(rows, colWidths=col_w, repeatRows=1)
    t.setStyle(TableStyle([
        ("BACKGROUND",    (0, 0), (-1, 0),  C_CARD),
        ("TEXTCOLOR",     (0, 0), (-1, 0),  C_WHITE),
        ("BACKGROUND",    (0, 1), (-1, -1), C_BG),
        ("TEXTCOLOR",     (0, 1), (-1, -1), C_TEXT),
        ("ROWBACKGROUNDS",(0, 1), (-1, -1), [C_BG, C_CARD]),
        ("BOX",           (0, 0), (-1, -1), 0.5, C_BORDER),
        ("INNERGRID",     (0, 0), (-1, -1), 0.3, C_BORDER),
        ("TOPPADDING",    (0, 0), (-1, -1), 5),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
        ("LEFTPADDING",   (0, 0), (-1, -1), 6),
        ("RIGHTPADDING",  (0, 0), (-1, -1), 6),
        ("ALIGN",         (0, 0), (-1, -1), "CENTER"),
        ("FONTSIZE",      (0, 0), (-1, -1), 7.5),
    ]))
    return t


def generate_report(charts: dict, df: pd.DataFrame,
                    out_name: str | None = None) -> Path:

    now_str = datetime.now().strftime("%Y%m%d_%H%M%S")
    if not out_name:
        out_name = f"NEPSE_Report_{now_str}.pdf"
    out_path = REPORTS_DIR / out_name

    styles = build_styles()
    doc = SimpleDocTemplate(
        str(out_path),
        pagesize=A4,
        leftMargin=2*cm, rightMargin=2*cm,
        topMargin=1.5*cm, bottomMargin=1.5*cm,
        title="NEPSE ETL Report",
        author="NEPSE ETL Pipeline",
    )

    story = []
    W, H = A4

    # ─── Cover Page ───────────────────────────────────────────────────────────
    story.append(Spacer(1, 2*cm))
    story.append(Paragraph("NEPSE", styles["Title"]))
    story.append(Paragraph("Live ETL  ·  Analytics Report", styles["Subtitle"]))
    story.append(Spacer(1, 0.3*cm))

    rng = ""
    if not df.empty:
        mn = df["fetched_at"].min().strftime("%d %b %Y  %H:%M")
        mx = df["fetched_at"].max().strftime("%d %b %Y  %H:%M")
        rng = f"Session: {mn} – {mx} NPT"
    story.append(Paragraph(rng, styles["Subtitle"]))
    story.append(Spacer(1, 0.5*cm))
    story.append(hr(C_BLUE, 1.5))

    # KPIs
    if not df.empty:
        latest = df.sort_values("fetched_at").groupby("symbol").last()
        total_vol   = int(latest["volume"].sum())
        avg_chg     = latest["pct_change_calc"].mean()
        n_up        = int((latest["pct_change_calc"] > 0).sum())
        n_down      = int((latest["pct_change_calc"] < 0).sum())
        n_symbols   = df["symbol"].nunique()

        metrics = [
            (f"{n_symbols}", "Symbols Tracked"),
            (f"{total_vol:,}", "Total Volume"),
            (f"{n_up} / {n_down}", "Gainers / Losers"),
            (f"{avg_chg:+.2f}%", "Avg % Change"),
        ]
        story.append(kpi_table(metrics, styles))

    story.append(Spacer(1, 0.6*cm))
    story.append(Paragraph(
        "Generated by NEPSE ETL Pipeline  ·  Data source: merolagani.com",
        styles["Footer"],
    ))
    story.append(PageBreak())

    # ─── Section 1: Charts ────────────────────────────────────────────────────
    story.append(section_heading("1. Price & Market Overview", styles))

    if "nepse_index" in charts:
        story += add_chart(charts["nepse_index"],
                           "Figure 1 — NEPSE Index: Close Price & Volume (Intraday)", styles)

    if "close_lines" in charts:
        story += add_chart(charts["close_lines"],
                           "Figure 2 — Close Price Line Chart: All Tracked Symbols", styles)

    story.append(PageBreak())
    story.append(section_heading("2. Returns & Performance", styles))

    if "pct_change_bars" in charts:
        story += add_chart(charts["pct_change_bars"],
                           "Figure 3 — Latest % Change vs Previous Close", styles)

    if "cumulative_return" in charts:
        story += add_chart(charts["cumulative_return"],
                           "Figure 4 — Cumulative Return (%) Over Session", styles)

    story.append(PageBreak())
    story.append(section_heading("3. Candlestick Analysis", styles))
    story.append(Paragraph(
        "Candlestick charts show OHLCV data for each polling interval. "
        "Green bodies indicate closing above open (bullish); "
        "red bodies indicate closing below open (bearish). "
        "Wicks represent the high/low range.",
        styles["Body"],
    ))
    story.append(Spacer(1, 6))

    if "candlestick" in charts:
        story += add_chart(charts["candlestick"],
                           "Figure 5 — Candlestick Charts: Top 4 Symbols", styles,
                           max_h=14*cm)

    story.append(PageBreak())
    story.append(section_heading("4. Volume & Correlation", styles))

    if "volume" in charts:
        story += add_chart(charts["volume"],
                           "Figure 6 — Cumulative Session Volume by Symbol", styles)

    if "correlation" in charts:
        story += add_chart(charts["correlation"],
                           "Figure 7 — % Change Correlation Heatmap", styles)

    story.append(PageBreak())
    story.append(section_heading("5. Session Summary Table", styles))

    if "summary_table" in charts:
        story += add_chart(charts["summary_table"],
                           "Figure 8 — OHLCV Summary (Latest Values)", styles,
                           max_h=12*cm)

    # ─── Section 2: Data Tables ───────────────────────────────────────────────
    story.append(PageBreak())
    story.append(section_heading("6. Descriptive Statistics", styles))

    if not df.empty:
        cols = ["open", "high", "low", "close", "volume", "pct_change_calc", "range"]
        avail_cols = [c for c in cols if c in df.columns]
        desc = df[avail_cols].describe().round(2).reset_index()
        desc.columns = ["Stat"] + avail_cols
        story.append(data_table(desc, styles))
        story.append(Spacer(1, 10))

        story.append(Paragraph(
            "<b>Key observations:</b>  "
            "The table above shows count, mean, standard deviation, min, "
            "25th/50th/75th percentiles, and max for all numeric fields. "
            "Large spread in volume indicates varied liquidity across symbols. "
            "The range column captures intraday price movement width.",
            styles["Body"],
        ))

    # ─── Section 3: Raw data sample ───────────────────────────────────────────
    story.append(PageBreak())
    story.append(section_heading("7. Cleaned Data Sample (Latest 20 Rows)", styles))

    if not df.empty:
        show_cols = ["fetched_at", "symbol", "open", "high", "low",
                     "close", "volume", "pct_change_calc", "direction"]
        avail = [c for c in show_cols if c in df.columns]
        sample = (df.sort_values("fetched_at", ascending=False)
                    .head(20)[avail]
                    .copy())
        sample["fetched_at"] = sample["fetched_at"].dt.strftime("%H:%M:%S")
        for col in ("open", "high", "low", "close"):
            if col in sample:
                sample[col] = sample[col].map(lambda x: f"{x:,.2f}")
        if "volume" in sample:
            sample["volume"] = sample["volume"].map(lambda x: f"{x:,}")
        if "pct_change_calc" in sample:
            sample["pct_change_calc"] = sample["pct_change_calc"].map(
                lambda x: f"{'+' if float(x) >= 0 else ''}{x:.2f}%"
                if isinstance(x, (int, float)) else x
            )
        sample.columns = [c.replace("_calc", "").replace("_", " ").title()
                          for c in sample.columns]
        story.append(data_table(sample, styles))

    # ─── Footer ───────────────────────────────────────────────────────────────
    story.append(Spacer(1, 1*cm))
    story.append(hr())
    story.append(Paragraph(
        f"NEPSE ETL Pipeline  ·  Report generated {datetime.now().strftime('%d %b %Y  %H:%M:%S')} NPT  ·  "
        "Data source: merolagani.com  ·  For informational purposes only.",
        styles["Footer"],
    ))

    doc.build(story)
    log.info(f"PDF report saved: {out_path}")
    return out_path


if __name__ == "__main__":
    from loader import load_cleaned, generate_all_charts
    df = load_cleaned()
    charts = generate_all_charts(df)
    path = generate_report(charts, df)
    print(f"Report: {path}")
