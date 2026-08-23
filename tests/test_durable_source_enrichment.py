import json
import urllib.error

import duckdb

from pursuitmap import durable_source_enrichment as engine
from pursuitmap import paths


def test_rate_limiter_uses_injected_clock_and_jitter():
    sleeps = []
    now = [0.0]
    limiter = engine.RateLimiter(1.0, 1.0, clock=lambda: now[0], sleeper=sleeps.append, randomizer=lambda: 0.5)
    assert limiter.wait() == 0.5
    assert sleeps == [0.5]
    now[0] = 0.5
    assert limiter.wait() == 1.0
    assert sleeps == [0.5, 1.0]


def test_retry_classification():
    assert engine.classify_status(429, None, (429,))[0] is True
    assert engine.classify_status(404, None, (429,))[0] is False
    assert engine.classify_status(None, TimeoutError(), (429,))[0] is True


def test_detail_batch_reports_uniform_network_failure(monkeypatch, tmp_path):
    connection = duckdb.connect()
    for table, definition in engine.LEDGER_SCHEMA.items():
        connection.execute(f'CREATE TABLE "{table}" ({definition})')
    connection.execute("CREATE SEQUENCE event_seq START 1")
    connection.execute("CREATE SEQUENCE response_seq START 1")
    connection.execute("CREATE SEQUENCE mapping_seq START 1")
    cache = duckdb.connect()
    for table, definition in engine.CACHE_SCHEMA.items():
        cache.execute(f'CREATE TABLE "{table}" ({definition})')
    for external_id in ("1", "2"):
        engine._insert_job(connection, "run", "detail", "/api/tender/{id}", f"https://example.test/{external_id}", {}, f"ocid-{external_id}", external_id)

    def fail_fetch(url, params, timeout):
        raise urllib.error.URLError("dns unavailable")

    monkeypatch.setattr(engine, "_fetch", fail_fetch)
    jobs = connection.execute("SELECT * FROM request_jobs ORDER BY external_id").fetchall()
    config = engine.EngineConfig("test", "1", "1", ("/list",), "/api/tender/{id}", retry_statuses=(408, 429))
    network_errors = engine._process_detail_batch(connection, cache, jobs, "run", config, engine.RateLimiter(100, 0, sleeper=lambda _: None), tmp_path, lambda: 0.0, lambda _: None, 2)
    assert network_errors == 2
    assert connection.execute("SELECT count(*) FROM request_jobs WHERE status = 'retryable_failed'").fetchone()[0] == 2


def test_resume_recovers_operator_interrupted_list_job():
    connection = duckdb.connect()
    connection.execute(f'CREATE TABLE request_jobs ({engine.LEDGER_SCHEMA["request_jobs"]})')
    engine._insert_job(connection, "run", "list", "/api/list", "https://example.test/list", {"page": 3})
    connection.execute("UPDATE request_jobs SET status = 'permanent_failed', error_class = 'RuntimeError', error_message = 'Query interrupted'")
    assert engine._recover_interrupted_jobs(connection, "run") == 1
    assert connection.execute("SELECT status, error_class FROM request_jobs").fetchone() == ("pending", None)
    connection.execute("UPDATE request_jobs SET status = 'running'")
    assert engine._recover_interrupted_jobs(connection, "run") == 1
    assert connection.execute("SELECT status FROM request_jobs").fetchone()[0] == "pending"


