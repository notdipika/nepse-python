#!/usr/bin/env bash
# ─────────────────────────────────────────────────────────────
#  NEPSE Daemon Launcher
#  Usage:
#    bash start_nepse.sh                      # use default watchlist
#    bash start_nepse.sh NABIL ADBL NTC       # custom symbols
#    bash start_nepse.sh stop                 # stop running daemon
#    bash start_nepse.sh status               # check if running
# ─────────────────────────────────────────────────────────────

DIR="$(cd "$(dirname "$0")" && pwd)"
DAEMON="$DIR/fetcher.py"
PID_FILE="$DIR/fetcher.pid"
LOG_FILE="$DIR/fetcher.log"

# ── stop ──────────────────────────────────────────────────────
if [[ "$1" == "stop" ]]; then
    if [[ -f "$PID_FILE" ]]; then
        PID=$(cat "$PID_FILE")
        if kill -0 "$PID" 2>/dev/null; then
            kill "$PID"
            echo "Sent SIGTERM to PID $PID."
        else
            echo "PID $PID not running. Cleaning up stale PID file."
            rm -f "$PID_FILE"
        fi
    else
        echo "No PID file found — daemon is not running (or was started without this launcher)."
    fi
    exit 0
fi

# ── status ─────────────────────────────────────────────────────
if [[ "$1" == "status" ]]; then
    if [[ -f "$PID_FILE" ]]; then
        PID=$(cat "$PID_FILE")
        if kill -0 "$PID" 2>/dev/null; then
            echo "✅  Daemon is RUNNING (PID $PID)."
        else
            echo "❌  PID file exists but process $PID is not running."
        fi
    else
        echo "❌  Daemon is NOT running (no PID file)."
    fi
    exit 0
fi

# ── already running? ───────────────────────────────────────────
if [[ -f "$PID_FILE" ]]; then
    PID=$(cat "$PID_FILE")
    if kill -0 "$PID" 2>/dev/null; then
        echo "⚠️   Daemon already running (PID $PID). Use 'bash start_nepse.sh stop' first."
        exit 1
    else
        rm -f "$PID_FILE"
    fi
fi

# ── launch ─────────────────────────────────────────────────────
SYMBOLS="$*"
echo "Starting NEPSE daemon in the background …"
echo "  Script : $DAEMON"
echo "  Log    : $LOG_FILE"
echo "  CSV    : $DIR/uncleaned.csv"
if [[ -n "$SYMBOLS" ]]; then
    echo "  Symbols: $SYMBOLS"
    nohup python3 "$DAEMON" $SYMBOLS >> "$LOG_FILE" 2>&1 &
else
    echo "  Symbols: (default watchlist in nepse_daemon.py)"
    nohup python3 "$DAEMON" >> "$LOG_FILE" 2>&1 &
fi

BG_PID=$!
echo ""
echo "✅  Daemon started (PID $BG_PID)."
echo "    Monitor:  tail -f $LOG_FILE"
echo "    Stop:     bash start_nepse.sh stop"
echo "    CSV:      $DIR/uncleaned.csv"