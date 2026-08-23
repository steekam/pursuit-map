import json

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
    connection.close()
    (roots.working / "normalization_manifest.json").write_text(json.dumps({"parquet_root": str(canonical)}), encoding="utf-8")

    planned = engine.plan("ke", limit=25)
    list_payload = json.dumps({"data": [{"id": 123, "ocid": "ocds-5whusi-123-ABC", "tender_ref": "ABC"}, {"id": 999, "ocid": "ocds-5whusi-999-NO", "tender_ref": "NO"}], "current_page": 1, "last_page": 1}).encode()
    detail_payload = json.dumps({"ocid": "ocds-5whusi-123-ABC", "tender_ref": "ABC", "title": "Network", "pe": {"id": 1, "name": "Buyer", "pin": "P1"}, "procurement_method": {"title": "Open", "code": "open"}, "procurement_category": {"title": "Goods", "code": "goods"}, "financial_year": {"name": "2025/2026"}, "documents": []}).encode()

    def fake_fetch(url, params, timeout):
        return (200, {"Content-Type": "application/json"}, list_payload if "/api/active-tenders" in url or "/api/closed-tenders" in url else detail_payload)

    monkeypatch.setattr(engine, "_fetch", fake_fetch)
    result = engine.execute(planned["run_id"], country="ke", sleep=lambda _: None, randomizer=lambda: 0.0)
    assert result["accepted_detail_rows"] == 1
    assert result["mapping_counts"] == {"true": 1, "false": 1}
    assert result["detail_match_rate"] == 1.0
    assert result["job_counts"]["permanent_failed"] == 0
    assert (roots.enriched / planned["run_id"] / "source_enrichment.parquet").exists()


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
