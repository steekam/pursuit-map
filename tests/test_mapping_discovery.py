import json

import duckdb

from pursuitmap import mapping_discovery as discovery
from pursuitmap import paths
from pursuitmap.source_enrichment import SCHEMA


def _source_fixture(monkeypatch, tmp_path):
    monkeypatch.setattr(paths, "DATA_ROOT", tmp_path / "data")
    roots = paths.country_paths("ke")
    run_root = roots.enriched / "source-run"
    run_root.mkdir(parents=True)
    canonical = roots.parquet / "canonical"
    canonical.mkdir(parents=True)
    roots.working.mkdir(parents=True)
    (roots.working / "normalization_manifest.json").write_text(json.dumps({"parquet_root": str(canonical)}))
    values = {column: "NULL::VARCHAR" for column in SCHEMA}
    values.update({"source_snapshot_sha256": "'sha'", "ocid": "'ocid-known'", "tender_number": "'T-1'", "title": "'Old tender'", "published_date_raw": "'2025-01-01'"})
    connection = duckdb.connect()
    connection.execute("COPY (SELECT 'ocid-known' AS ocid, '2025-01-01' AS release_date) TO ? (FORMAT PARQUET)", [str(canonical / "releases.parquet")])
    tender_columns = {"ocid": "'ocid-pending'", "release_date": "'2025-01-01'", "period_end": "'2025-06-01'"}
    tender_columns.update({column: "NULL::VARCHAR" for column in ("source_snapshot_sha256", "release_id", "buyer_id", "buyer_name", "tender_id", "title", "description", "status", "procurement_method", "procurement_method_details", "category", "main_procurement_category", "additional_categories_json", "procuring_entity_id", "procuring_entity_name", "enquiry_start_raw", "enquiry_start", "enquiry_start_status", "enquiry_end_raw", "enquiry_end", "enquiry_end_status", "period_start_raw", "period_start", "period_start_status", "period_end_status", "value_amount_raw", "value_amount", "value_currency", "value_status", "raw_json")})
    connection.execute(f"COPY (SELECT {','.join(f'{expression} AS {column}' for column, expression in tender_columns.items())}) TO ? (FORMAT PARQUET)", [str(canonical / "tenders.parquet")])
    connection.execute("COPY (SELECT 'sha' AS source_snapshot_sha256, 'ocid-pending' AS ocid, 'mapping_pending' AS state) TO ? (FORMAT PARQUET)", [str(run_root / "enrichment_eligibility.parquet")])
    connection.execute(f"COPY (SELECT {','.join(f'{expression} AS {column}' for column, expression in values.items())}) TO ? (FORMAT PARQUET)", [str(run_root / "source_enrichment.parquet")])
    connection.close()
    (roots.raw).mkdir(parents=True)
    (roots.raw / "ocds_full.jsonl.gz").write_bytes(b"raw")
    (roots.raw / "manifest.json").write_text(json.dumps({"sha256": "sha"}))
    return roots


def test_extract_records_supports_known_shapes():
    assert discovery._extract_records(b'{"data":[{"id":1,"ocid":"o"}]}')[0][0]["id"] == 1
    assert discovery._extract_records(b'{"results":[{"id":2,"ocid":"o"}]}')[0][0]["id"] == 2
    assert discovery._extract_records(b'[{"id":3,"ocid":"o"}]')[0][0]["id"] == 3
    assert discovery._extract_records(b'{"message":"unsupported"}')[1] == "unsupported"


def test_contract_records_map_nested_tender():
    records, _ = discovery._extract_records(b'{"data":[{"id":99,"tender":{"id":77,"ocid":"ocid-77","tender_ref":"T-77"}}]}')
    tender = records[0]["tender"]
    assert tender["id"] == 77
    assert tender["ocid"] == "ocid-77"


def test_gap_plan_is_bounded_and_list_only(monkeypatch, tmp_path):
    roots = _source_fixture(monkeypatch, tmp_path)
    result = discovery.plan("source-run", country="ke", from_year=2025, to_year=2025, max_jobs=7)
    connection = duckdb.connect(str(roots.enriched / result["run_id"] / "ledger.duckdb"), read_only=True)
    assert result["planned_jobs"] == 7
    assert connection.execute("SELECT count(*) FROM discovery_jobs WHERE endpoint_family = 'archive'").fetchone()[0] == 0
    assert connection.execute("SELECT count(*) FROM discovery_jobs WHERE endpoint LIKE '%tender/%'").fetchone()[0] == 0
    connection.close()


