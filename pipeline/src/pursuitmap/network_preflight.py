from __future__ import annotations

import socket
from urllib.parse import urlsplit


def check(url: str = "https://tenders.go.ke") -> dict:
    parsed = urlsplit(url)
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        raise ValueError("network preflight requires an HTTP or HTTPS URL")
    port = parsed.port or (443 if parsed.scheme == "https" else 80)
    try:
        addresses = sorted({result[4][0] for result in socket.getaddrinfo(parsed.hostname, port, type=socket.SOCK_STREAM)})
    except socket.gaierror as error:
        raise RuntimeError(f"DNS resolution failed for {parsed.hostname}: {error}. Run the command with network-enabled execution.") from error
    return {"url": url, "host": parsed.hostname, "port": port, "addresses": addresses, "status": "pass"}
