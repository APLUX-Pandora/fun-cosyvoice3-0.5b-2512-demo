#!/bin/bash
# Stop only this deployment and wait for its model owner to finish cleanup.
set -eu
D="$(cd "$(dirname "$0")" && pwd)"
PID_FILE="$D/web.pid"
if [ ! -f "$PID_FILE" ]; then
    echo "No recorded demo process."
    exit 0
fi
read -r task_pid < "$PID_FILE"
case "$task_pid" in
    ""|*[!0-9]*) echo "Invalid demo PID file; no process signalled." >&2; exit 1 ;;
esac
if [ "$task_pid" -le 1 ]; then
    echo "Invalid demo PID; no process signalled." >&2
    exit 1
fi
if ! kill -0 "$task_pid" 2>/dev/null; then
    rm -f "$PID_FILE"
    echo "Recorded demo process has already exited."
    exit 0
fi
if ! tr '\0' '\n' < "/proc/$task_pid/cmdline" | grep -Fxq "$D/app.py"; then
    echo "Recorded PID is not this demo; no process signalled." >&2
    exit 1
fi
kill -TERM "$task_pid"
task_deadline=$((SECONDS + 30))
while kill -0 "$task_pid" 2>/dev/null; do
    if [ -r "/proc/$task_pid/status" ] && grep -q '^State:.*Z' "/proc/$task_pid/status"; then
        break
    fi
    if [ "$SECONDS" -ge "$task_deadline" ]; then
        echo "Timed out waiting for demo cleanup; PID file retained." >&2
        exit 1
    fi
    sleep 0.1
done
rm -f "$PID_FILE"
echo "Stopped demo PID $task_pid after process exit."
