"""
email_sender.py  ─  Send the NEPSE PDF report via Gmail (SMTP / TLS)

HOW EMAIL SENDING WORKS (simple explanation):
─────────────────────────────────────────────
  Your computer acts like a mail client (like Outlook or Gmail app).
  It connects to Gmail's mail server (smtp.gmail.com) on port 587,
  says "hello, I want to send an email", logs in with your credentials,
  hands over the message, and the server delivers it to recipients.

  The protocol used is called SMTP (Simple Mail Transfer Protocol).
  TLS encryption is used so your password isn't sent in plain text.

HOW TO SET UP (one-time):
─────────────────────────
  1. You need a Gmail account. Go to:
     https://myaccount.google.com/security  →  enable 2-Step Verification

  2. Generate an "App Password" (NOT your real Gmail password):
     https://myaccount.google.com/apppasswords
     → Select "Mail" + "Other (Custom name)" → Generate → copy the 16-char code

  3. Set these environment variables before running (in your terminal):
       export NEPSE_EMAIL_SENDER=you@gmail.com
       export NEPSE_EMAIL_PASSWORD=xxxx_xxxx_xxxx_xxxx
       export NEPSE_EMAIL_RECIPIENTS=friend@gmail.com,other@gmail.com
       export NEPSE_EMAIL_ENABLED=true

     On Windows (Command Prompt):
       set NEPSE_EMAIL_SENDER=you@gmail.com
       set NEPSE_EMAIL_PASSWORD=xxxx_xxxx_xxxx_xxxx

  WHY App Password and not your regular password?
  → Regular password won't work with SMTP if 2FA is on.
  → App passwords are scoped and can be revoked without changing your main password.

Standalone test:
  python email_sender.py path/to/NEPSE_Report.pdf [recipient@example.com ...]
"""

import ssl
import smtplib
import socket
from datetime import datetime
from email.mime.multipart   import MIMEMultipart
from email.mime.text        import MIMEText
from email.mime.application import MIMEApplication
from pathlib import Path

from config import (
    EMAIL_ENABLED, EMAIL_SENDER, EMAIL_PASSWORD,
    EMAIL_RECIPIENTS, EMAIL_CC,
    EMAIL_SMTP_HOST, EMAIL_SMTP_PORT,
    EMAIL_SUBJECT_TPL, NPT,
)
from logger import get_logger

log = get_logger("email_sender")


# ─── Build email body ──────────────────────────────────────────────────────────

def _build_html(pdf_path: Path, summary: dict | None = None) -> str:
    """
    Returns an HTML string for the email body.
    HTML emails are just web pages embedded in the message — most mail
    clients render them like a mini website.
    """
    today_str    = datetime.now(NPT).strftime("%A, %d %B %Y")
    generated_at = datetime.now(NPT).strftime("%H:%M NPT")
    file_size    = f"{pdf_path.stat().st_size / 1024:.1f} KB" if pdf_path.exists() else "—"

    # Build the KPI stats table rows (if summary data was provided)
    kpi_rows = ""
    if summary:
        items = [
            ("Symbols Tracked",  str(summary.get("n_symbols",   "—"))),
            ("Total Volume",     f"{summary.get('total_volume', 0):,}"),
            ("Gainers / Losers", f"{summary.get('gainers', '—')} / {summary.get('losers', '—')}"),
            ("Avg % Change",     f"{summary.get('avg_change', 0.0):+.2f}%"),
        ]
        for label, value in items:
            kpi_rows += (
                f'<tr>'
                f'<td style="padding:9px 18px;color:#555;font-size:13px;border-bottom:1px solid #e8ecf0;">{label}</td>'
                f'<td style="padding:9px 18px;font-weight:600;color:#1A3A5C;font-size:13px;text-align:right;border-bottom:1px solid #e8ecf0;">{value}</td>'
                f'</tr>'
            )

    kpi_section = ""
    if kpi_rows:
        kpi_section = f"""
        <h3 style="color:#1565C0;font-size:14px;margin:28px 0 8px;font-family:Arial,sans-serif;">Session Highlights</h3>
        <table width="100%" cellpadding="0" cellspacing="0"
               style="border:1px solid #D6E4F0;border-radius:6px;border-collapse:collapse;background:#F8FBFF;margin-bottom:8px;">
          <thead>
            <tr style="background:#1565C0;">
              <th style="padding:10px 18px;color:white;font-size:12px;text-align:left;font-family:Arial,sans-serif;border-radius:6px 0 0 0;">Metric</th>
              <th style="padding:10px 18px;color:white;font-size:12px;text-align:right;font-family:Arial,sans-serif;border-radius:0 6px 0 0;">Value</th>
            </tr>
          </thead>
          <tbody>{kpi_rows}</tbody>
        </table>"""

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8"/>
  <meta name="viewport" content="width=device-width,initial-scale=1.0"/>
  <title>NEPSE ETL Report</title>
