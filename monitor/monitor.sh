#!/bin/sh
set -eu

DEBOUNCE_PID=''
INOTIFY_PID=''
PARENT=$$

finish() {
  trap - INT TERM EXIT
  echo "[monitor.sh] Exiting."
  debounce_stop
  inotify_stop
  exit 0
}

debounce() {
  echo "Debounced run: $ONCHANGE_CMD"

  # Kill existing pending timer (reset)
  [ -n "$DEBOUNCE_PID" ] && kill $DEBOUNCE_PID 2>/dev/null || true

  (
      sleep "$DEBOUNCE_TIME"
      echo "[monitor.sh] exec: $ONCHANGE_CMD"

      # inotify_stop
      kill -s USR1 "$PARENT" 2>/dev/null

      sh -c "$ONCHANGE_CMD"

      echo sleeping $ONCHANGE_CMD_TIME seconds
      sleep $ONCHANGE_CMD_TIME

      # inotify_start
      kill -s USR2 "$PARENT" 2>/dev/null
  ) &
  DEBOUNCE_PID=$!
}

debounce_stop() {
  echo debounce stop
  kill $DEBOUNCE_PID 2>/dev/null || true
}

inotify_start() {
  echo Starting inotifywait
  (
    while FN="$(inotifywait -q -r \
      -e close_write,modify,create,move \
      --format '%w%f' \
      --exclude "$EXCLUDE" \
      $WATCH_DIR
    )"; do
      echo "inotify change: $FN"
      # Notify parent when change detected
      kill -s ALRM "$PARENT" 2>/dev/null
    done
  ) &
  INOTIFY_PID=$!
}

inotify_stop() {
  echo inotifywait stop
  pkill -P "$INOTIFY_PID" inotifywait 2>/dev/null || true
  kill $INOTIFY_PID 2>/dev/null || true
}

trap finish SIGINT INT TERM EXIT
trap debounce ALRM
trap inotify_stop USR1
trap inotify_start USR2

# -----------------------------------------------------------

inotify_start

while true
do
  sleep 1
done
