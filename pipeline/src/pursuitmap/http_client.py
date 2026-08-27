"""Deterministic, source-agnostic HTTP primitives for durable request runners."""

from __future__ import annotations

import random
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from datetime import UTC, datetime
from email.utils import parsedate_to_datetime
from threading import Lock
from typing import Callable


RETRY_STATUSES = frozenset({408, 425, 429, 500, 502, 503, 504})


@dataclass(frozen=True)
class HttpPolicy:
    rate_per_second: float = 1.0
    jitter_seconds: float = 1.0
    timeout_seconds: float = 30.0
    max_attempts: int = 6
    max_backoff_seconds: float = 600.0
    circuit_429_threshold: int = 3
    circuit_pause_seconds: float = 60.0
    retry_statuses: frozenset[int] = RETRY_STATUSES


@dataclass(frozen=True)
class HttpResult:
    status: int | None
    headers: dict[str, str]
    body: bytes
    attempts: int
    wait_seconds: float
    error_class: str | None = None
    error_message: str | None = None


def parse_retry_after(value: str | None, *, now: datetime | None = None) -> float | None:
    if not value:
        return None
    try:
        return max(0.0, float(value))
    except (TypeError, ValueError):
        try:
            retry_at = parsedate_to_datetime(value)
        except (TypeError, ValueError, OverflowError):
            return None
        if retry_at.tzinfo is None:
            retry_at = retry_at.replace(tzinfo=UTC)
        return max(0.0, (retry_at - (now or datetime.now(UTC))).total_seconds())


def classify(status: int | None, error: Exception | None, retry_statuses: frozenset[int] = RETRY_STATUSES) -> tuple[bool, str]:
    if status in retry_statuses:
        return True, f"http_{status}"
    if status is not None:
        return False, f"http_{status}"
    if isinstance(error, (TimeoutError, urllib.error.URLError, ConnectionError)):
        return True, error.__class__.__name__
    return False, error.__class__.__name__ if error else "unknown"


class RateLimiter:
    def __init__(self, rate_per_second: float, jitter_seconds: float = 0.0, *, clock: Callable[[], float] = time.monotonic, sleeper: Callable[[float], None] = time.sleep, randomizer: Callable[[], float] = random.random) -> None:
        if rate_per_second <= 0:
            raise ValueError("rate_per_second must be greater than zero")
        self.base_interval = 1.0 / rate_per_second
        self.interval = self.base_interval
        self.jitter_seconds = jitter_seconds
        self.clock = clock
        self.sleeper = sleeper
        self.randomizer = randomizer
        self.next_at = 0.0
        self.consecutive_429 = 0
        self._lock = Lock()

    def wait(self, extra_seconds: float = 0.0) -> float:
        with self._lock:
            now = self.clock()
            target = max(now, self.next_at) + extra_seconds + self.randomizer() * self.jitter_seconds
            self.next_at = target + self.interval
        delay = max(0.0, target - now)
        if delay:
            self.sleeper(delay)
        return delay

    def observe(self, status: int | None) -> None:
        with self._lock:
            if status == 429:
                self.consecutive_429 += 1
                self.interval = min(60.0, self.interval * 2.0)
            elif status is not None and 200 <= status < 400:
                self.consecutive_429 = 0
                self.interval = max(self.base_interval, self.interval * 0.5)

    def circuit_open(self, threshold: int) -> bool:
        with self._lock:
            return self.consecutive_429 >= threshold


class HttpClient:
    def __init__(self, policy: HttpPolicy, *, opener=None, clock: Callable[[], float] = time.monotonic, sleeper: Callable[[float], None] = time.sleep, randomizer: Callable[[], float] = random.random) -> None:
        self.policy = policy
        self.opener = opener or urllib.request.build_opener()
        self.clock = clock
        self.sleeper = sleeper
        self.limiter = RateLimiter(policy.rate_per_second, policy.jitter_seconds, clock=clock, sleeper=sleeper, randomizer=randomizer)

    def request(self, url: str, *, params: dict | None = None, headers: dict[str, str] | None = None) -> HttpResult:
        request_url = url + ("?" + urllib.parse.urlencode(params) if params else "")
        total_wait = 0.0
        last_status = None
        for attempt in range(1, self.policy.max_attempts + 1):
            if self.limiter.circuit_open(self.policy.circuit_429_threshold):
                pause = self.policy.circuit_pause_seconds
                total_wait += pause
                self.sleeper(pause)
                self.limiter.consecutive_429 = 0
            total_wait += self.limiter.wait()
            request = urllib.request.Request(request_url, headers=headers or {"Accept": "application/json"})
            try:
                with self.opener.open(request, timeout=self.policy.timeout_seconds) as response:
                    result = HttpResult(response.status, dict(response.headers), response.read(), attempt, total_wait)
            except urllib.error.HTTPError as error:
                result = HttpResult(error.code, dict(error.headers), error.read(), attempt, total_wait)
            except Exception as error:
                retryable, error_class = classify(None, error, self.policy.retry_statuses)
                if not retryable or attempt >= self.policy.max_attempts:
                    return HttpResult(None, {}, b"", attempt, total_wait, error_class, str(error))
                delay = min(self.policy.max_backoff_seconds, 2**attempt)
                total_wait += delay + self.limiter.randomizer() * self.policy.jitter_seconds
                self.sleeper(delay)
                continue
            last_status = result.status
            self.limiter.observe(result.status)
            retryable, error_class = classify(result.status, None, self.policy.retry_statuses)
            if not retryable or attempt >= self.policy.max_attempts:
                return result if result.error_class else HttpResult(result.status, result.headers, result.body, attempt, total_wait, None if result.status and 200 <= result.status < 400 else error_class, None)
            retry_after = parse_retry_after(result.headers.get("Retry-After"))
            delay = min(self.policy.max_backoff_seconds, retry_after if retry_after is not None else 2**attempt)
            total_wait += delay
            self.sleeper(delay)
        return HttpResult(last_status, {}, b"", self.policy.max_attempts, total_wait, "exhausted", "retry attempts exhausted")
