from __future__ import annotations

import urllib.error

import pytest

from pursuitmap.http_client import HttpClient, HttpPolicy, RateLimiter, classify, parse_retry_after


def test_parse_retry_after_supports_seconds_and_dates():
    assert parse_retry_after("8") == 8.0
    assert parse_retry_after("invalid") is None


def test_classify_keeps_access_errors_permanent():
    assert classify(404, None)[0] is False
    assert classify(429, None)[0] is True
    assert classify(None, urllib.error.URLError("dns"))[0] is True


def test_rate_limiter_rejects_invalid_rate():
    with pytest.raises(ValueError):
        RateLimiter(0)


def test_http_client_retries_429_and_honors_retry_after(monkeypatch):
    calls = []
    sleeps = []

    class Response:
        status = 200
        headers = {"Content-Type": "application/json"}

        def read(self):
            return b'{"ok":true}'

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

    class Opener:
        def open(self, request, timeout):
            calls.append(request.full_url)
            if len(calls) == 1:
                raise urllib.error.HTTPError(request.full_url, 429, "busy", {"Retry-After": "2"}, None)
            return Response()

    client = HttpClient(HttpPolicy(rate_per_second=100, jitter_seconds=0, max_attempts=2), opener=Opener(), sleeper=sleeps.append, randomizer=lambda: 0)
    result = client.request("https://example.test/api", params={"page": 1})
    assert result.status == 200
    assert len(calls) == 2
    assert 2.0 in sleeps
