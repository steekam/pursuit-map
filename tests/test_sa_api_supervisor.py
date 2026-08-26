from __future__ import annotations

import json

import duckdb

from pursuitmap.sa_api_supervisor import _classify, _job_id, _setup


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
    connection.close()