def test_partition_plan_is_immutable_closed_route_and_capped(monkeypatch, tmp_path):
    roots = _source_fixture(monkeypatch, tmp_path)
    monkeypatch.setattr(
        discovery,
        "_partition_metadata_values",
        lambda canonical, pending, date_field, date_value: {
            "tender_ref": "T-7",
            "title": "Old tender",
            "pe:name": "Buyer",
            "procurementMethod:title": "Open",
            "procurementCategory:title": "Goods",
        },
    )
    first = discovery.partition_plan("source-run", country="ke", from_year=2025, to_year=2025, max_requests=6)
    second = discovery.partition_plan("source-run", country="ke", from_year=2025, to_year=2025, max_requests=6)
    assert first["run_id"] != second["run_id"]
    connection = duckdb.connect(str(roots.enriched / first["run_id"] / "ledger.duckdb"), read_only=True)
    assert connection.execute("SELECT count(*) FROM discovery_jobs").fetchone()[0] == 6
    assert connection.execute("SELECT count(*) FROM discovery_jobs WHERE endpoint = '/api/closed-tenders'").fetchone()[0] == 6
    assert connection.execute("SELECT count(*) FROM discovery_jobs WHERE endpoint_family = 'partition'").fetchone()[0] == 6
    assert connection.execute("SELECT max(attempts) FROM discovery_jobs").fetchone()[0] == 0
    connection.close()


def test_gap_execute_deduplicates_and_enqueues_next_page(monkeypatch, tmp_path):
    roots = _source_fixture(monkeypatch, tmp_path)
    planned = discovery.plan("source-run", country="ke", from_year=2025, to_year=2025, max_jobs=1)
    payload = json.dumps({"data": [{"id": 7, "ocid": "ocid-pending", "tender_ref": "T-7"}, {"id": 7, "ocid": "ocid-pending", "tender_ref": "T-7"}], "current_page": 1, "last_page": 2}).encode()
    monkeypatch.setattr(discovery, "_fetch", lambda url, params, timeout: (200, {"Content-Type": "application/json"}, payload))
    result = discovery.execute(planned["run_id"], country="ke", sleep=lambda _: None, randomizer=lambda: 0.0)
    connection = duckdb.connect(str(roots.enriched / planned["run_id"] / "ledger.duckdb"), read_only=True)
    assert result["mapping_count"] == 1, (result, connection.execute("SELECT status,error_class,error_message FROM discovery_jobs").fetchall())
    assert connection.execute("SELECT duplicate_count FROM discovery_mappings").fetchone()[0] == 1
    assert connection.execute("SELECT count(*) FROM discovery_jobs WHERE status = 'pending'").fetchone()[0] == 0
    connection.close()


def test_gap_execute_honors_retry_after(monkeypatch, tmp_path):
    roots = _source_fixture(monkeypatch, tmp_path)
    planned = discovery.plan("source-run", country="ke", from_year=2025, to_year=2025, max_jobs=1)
    payload = json.dumps({"data": [], "current_page": 1, "last_page": 1}).encode()
    responses = iter([
        (429, {"Retry-After": "8", "Content-Type": "application/json"}, b"rate limited"),
        (200, {"Content-Type": "application/json"}, payload),
    ])
    sleeps = []
    monkeypatch.setattr(discovery, "_fetch", lambda url, params, timeout: next(responses))
    result = discovery.execute(planned["run_id"], country="ke", sleep=sleeps.append, randomizer=lambda: 0.0)
    connection = duckdb.connect(str(roots.enriched / planned["run_id"] / "ledger.duckdb"), read_only=True)
    assert result["job_counts"]["succeeded"] == 1
    assert sleeps[0] == 8.0
    assert connection.execute("SELECT attempts, status FROM discovery_jobs").fetchone() == (2, "succeeded")
    assert '"Retry-After": "8"' in connection.execute("SELECT headers_json FROM discovery_responses WHERE http_status = 429").fetchone()[0]
    connection.close()


def test_promote_selects_one_mapping_per_ocid(monkeypatch, tmp_path):
    roots = _source_fixture(monkeypatch, tmp_path)
    discovery_run = "mapping-discovery-fixture"
    output = roots.enriched / discovery_run
    output.mkdir(parents=True)
    connection = duckdb.connect(str(output / "ledger.duckdb"))
    discovery._create_ledger(connection)
    connection.execute("INSERT INTO run_metadata VALUES (?, ?, ?, ?, ?, ?, 'complete', ?)", [discovery_run, "ke", "source-run", "sha", "{}", "now", 250])
    mapping_columns = "run_id, mapping_key, job_id, endpoint_family, endpoint, list_page, external_id, ocid, tender_ref, canonical_match, new_canonical_match, duplicate_count, response_hash, created_at"
    connection.execute(f"INSERT INTO discovery_mappings ({mapping_columns}) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)", [discovery_run, "key-1", "job-1", "list", "/api/closed-tenders", 1, "77", "ocid-pending", "T-7", True, True, 0, "hash", "now"])
    connection.execute(f"INSERT INTO discovery_mappings ({mapping_columns}) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)", [discovery_run, "key-2", "job-2", "list", "/api/active-tenders", 2, "88", "ocid-pending", "T-8", True, True, 0, "hash", "now"])
    connection.close()
    result = discovery.promote(discovery_run, country="ke", sample_per_cohort=100)
    assert result["selected_mappings"] == 1
    child = duckdb.connect(str(roots.enriched / result["run_id"] / "ledger.duckdb"), read_only=True)
    assert child.execute("SELECT count(*) FROM request_jobs WHERE job_type = 'detail'").fetchone()[0] == 1
    assert child.execute("SELECT expected_ocid, external_id FROM request_jobs").fetchone() == ("ocid-pending", "77")
    child.close()
