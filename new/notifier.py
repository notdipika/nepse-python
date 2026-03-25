"""
notifier.py  ─  Cross-platform desktop notification

Supports:
  • Linux   — notify-send  (install: sudo apt install libnotify-bin)
  • macOS   — osascript
  • Windows — PowerShell WinRT Toast → VBScript balloon fallback

Never crashes the main process; all errors are logged and swallowed.

Usage:
    from notifier import notify
    notify("NEPSE Report Ready", "PDF saved to reports/2026-03-26/")
"""

import os
import sys
import platform
import subprocess
import threading
from pathlib import Path

from logger import get_logger

log = get_logger("notifier")

_SYSTEM = platform.system()   # "Linux" | "Darwin" | "Windows"


# ─── Internal send functions ──────────────────────────────────────────────────

def _linux(title: str, body: str):
    try:
        subprocess.run(
            ["notify-send", title, body,
             "--icon=dialog-information", "--expire-time=10000"],
            timeout=5, capture_output=True,
        )
        log.info("Desktop notification sent (notify-send).")
    except FileNotFoundError:
        log.info("notify-send not found — trying zenity …")
        try:
            subprocess.run(
                ["zenity", "--info", f"--title={title}", f"--text={body}",
                 "--timeout=10"],
                timeout=12, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            )
            log.info("Desktop notification sent (zenity).")
        except FileNotFoundError:
            log.info("No desktop notification tool found on Linux (notify-send / zenity).")
    except Exception as e:
        log.debug(f"Linux notification error: {e}")


def _macos(title: str, body: str):
    try:
        script = (
            f'display notification "{body}" '
            f'with title "{title}" '
            'sound name "Glass"'
        )
        subprocess.Popen(["osascript", "-e", script])
        log.info("Desktop notification sent (osascript).")
    except Exception as e:
        log.debug(f"macOS notification error: {e}")


def _windows(title: str, body: str, pdf_path: str | None = None):
    # Method 1 — WinRT Toast (Windows 10/11)
    toast_ps = f"""
try {{
    [Windows.UI.Notifications.ToastNotificationManager,Windows.UI.Notifications,ContentType=WindowsRuntime] | Out-Null
    [Windows.Data.Xml.Dom.XmlDocument,Windows.Data.Xml.Dom,ContentType=WindowsRuntime] | Out-Null
    $template = [Windows.UI.Notifications.ToastTemplateType]::ToastText02
    $xml = [Windows.UI.Notifications.ToastNotificationManager]::GetTemplateContent($template)
    $xml.GetElementsByTagName('text')[0].AppendChild($xml.CreateTextNode('{title}')) | Out-Null
    $xml.GetElementsByTagName('text')[1].AppendChild($xml.CreateTextNode('{body}')) | Out-Null
    $toast = [Windows.UI.Notifications.ToastNotification]::new($xml)
    [Windows.UI.Notifications.ToastNotificationManager]::CreateToastNotifier('NEPSE ETL').Show($toast)
    Write-Output "TOAST_OK"
}} catch {{
    Write-Output "TOAST_FAIL: $_"
}}
"""
    toast_ok = False
    try:
        result = subprocess.run(
            ["powershell", "-WindowStyle", "Hidden", "-NonInteractive",
             "-Command", toast_ps],
            capture_output=True, text=True, timeout=15,
        )
        if "TOAST_OK" in (result.stdout or ""):
            toast_ok = True
            log.info("Desktop notification sent (Windows Toast).")
    except Exception as e:
        log.debug(f"Windows Toast error: {e}")

    # Method 2 — VBScript balloon (fallback)
    if not toast_ok:
        vbs = (
            f'Set s = CreateObject("WScript.Shell")\n'
            f's.Popup "{body}", 30, "{title}", 64\n'
        )
        vbs_path = os.path.join(os.environ.get("TEMP", "."), "_nepse_notify.vbs")
        try:
            with open(vbs_path, "w") as f:
                f.write(vbs)
            subprocess.run(
                ["cscript", "//Nologo", vbs_path],
                capture_output=True, text=True, timeout=35,
            )
            log.info("Desktop notification sent (VBScript balloon).")
        except Exception as e:
            log.debug(f"VBScript notification error: {e}")

    # Open PDF automatically on Windows
    if pdf_path and os.path.exists(pdf_path):
        try:
            os.startfile(pdf_path)
            log.info("PDF opened in default viewer.")
        except Exception as e:
            log.debug(f"Could not open PDF: {e}")


# ─── Public API ───────────────────────────────────────────────────────────────

def notify(title: str, body: str, pdf_path: str | Path | None = None):
    """
    Send a desktop notification synchronously.
    Safe to call from any thread; never raises.
    """
    if isinstance(pdf_path, Path):
        pdf_path = str(pdf_path)

    try:
        if _SYSTEM == "Linux":
            _linux(title, body)
        elif _SYSTEM == "Darwin":
            _macos(title, body)
        elif _SYSTEM == "Windows":
            _windows(title, body, pdf_path)
        else:
            log.info(f"Unsupported platform ({_SYSTEM}) — skipping desktop notification.")
    except Exception as e:
        log.debug(f"notify() swallowed unexpected error: {e}")


def notify_async(title: str, body: str, pdf_path: str | Path | None = None):
    """
    Non-blocking wrapper — fires and forgets in a daemon thread.
    """
    threading.Thread(
        target=notify,
        args=(title, body, pdf_path),
        daemon=True,
    ).start()


# ─── CLI test ─────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    notify(
        "NEPSE ETL — Test",
        "If you see this, desktop notifications are working!",
    )
    print("Notification fired. Check your desktop.")
