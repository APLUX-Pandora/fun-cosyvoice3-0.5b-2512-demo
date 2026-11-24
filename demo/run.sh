#!/bin/bash
# Start this deployment with its own venv. Default: https://<board-ip>:8766.
set -eu
D="$(cd "$(dirname "$0")" && pwd)"
ROOT="$(dirname "$D")"
task_port="${PORT:-8766}"
if [ "$#" -ne 0 ]; then
    if [ "$#" -ne 2 ] || [ "$1" != "--port" ]; then
        echo "Usage: bash demo/run.sh [--port PORT]" >&2
        exit 2
    fi
    task_port="$2"
fi
case "$task_port" in ""|*[!0-9]*) echo "PORT must be an integer 1..65535" >&2; exit 1 ;; esac
if [ "${#task_port}" -gt 5 ] || [ "$task_port" -lt 1 ] || [ "$task_port" -gt 65535 ]; then
    echo "PORT must be an integer 1..65535" >&2; exit 1
fi
VENV="${CV3_VENV:-$ROOT/.venv}"
if [ ! -f "$VENV/pyvenv.cfg" ] || [ ! -f "$VENV/bin/activate" ]; then
    echo "Missing isolated demo environment: $VENV." >&2
    echo "From the Demo root ($ROOT), create and activate that environment, then run python -m pip install -r requirements.txt." >&2
    echo "For SDK-only installation, see sdk/README.md." >&2
    exit 1
fi
# Activation is local to this launcher and inherited by the background child.
source "$VENV/bin/activate"
python -c 'import sys; from pathlib import Path; assert sys.prefix != sys.base_prefix and Path(sys.prefix).resolve() == Path(sys.argv[1]).resolve(), "Demo requires the selected isolated venv"' "$VENV"
if [ -f "$D/web.pid" ]; then
    read -r task_pid < "$D/web.pid"
    case "$task_pid" in ""|*[!0-9]*) echo "Invalid existing PID file; no service started." >&2; exit 1 ;; esac
    if [ "$task_pid" -le 1 ]; then echo "Invalid existing PID; no service started." >&2; exit 1; fi
    if kill -0 "$task_pid" 2>/dev/null; then
        if ! tr '\0' '\n' < "/proc/$task_pid/cmdline" | grep -Fxq "$D/app.py"; then
            echo "Recorded PID belongs to another process; no service started." >&2; exit 1
        fi
        echo "Already running this deployment, pid $task_pid"; exit 0
    fi
fi
task_port=$((10#$task_port))
task_protocol=https
task_args=(--port "$task_port")
if [ "${CV3_HTTP:-0}" = 1 ]; then
    task_protocol=http
    task_args+=(--http --host 127.0.0.1)
fi

task_log="$D/web.log"
: >> "$task_log"
task_log_start=$(($(wc -c < "$task_log") + 1))
setsid --fork --wait bash -c 'echo "$$" > "$1/web.pid"; exec python "$1/app.py" "${@:2}"' \
    bash "$D" "${task_args[@]}" < /dev/null >> "$task_log" 2>&1 &
task_launcher=$!
task_deadline=$((SECONDS + 60))
while kill -0 "$task_launcher" 2>/dev/null; do
    # The app logs this after loading the model and binding the listener.
    if tail -c "+$task_log_start" "$task_log" | grep -Fx "{\"$task_protocol\": $task_port}" > /dev/null; then
        echo "Started pid $(cat "$D/web.pid"), log $task_log"
        exit 0
    fi
    if [ "$SECONDS" -ge "$task_deadline" ]; then
        echo "Demo is still starting after 60 seconds. See $task_log." >&2
        exit 1
    fi
    sleep 0.2
done
echo "Demo exited before it was ready. See $task_log." >&2
exit 1
