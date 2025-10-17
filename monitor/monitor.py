#!/usr/bin/env python3
"""Watch Pi-hole configuration files and trigger sync commands on changes.

This is a Python replacement for the original shell-based monitor. It watches a
directory for modifications, debounces rapid event bursts, runs
``pi_hole_config_hash.py`` to detect configuration changes, and executes an
optional follow-up command when changes are detected.
"""

from __future__ import annotations

import logging
import os
import queue
import re
import signal
import subprocess
import sys
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Iterable

from watchdog.events import FileSystemEvent, FileSystemEventHandler
from watchdog.observers import Observer

import pi_hole_config_hash

ALLOWED_EVENT_TYPES = {"modified", "created", "moved", "closed"}
# DEBUG, INFO, WARNING, ERROR, CRITICAL
LOG_LEVEL = logging.INFO

# Configure logging
logging.basicConfig(
    level=LOG_LEVEL, # Minimum level to log
    format='%(asctime)s [%(levelname)s] %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S',
)
logging.Formatter.converter = time.localtime
logging.getLogger("watchdog").setLevel(logging.WARNING)


@dataclass(slots=True)
class Settings:
    """Runtime configuration populated from environment variables."""
    watch_dir: Path
    include_pattern: str | None
    exclude_pattern: str | None
    debounce_time: float
    onchange_cmd: str | None


def read_settings() -> Settings:
    """Load runtime settings from environment variables."""
    try:
        watch_dir = Path(os.environ["WATCH_DIR"]).resolve()
    except KeyError as exc:
        raise RuntimeError("WATCH_DIR environment variable is required") from exc

    include = os.environ.get("WATCH_INCLUDE") or None
    exclude = os.environ.get("WATCH_EXCLUDE") or None

    debounce_time = float(os.environ.get("DEBOUNCE_TIME", "3"))
    onchange_cmd = os.environ.get("ONCHANGE_CMD") or None

    if not watch_dir.exists():
        raise RuntimeError(f"Watch directory does not exist: {watch_dir}")

    return Settings(
        watch_dir=watch_dir,
        include_pattern=include,
        exclude_pattern=exclude,
        debounce_time=debounce_time,
        onchange_cmd=onchange_cmd,
    )


class DebounceWorker(threading.Thread):
    """Process filesystem events with debounce behaviour."""

    def __init__(
        self,
        debounce_time: float,
        callback: Callable[[], None],
    ) -> None:
        super().__init__(daemon=True)
        self._debounce_time = debounce_time
        self._callback = callback
        self._events: "queue.Queue[float]" = queue.Queue()
        self._stop_requested = threading.Event()

    def notify(self) -> None:
        """Signal that a new filesystem event has occurred."""
        try:
            self._events.put_nowait(time.time())
            logging.debug("DebounceWorker notified.")
        except queue.Full:
            # Queue is unbounded by default; this is defensive and shouldn't occur.
            pass

    def stop(self) -> None:
        """Request worker shutdown."""
        self._stop_requested.set()
        # Push a sentinel event to unblock queue.get
        self.notify()

    def run(self) -> None:
        """Main loop: wait for calm period, then invoke callback."""
        while not self._stop_requested.is_set():
            try:
                while True:
                    event_time = self._events.get(timeout=0.1)
                    # Drain any remaining events immediately so queue stays empty
                    while True:
                        try:
                            event_time = self._events.get_nowait()
                        except queue.Empty:
                            break

                    if self._stop_requested.is_set():
                        return

                    deadline = time.time() + self._debounce_time
                    while time.time() < deadline:
                        remaining = deadline - time.time()
                        try:
                            event_time = self._events.get(timeout=remaining)
                            deadline = time.time() + self._debounce_time
                        except queue.Empty:
                            logging.debug("DebounceWorker debounce window elapsed.")
                            if self._stop_requested.is_set():
                                return
                            logging.debug("DebounceWorker invoking callback.")
                            self._callback()
                            break
            except queue.Empty:
                continue



