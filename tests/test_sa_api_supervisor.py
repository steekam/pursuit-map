from __future__ import annotations

import json

import duckdb

from pursuitmap.http_client import HttpResult
from pursuitmap.sa_api_supervisor import CAPACITY_LEVELS, _classify, _fetch_job, _job_id, _setup


def test_job_id_is_deterministic_and_scoped():
    assert _job_id("run", "exact_ocid", "ocds-1") == _job_id("run", "exact_ocid", "ocds-1")
    assert _job_id("run", "exact_ocid", "ocds-1") != _job_id("other", "exact_ocid", "ocds-1")


def test_error_classification_retries_transient_http_errors():
    assert _classify(None, 429, 1) == ("retryable_failed", True, "http_429")
    assert _classify(None, 404, 1) == ("permanent_failed", False, "http_404")
    assert _classify(None, 500, 6) == ("permanent_failed", False, "http_500")


def test_supervisor_ledger_has_required_tables(tmp_path):
    connection = duckdb.connect(str(tmp_path / "ledger.duckdb"))
    _setup(connection)
    tables = {row[0] for row in connection.execute("SHOW TABLES").fetchall()}
    assert tables == {
        "supervisor_capacity_tests",
        "supervisor_events",
        "supervisor_jobs",
        "supervisor_matches",
        "supervisor_probe_results",
    }
    columns = {row[0] for row in connection.execute("DESCRIBE supervisor_events").fetchall()}
    assert {"elapsed_seconds", "transport_attempts"}.issubset(columns)
    connection.close()


def test_fetch_job_uses_shared_http_result_and_validates_ocid():
    class Client:
        def request(self, url):
            assert url == "https://example.test/ocds-1"
            return HttpResult(200, {"Content-Type": "application/json"}, b'{"id":"release-1","ocid":"ocds-1","tender":{}}', 2, 3.5)

    result = _fetch_job(("job-1", "ocds-1", "https://example.test/ocds-1", 0), Client())

    assert result["state"] == "succeeded"
    assert result["transport_attempts"] == 2
    assert result["waited"] == 3.5


def test_capacity_probe_includes_controlled_level_eight():
    assert CAPACITY_LEVELS[-1] == 8