def test_plan_run_materialize_with_fake_ppip(monkeypatch, tmp_path):
    monkeypatch.setattr(paths, "DATA_ROOT", tmp_path / "data")
    roots = paths.country_paths("ke")
    paths.ensure_data_dirs("ke")
    raw = roots.raw / "ocds_full.jsonl.gz"
    raw.write_bytes(b"fixture")
    (roots.raw / "manifest.json").write_text(json.dumps({"sha256": "fixture-sha"}), encoding="utf-8")
    canonical = roots.parquet / "fixture"
    canonical.mkdir()
    connection = duckdb.connect()
    connection.execute("COPY (SELECT 'ocds-5whusi-123-ABC' AS ocid, 'release-1' AS release_id) TO ? (FORMAT PARQUET)", [str(canonical / "tenders.parquet")])
    connection.execute("COPY (SELECT 'ocds-5whusi-123-ABC' AS ocid, '2025-01-01' AS release_date) TO ? (FORMAT PARQUET)", [str(canonical / "releases.parquet")])
    connection.close()
    (roots.working / "normalization_manifest.json").write_text(json.dumps({"parquet_root": str(canonical)}), encoding="utf-8")

    planned = engine.plan("ke", limit=25)
    list_payload = json.dumps({"data": [{"id": 123, "ocid": "ocds-5whusi-123-ABC", "tender_ref": "ABC"}, {"id": 999, "ocid": "ocds-5whusi-999-NO", "tender_ref": "NO"}], "current_page": 1, "last_page": 2, "next_page_url": "https://example.test/page/2"}).encode()
    list_payload_page_2 = json.dumps({"data": [{"id": 123, "ocid": "ocds-5whusi-123-ABC", "tender_ref": "ABC"}, {"id": 999, "ocid": "ocds-5whusi-999-NO", "tender_ref": "NO"}], "current_page": 2, "last_page": 2}).encode()
    detail_payload = json.dumps({"ocid": "ocds-5whusi-123-ABC", "tender_ref": "ABC", "title": "Network", "pe": {"id": 1, "name": "Buyer", "pin": "P1"}, "procurement_method": {"title": "Open", "code": "open"}, "procurement_category": {"title": "Goods", "code": "goods"}, "financial_year": {"name": "2025/2026"}, "documents": []}).encode()

    call_kinds = []

    def fake_fetch(url, params, timeout):
        if "/api/active-tenders" in url or "/api/closed-tenders" in url:
            call_kinds.append("list")
            return (200, {"Content-Type": "application/json"}, list_payload if params["page"] == 1 else list_payload_page_2)
        call_kinds.append("detail")
        return (200, {"Content-Type": "application/json"}, detail_payload)

    monkeypatch.setattr(engine, "_fetch", fake_fetch)
    result = engine.execute(planned["run_id"], country="ke", sleep=lambda _: None, randomizer=lambda: 0.0, workers=2)
    assert result["accepted_detail_rows"] == 1
    assert result["mapping_counts"] == {"true": 1, "false": 1}
    assert result["detail_match_rate"] == 1.0
    assert result["job_counts"]["permanent_failed"] == 0
    assert (roots.enriched / planned["run_id"] / "source_enrichment.parquet").exists()
    assert call_kinds.index("detail") > max(index for index, kind in enumerate(call_kinds) if kind == "list")
    progress = engine.status(planned["run_id"], country="ke")
    assert progress["phase"] == "complete"
    assert progress["accepted_detail_rows"] == 1
    eligibility = duckdb.connect().execute("SELECT state, count(*) FROM read_parquet(?) GROUP BY 1", [str(roots.enriched / planned["run_id"] / "enrichment_eligibility.parquet")]).fetchall()
    assert dict(eligibility) == {"source_only": 1, "validated_detail": 1}


def test_reuses_validated_responses_across_runs(monkeypatch, tmp_path):
    monkeypatch.setattr(paths, "DATA_ROOT", tmp_path / "data")
    roots = paths.country_paths("ke")
    paths.ensure_data_dirs("ke")
    raw = roots.raw / "ocds_full.jsonl.gz"
    raw.write_bytes(b"fixture")
    manifest = roots.raw / "manifest.json"
    manifest.write_text(json.dumps({"sha256": "fixture-sha-1"}), encoding="utf-8")
    canonical = roots.parquet / "fixture"
    canonical.mkdir()
    connection = duckdb.connect()
    connection.execute("COPY (SELECT 'ocds-5whusi-123-ABC' AS ocid, 'release-1' AS release_id) TO ? (FORMAT PARQUET)", [str(canonical / "tenders.parquet")])
    connection.execute("COPY (SELECT 'ocds-5whusi-123-ABC' AS ocid, '2025-01-01' AS release_date) TO ? (FORMAT PARQUET)", [str(canonical / "releases.parquet")])
    connection.close()
    (roots.working / "normalization_manifest.json").write_text(json.dumps({"parquet_root": str(canonical)}), encoding="utf-8")
    list_payload = json.dumps({"data": [{"id": 123, "ocid": "ocds-5whusi-123-ABC", "tender_ref": "ABC"}], "current_page": 1, "last_page": 1}).encode()
    detail_payload = json.dumps({"ocid": "ocds-5whusi-123-ABC", "tender_ref": "ABC", "title": "Network", "pe": {"id": 1, "name": "Buyer", "pin": "P1"}, "procurement_method": {"title": "Open", "code": "open"}, "procurement_category": {"title": "Goods", "code": "goods"}, "financial_year": {"name": "2025/2026"}, "documents": []}).encode()
    calls = []

    def fake_fetch(url, params, timeout):
        calls.append(url)
        return (200, {"Content-Type": "application/json"}, list_payload if "/api/active-tenders" in url or "/api/closed-tenders" in url else detail_payload)

    monkeypatch.setattr(engine, "_fetch", fake_fetch)
    first = engine.plan("ke", limit=25)
    first_result = engine.execute(first["run_id"], country="ke", sleep=lambda _: None, randomizer=lambda: 0.0)
    assert first_result["network_requests"] == 3
    manifest.write_text(json.dumps({"sha256": "fixture-sha-2"}), encoding="utf-8")
    second = engine.plan("ke", limit=25)
    second_result = engine.execute(second["run_id"], country="ke", sleep=lambda _: None, randomizer=lambda: 0.0)
    assert second_result["cache_hits"] == 3
    assert second_result["network_requests"] == 0
    assert len(calls) == 3
    assert second_result["accepted_detail_rows"] == 1