class ChangeHandler(FileSystemEventHandler):
    """Convert watchdog events into debounced notifications."""

    def __init__(
        self, notify: Callable[[], None], include: str | None, exclude: str | None
    ) -> None:
        super().__init__()
        self._notify = notify
        self._include_regex = re.compile(include) if include else None
        self._exclude_regex = re.compile(exclude) if exclude else None
        self._snapshots: dict[str, tuple[int, int]] = {}

    def on_any_event(self, event: FileSystemEvent) -> None:
        if event.event_type not in ALLOWED_EVENT_TYPES:
            return

        if event.is_directory:
            return

        if event.event_type == "closed" and not getattr(event, "is_write", False):
            return

        path = event.src_path

        if self._include_regex and not self._include_regex.search(path):
            return

        if self._exclude_regex and self._exclude_regex.search(path):
            return

        if not self._has_real_change(path):
            logging.debug(f"Skipping {path}; metadata unchanged.")
            return

        logging.debug(f"File changed {event.event_type} {event.src_path}")

        self._notify()

    def _has_real_change(self, path: str) -> bool:
        """Return True when stat info indicates an actual content change."""
        try:
            stat_result = os.stat(path)
        except FileNotFoundError:
            self._snapshots.pop(path, None)
            return True

        current = (int(stat_result.st_mtime_ns), int(stat_result.st_size))
        previous = self._snapshots.get(path)
        if previous == current:
            return False

        self._snapshots[path] = current
        return True


class Monitor:
    """Main application controller."""

    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self._worker = DebounceWorker(
            settings.debounce_time, self._sync_configs
        )

        self._observer = Observer()
        self._shutdown = threading.Event()

    def start(self) -> None:
        """Start the filesystem observer and debounce worker."""
        logging.info(f"Watching {self.settings.watch_dir}")
        self._worker.start()
        handler = ChangeHandler(
            self._worker.notify,
            self.settings.include_pattern,
            self.settings.exclude_pattern,
        )
        observed = self._observer.schedule(
            handler,
            str(self.settings.watch_dir),
            recursive=True,
        )

        self._observer.start()

    def stop(self) -> None:
        """Gracefully stop watcher threads."""
        if self._shutdown.is_set():
            return
        self._shutdown.set()
        logging.info("Shutting down.")
        self._observer.stop()
        self._worker.stop()
        self._observer.join()
        self._worker.join()

    def _sync_configs(self) -> None:
        """Invoke the hash script and execute the change command if required."""
        logging.info("Debounced change detected; running hash check.")
        result = self._run_hash_check()
        status = getattr(result, "status", 3)
        summary_hash = getattr(result, "summary_hash", None)

        if summary_hash:
            logging.info(f"Current config hash: {summary_hash}")

        if status == 1:
            logging.info("Configuration change detected.")
            self._run_onchange_command()
        elif status == 0:
            logging.info("Configuration unchanged. Skipping sync.")
        else:
            logging.info(f"Hash check returned {status}; skipping sync.")

    def _run_hash_check(self):
        """Invoke the hash checker within the current process."""
        try:
            result = pi_hole_config_hash.run_hash_check()
        except Exception as exc:  # pragma: no cover - defensive
            message = f"Hash check raised an unexpected error: {exc}"
            logging.error(message)
            return pi_hole_config_hash.HashCheckResult(
                status=3,
                summary_hash=None,
                previous_hash=None,
                message=message,
                error=True,
            )

        message = getattr(result, "message", "")
        logging.info(message)

        return result

    def _run_onchange_command(self) -> None:
        """Execute the configured on-change command and apply the cooldown delay."""
        if not self.settings.onchange_cmd:
            logging.info("No ONCHANGE_CMD configured; skipping.")
            return

        logging.info(f"Executing: {self.settings.onchange_cmd}")
        try:
            subprocess.run(
                self.settings.onchange_cmd,
                shell=True,
                check=False,
            )
        except OSError as exc:
            logging.error(f"Failed to run ONCHANGE_CMD: {exc}")


def main() -> int:
    try:
        settings = read_settings()
    except Exception as exc:
        logging.error(exc)
        return 2

    monitor = Monitor(settings)

    def handle_signal(signum: int, _frame: object) -> None:
        logging.info(f"Received signal {signum}.")
        monitor.stop()

    for sig in (signal.SIGINT, signal.SIGTERM):
        signal.signal(sig, handle_signal)

    monitor.start()

    try:
        while not monitor._shutdown.is_set():
            time.sleep(1)
    except KeyboardInterrupt:
        logging.info("Keyboard interrupt received.")
        monitor.stop()

    return 0


if __name__ == "__main__":
    sys.exit(main())