</head>
<body style="margin:0;padding:0;background:#F0F4F8;font-family:'Segoe UI',Arial,sans-serif;">
  <table width="100%" cellpadding="0" cellspacing="0" style="background:#F0F4F8;padding:32px 16px;">
    <tr><td align="center">
      <table width="600" cellpadding="0" cellspacing="0"
             style="background:#FFFFFF;border-radius:10px;box-shadow:0 2px 12px rgba(0,0,0,0.10);overflow:hidden;max-width:600px;">

        <!-- Header -->
        <tr>
          <td style="background:linear-gradient(135deg,#0d1b2a 0%,#1565c0 100%);padding:28px 32px;">
            <h2 style="margin:0;color:#29b6f6;font-size:22px;font-family:Arial,sans-serif;">&#128200; NEPSE Daily Market Report</h2>
            <p style="margin:6px 0 0;color:#90caf9;font-size:13px;font-family:Arial,sans-serif;">
              {today_str} &nbsp;&middot;&nbsp; Generated {generated_at}
            </p>
          </td>
        </tr>

        <!-- Body -->
        <tr>
          <td style="padding:28px 32px 24px;">
            <p style="color:#333;font-size:14px;line-height:1.7;margin:0 0 20px;">
              Your NEPSE daily market report is ready and attached as a PDF.
              The report includes closing-price charts, moving averages, volume
              analysis, and key statistics for all tracked symbols.
            </p>

            {kpi_section}

            <!-- Attachment badge -->
            <table width="100%" cellpadding="0" cellspacing="0"
                   style="margin-top:24px;border:1px solid #E0E7EF;border-radius:8px;background:#F8FBFF;">
              <tr>
                <td style="padding:14px 16px;font-size:22px;width:44px;">&#128206;</td>
                <td style="padding:14px 8px;">
                  <p style="margin:0;color:#1A1A2E;font-size:13px;font-weight:600;font-family:Arial,sans-serif;">{pdf_path.name}</p>
                  <p style="margin:3px 0 0;color:#888;font-size:12px;font-family:Arial,sans-serif;">PDF Report &nbsp;&middot;&nbsp; {file_size}</p>
                </td>
              </tr>
            </table>
          </td>
        </tr>

        <!-- Footer -->
        <tr>
          <td style="background:#F4F6FA;padding:16px 32px;border-top:1px solid #E8ECF4;">
            <p style="margin:0;color:#999;font-size:11px;text-align:center;font-family:Arial,sans-serif;">
              Data source: merolagani.com &nbsp;&middot;&nbsp; NEPSE ETL Pipeline &nbsp;&middot;&nbsp; For informational purposes only.
            </p>
          </td>
        </tr>

      </table>
    </td></tr>
  </table>
</body>
</html>"""


def _build_plain(pdf_path: Path, summary: dict | None = None) -> str:
    """Plain-text fallback for email clients that don't render HTML."""
    date_str = datetime.now(NPT).strftime("%A, %d %B %Y  %H:%M NPT")
    lines = [
        "NEPSE ETL Analytics Report",
        "=" * 40,
        f"Generated : {date_str}",
        f"Attachment: {pdf_path.name}",
        "",
    ]
    if summary:
        lines += [
            "Session Highlights",
            "-" * 22,
            f"  Symbols Tracked : {summary.get('n_symbols', '—')}",
            f"  Total Volume     : {summary.get('total_volume', 0):,}",
            f"  Gainers / Losers : {summary.get('gainers', '—')} / {summary.get('losers', '—')}",
            f"  Avg % Change     : {summary.get('avg_change', 0.0):+.2f}%",
            "",
        ]
    lines += [
        "Please open the attached PDF for the full analytics report.",
        "",
        "—",
        "NEPSE ETL Pipeline  |  Data: merolagani.com  |  Informational use only.",
    ]
    return "\n".join(lines)


# ─── Core send function ────────────────────────────────────────────────────────

