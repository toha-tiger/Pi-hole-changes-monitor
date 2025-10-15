#!/bin/sh
set -eu

DEBOUNCE_PID=''
INOTIFY_PID=''
PARENT=$$

finish() {
  trap - INT TERM EXIT

  echo "[monitor.sh] Exiting."
  kill $DEBOUNCE_PID 2>/dev/null || true
  pkill -P "$INOTIFY_PID" inotifywait 2>/dev/null || true
  kill $INOTIFY_PID 2>/dev/null || true

  exit 0
}

debounce() {
    DELAY="$1"; shift
    CMD="$*"

    # Kill existing pending timer (reset)
    [ -n "$DEBOUNCE_PID" ] && kill $DEBOUNCE_PID 2>/dev/null || true

    (
        sleep "$DELAY"
        echo "[monitor.sh] exec: $ONCHANGE_CMD"
        sh -c "$CMD"
    ) &
    DEBOUNCE_PID=$!
}

changes() {
  echo "[monitor.sh] Debounced run: $ONCHANGE_CMD"
  debounce 3 "$ONCHANGE_CMD"
}

trap finish SIGINT INT TERM EXIT
trap changes ALRM

# -----------------------------------------------------------

echo Starting
(
  while FN="$(inotifywait -q -r \
    -e close_write,modify,create,move \
    --format '%w%f' \
    --exclude "$EXCLUDE" \
    $WATCH_DIR
  )"; do
    echo "[monitor.sh] inotify change: $FN"
    # Notify parent when change detected
    kill -s ALRM "$PARENT" 2>/dev/null
  done
) &
INOTIFY_PID=$!

while $( kill -0 "$INOTIFY_PID" 2>/dev/null )
do
  sleep 1
done
echo inotify exited
