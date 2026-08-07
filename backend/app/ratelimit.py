"""In-process login throttling (per client IP and per account).

Sized for the single-replica deployment in deploy/docker-compose.yml. If the
backend is ever scaled out, move this state to Redis — each replica currently
keeps its own counters, so N replicas allow N times the attempts.

Two independent limits, because they stop different attacks:
  * per IP     — one host spraying many accounts
  * per email  — a botnet spraying one account
"""
import threading
import time
from dataclasses import dataclass, field

from fastapi import Request

from .config import settings


@dataclass
class _Bucket:
    failures: list[float] = field(default_factory=list)
    locked_until: float = 0.0


class LoginThrottle:
    def __init__(
        self,
        max_attempts: int,
        window_seconds: int,
        lockout_seconds: int,
        max_tracked: int = 10_000,
    ) -> None:
        self._max = max_attempts
        self._window = window_seconds
        self._lockout = lockout_seconds
        self._max_tracked = max_tracked
        self._buckets: dict[str, _Bucket] = {}
        self._lock = threading.Lock()

    def retry_after(self, key: str) -> int:
        """Seconds the caller must wait, or 0 if it may proceed."""
        now = time.monotonic()
        with self._lock:
            bucket = self._buckets.get(key)
            if bucket is None:
                return 0
            if bucket.locked_until > now:
                return max(1, int(bucket.locked_until - now))
            return 0

    def record_failure(self, key: str) -> None:
        now = time.monotonic()
        with self._lock:
            self._evict_locked(now)
            bucket = self._buckets.setdefault(key, _Bucket())
            cutoff = now - self._window
            bucket.failures = [t for t in bucket.failures if t > cutoff]
            bucket.failures.append(now)
            if len(bucket.failures) >= self._max:
                # Exponential backoff on repeated lockouts of the same key.
                overflow = len(bucket.failures) - self._max
                factor = min(2**overflow, 8)
                bucket.locked_until = now + self._lockout * factor

    def reset(self, key: str) -> None:
        with self._lock:
            self._buckets.pop(key, None)

    def _evict_locked(self, now: float) -> None:
        """Drop stale buckets so the dict can't grow without bound."""
        if len(self._buckets) < self._max_tracked:
            return
        cutoff = now - self._window
        stale = [
            k
            for k, b in self._buckets.items()
            if b.locked_until <= now and not [t for t in b.failures if t > cutoff]
        ]
        for k in stale:
            del self._buckets[k]
        if len(self._buckets) >= self._max_tracked:
            self._buckets.clear()


ip_throttle = LoginThrottle(
    max_attempts=settings.login_max_attempts_per_ip,
    window_seconds=settings.login_window_seconds,
    lockout_seconds=settings.login_lockout_seconds,
)

email_throttle = LoginThrottle(
    max_attempts=settings.login_max_attempts_per_email,
    window_seconds=settings.login_window_seconds,
    lockout_seconds=settings.login_lockout_seconds,
)


def client_ip(request: Request) -> str:
    """Client address as seen after uvicorn's proxy-header handling.

    uvicorn is run with --proxy-headers --forwarded-allow-ips, so request.client
    is already the real client for requests that came through nginx. Reading
    X-Forwarded-For directly here would let a client spoof its own key.
    """
    return request.client.host if request.client else "unknown"


def reset_all() -> None:
    """Test helper — clears both throttles."""
    ip_throttle._buckets.clear()
    email_throttle._buckets.clear()
