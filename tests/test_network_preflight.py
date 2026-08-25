import socket

import pytest

from pursuitmap.network_preflight import check


def test_network_check_returns_resolved_addresses(monkeypatch):
    monkeypatch.setattr(socket, "getaddrinfo", lambda *args, **kwargs: [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("192.0.2.1", 443))])
    assert check()["addresses"] == ["192.0.2.1"]


def test_network_check_reports_dns_failure(monkeypatch):
    def fail(*args, **kwargs):
        raise socket.gaierror(8, "name or service not known")

    monkeypatch.setattr(socket, "getaddrinfo", fail)
    with pytest.raises(RuntimeError, match="DNS resolution failed"):
        check()
