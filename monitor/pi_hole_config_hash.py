#!/usr/bin/env python3
"""Generate a stable hash for Pi-hole configuration endpoints.

This module can be executed as a script or imported. When imported,
``run_hash_check`` can be used to perform the hash comparison without spawning
an external process.
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Iterable, Tuple

import requests
from requests import Response, Session

# Configure logging
logging.basicConfig(
    level=logging.INFO, # Minimum level to log
    format='%(asctime)s [%(levelname)s] %(message)s'
)

PIHOLE_HASH_PATH = Path("/tmp/pi_hole_config_hash/config.md5")
PIHOLE_SID_CACHE_PATH = Path("/tmp/pi_hole_config_hash/sid.json")
PIHOLE_LOGIN_ENDPOINT = "/api/auth"
PIHOLE_HASH_FIRST_RUN_EXIT = 1
PIHOLE_API_URL = os.environ.get("PIHOLE_API_URL")
PIHOLE_PASSWORD = os.environ.get("PIHOLE_PASSWORD")

DEFAULT_ENDPOINTS = (
    "/api/config",
    "/api/dhcp/leases",
    "/api/groups",
    "/api/lists",
    "/api/domains",
    "/api/clients",
)


class ApiError(RuntimeError):
    """API related errors."""


@dataclass(slots=True)
class HashCheckResult:
    """Structured result from a hash comparison run."""

    status: int
    summary_hash: str | None
    previous_hash: str | None
    message: str
    error: bool = False


def urljoin(base: str, endpoint: str) -> str:
    """Join base URL and endpoint path safely."""
    return f"{base.rstrip('/')}/{endpoint.lstrip('/')}"


def login(
    session: Session, base_url: str, password: str, login_endpoint: str
) -> Tuple[str, float]:
    """Authenticate against the Pi-hole API and return the session id and validity."""
    login_url = urljoin(base_url, login_endpoint)
    try:
        response = session.post(
            login_url,
            json={"password": password},
            timeout=10,
        )
    except requests.RequestException as exc:
        raise ApiError(f"Login request failed: {exc}") from exc

    sid, validity = parse_login_response(response)
    session.headers["X-FTL-SID"] = sid
    return sid, validity


def parse_login_response(response: Response) -> Tuple[str, float]:
    """Extract the session identifier and validity window from a login response."""
    try:
        response.raise_for_status()
    except requests.HTTPError as exc:
        raise ApiError(f"Login failed with status {response.status_code}") from exc

    try:
        payload = response.json()
    except ValueError as exc:
        raise ApiError("Login response is not valid JSON") from exc

    session_data = payload.get("session")
    if not isinstance(session_data, dict):
        raise ApiError("Login response does not contain 'session' information")

    sid = session_data.get("sid")
    validity = session_data.get("validity")

    if not isinstance(sid, str) or not sid:
        raise ApiError("Login response does not contain a valid 'sid'")

    try:
        validity_value = float(validity)
    except (TypeError, ValueError) as exc:
        raise ApiError(
            "Login response does not contain a valid 'validity' value"
        ) from exc

    return sid, validity_value


def strip_took_field(data: Any) -> Any:
    """Recursively remove any 'took' fields from dictionaries."""
    if isinstance(data, dict):
        return {
            key: strip_took_field(value)
            for key, value in data.items()
            if key != "took"
        }
    if isinstance(data, list):
        return [strip_took_field(item) for item in data]
    return data


def fetch_endpoint(session: Session, base_url: str, endpoint: str) -> Dict[str, Any]:
    """Fetch and normalize data from a given API endpoint."""
    url = urljoin(base_url, endpoint)
    try:
        response = session.get(url, timeout=10)
        response.raise_for_status()
    except requests.RequestException as exc:
        raise ApiError(f"Failed to fetch {endpoint}: {exc}") from exc

    try:
        data = response.json()
    except ValueError as exc:
        raise ApiError(f"Response from {endpoint} is not valid JSON") from exc

    return strip_took_field(data)


def digest_payload(payload: Any) -> str:
    """Calculate an MD5 hash for the provided JSON-serializable payload."""
    normalized = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    return hashlib.md5(normalized.encode("utf-8")).hexdigest()


def combine_hashes(hashes: Iterable[str]) -> str:
    """Calculate the MD5 of the concatenated individual hashes."""
    combined = "".join(hashes)
    return hashlib.md5(combined.encode("ascii")).hexdigest()


def read_previous_hash(path: Path) -> str | None:
    """Read the previously stored summary hash."""
    try:
        return path.read_text(encoding="ascii").strip()
    except FileNotFoundError:
        return None


def write_hash(path: Path, value: str) -> None:
    """Persist the summary hash for future runs."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(f"{value}\n", encoding="ascii")