def send_report(
    pdf_path: Path,
    recipients: list[str] | None = None,
    cc: list[str] | None = None,
    summary: dict | None = None,
) -> bool:
    """
    Build and send an email with the PDF attached.

    Args:
        pdf_path   : Path to the generated PDF file.
        recipients : Who to send to (defaults to config.EMAIL_RECIPIENTS).
        cc         : CC recipients (defaults to config.EMAIL_CC).
        summary    : Optional session stats dict for the KPI table:
                       {n_symbols, total_volume, gainers, losers, avg_change}

    Returns:
        True on success, False on failure.
    """
    if not EMAIL_ENABLED:
        log.info("Email sending disabled (NEPSE_EMAIL_ENABLED=false). Skipping.")
        return False

    if not pdf_path.exists():
        log.error(f"PDF not found, cannot email: {pdf_path}")
        return False

    to_list = recipients or EMAIL_RECIPIENTS
    cc_list = cc         or EMAIL_CC

    if not to_list:
        log.warning("No recipients configured. Set NEPSE_EMAIL_RECIPIENTS.")
        return False

    # ── Build the message ──────────────────────────────────────────────────────
    subject = EMAIL_SUBJECT_TPL.format(date=datetime.now(NPT).strftime("%d %b %Y"))

    # MIMEMultipart("mixed") = an email that can have both body text and attachments
    msg = MIMEMultipart("mixed")
    msg["From"]    = f"NEPSE ETL Pipeline <{EMAIL_SENDER}>"
    msg["To"]      = ", ".join(to_list)
    msg["Subject"] = subject
    if cc_list:
        msg["Cc"] = ", ".join(cc_list)

    # An "alternative" part holds both plain-text and HTML versions.
    # The email client picks whichever it supports (HTML preferred).
    alt = MIMEMultipart("alternative")
    alt.attach(MIMEText(_build_plain(pdf_path, summary), "plain"))
    alt.attach(MIMEText(_build_html(pdf_path,  summary), "html"))
    msg.attach(alt)

    # Attach the PDF file
    with open(pdf_path, "rb") as fh:
        part = MIMEApplication(fh.read(), _subtype="pdf")
    part.add_header("Content-Disposition", "attachment", filename=pdf_path.name)
    msg.attach(part)

    # ── Send via SMTP ──────────────────────────────────────────────────────────
    # SMTP steps explained:
    #   1. Connect to smtp.gmail.com:587
    #   2. ehlo() → say hello, negotiate features
    #   3. starttls() → upgrade connection to encrypted TLS
    #   4. login() → authenticate with your email + App Password
    #   5. sendmail() → hand over the message bytes
    all_recipients = to_list + cc_list
    try:
        log.info(f"Connecting to {EMAIL_SMTP_HOST}:{EMAIL_SMTP_PORT} …")
        context = ssl.create_default_context()
        with smtplib.SMTP(EMAIL_SMTP_HOST, EMAIL_SMTP_PORT, timeout=30) as server:
            server.ehlo()
            server.starttls(context=context)
            server.ehlo()
            server.login(EMAIL_SENDER, EMAIL_PASSWORD)
            server.sendmail(EMAIL_SENDER, all_recipients, msg.as_string())
        log.info(f"Report emailed to: {', '.join(all_recipients)}")
        return True

    except smtplib.SMTPAuthenticationError:
        log.error(
            "Authentication failed. Check NEPSE_EMAIL_SENDER and NEPSE_EMAIL_PASSWORD. "
            "Use a Gmail App Password, not your main password."
        )
    except smtplib.SMTPRecipientsRefused as e:
        log.error(f"Recipient(s) refused by server: {e}")
    except smtplib.SMTPConnectError as e:
        log.error(f"Could not connect to {EMAIL_SMTP_HOST}: {e}")
    except socket.timeout:
        log.error(f"Connection timed out to {EMAIL_SMTP_HOST}:{EMAIL_SMTP_PORT}.")
    except Exception as e:
        log.error(f"Failed to send email: {e}", exc_info=True)

    return False


# ─── CLI test ──────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    import sys
    if len(sys.argv) < 2:
        print("Usage: python email_sender.py path/to/report.pdf [recipient@example.com ...]")
        sys.exit(1)
    path  = Path(sys.argv[1])
    recip = sys.argv[2:] or None
    sys.exit(0 if send_report(path, recipients=recip) else 1)