def load_cached_sid(path: Path) -> str | None:
    """Load a cached SID if available and not expired."""
    try:
        raw = path.read_text(encoding="utf-8")
        payload = json.loads(raw)
    except FileNotFoundError:
        return None
    except json.JSONDecodeError:
        return None

    sid = payload.get("sid")
    expires = payload.get("expires")

    if not isinstance(sid, str) or not sid:
        return None

    try:
        expires_ts = float(expires)
    except (TypeError, ValueError):
        return None

    if expires_ts <= time.time():
        return None

    return sid


def cache_sid(path: Path, sid: str, validity: float) -> None:
    """Store session identifier with an expiry buffer."""
    now = time.time()
    adjusted_expires = now + max(validity - 5, 0)
    payload = {
        "sid": sid,
        "expires": f"{adjusted_expires:.0f}",
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload) + "\n", encoding="utf-8")


def run_hash_check() -> HashCheckResult:
    """Execute the hash comparison and return a structured result."""
    hash_file = PIHOLE_HASH_PATH
    sid_cache_file = PIHOLE_SID_CACHE_PATH
    login_endpoint = PIHOLE_LOGIN_ENDPOINT
    first_run_exit = PIHOLE_HASH_FIRST_RUN_EXIT
    base_url = PIHOLE_API_URL
    password = PIHOLE_PASSWORD

    session = requests.Session()

    try:
        cached_sid = load_cached_sid(sid_cache_file)
        if cached_sid:
            session.headers["X-FTL-SID"] = cached_sid
        else:
            sid, validity = login(session, base_url, password, login_endpoint)
            cache_sid(sid_cache_file, sid, validity)

        if "X-FTL-SID" not in session.headers:
            raise ApiError("Missing session identifier for API requests")

        endpoint_hashes = [
            digest_payload(fetch_endpoint(session, base_url, endpoint))
            for endpoint in DEFAULT_ENDPOINTS
        ]
        summary_hash = combine_hashes(endpoint_hashes)
    except ApiError as exc:
        return HashCheckResult(
            status=3,
            summary_hash=None,
            previous_hash=None,
            message=str(exc),
            error=True,
        )

    previous_hash = read_previous_hash(hash_file)
    write_hash(hash_file, summary_hash)

    if previous_hash is None:
        return HashCheckResult(
            status=first_run_exit,
            summary_hash=summary_hash,
            previous_hash=None,
            message="No previous hash found; stored current summary hash.",
        )

    if summary_hash == previous_hash:
        return HashCheckResult(
            status=0,
            summary_hash=summary_hash,
            previous_hash=previous_hash,
            message="Pi-hole configuration unchanged.",
        )

    return HashCheckResult(
        status=1,
        summary_hash=summary_hash,
        previous_hash=previous_hash,
        message="Pi-hole configuration has changed.",
    )


def main() -> int:
    result = run_hash_check()
    stream = sys.stderr if result.error else sys.stdout
    if result.message:
        print(result.message, file=stream)
    return result.status


if __name__ == "__main__":
    sys.exit(main())

