from __future__ import annotations

import hashlib
import json
import random
import time
import urllib.parse
from datetime import UTC, datetime
from pathlib import Path
from typing import Callable

import duckdb

from .durable_source_enrichment import BASE_URL, EngineConfig, RateLimiter, _cache_connection, _cache_lookup, _cache_store, _create_sequences, _fetch, _insert_job as _insert_detail_job, _now, _create_ledger as _create_detail_ledger, classify_status, execute as execute_detail, load_config
from .paths import canonical_root, country_paths
from .provenance import run_id, sha256_file, source_hash, utc_now


DISCOVERY_VERSION = "kenya-mapping-discovery-1"
LIST_ENDPOINTS = ("/api/active-tenders", "/api/closed-tenders")
ARCHIVE_ENDPOINTS = ("/api/explore-contracts", "/api/get/all/published-contracts", "/api/get/explored-contracts", "/api/contract")
FINANCIAL_YEAR_IDS = (
    (39, "2026-2027"), (36, "2025-2026"), (22, "2024-2025"),
    (21, "2023-2024"), (20, "2022-2023"), (19, "2021-2022"),
    (13, "2020-2021"), (14, "2019-2020"), (15, "2018-2019"),
    (38, "2016-2017"), (37, "2015-2016"),
)
DISCOVERY_SCHEMA = {
    "run_metadata": "run_id VARCHAR PRIMARY KEY, country VARCHAR, source_run_id VARCHAR, source_snapshot_sha256 VARCHAR, config_json VARCHAR, created_at VARCHAR, status VARCHAR, max_jobs INTEGER",
    "discovery_jobs": "job_id VARCHAR PRIMARY KEY, run_id VARCHAR, endpoint_family VARCHAR, endpoint VARCHAR, url VARCHAR, params_json VARCHAR, cohort_year INTEGER, filter_field VARCHAR, filter_value VARCHAR, status VARCHAR, attempts INTEGER, next_attempt_at DOUBLE, http_status INTEGER, error_class VARCHAR, error_message VARCHAR, response_hash VARCHAR, response_path VARCHAR, created_at VARCHAR, updated_at VARCHAR",
    "discovery_events": "event_id BIGINT, job_id VARCHAR, attempt INTEGER, state VARCHAR, wait_seconds DOUBLE, http_status INTEGER, retryable BOOLEAN, error_class VARCHAR, error_message VARCHAR, response_hash VARCHAR, created_at VARCHAR",
    "discovery_responses": "response_id BIGINT, run_id VARCHAR, job_id VARCHAR, url VARCHAR, retrieved_at VARCHAR, http_status INTEGER, content_type VARCHAR, response_hash VARCHAR, response_path VARCHAR, response_bytes BIGINT, cache_hit BOOLEAN",
    "discovery_mappings": "mapping_id BIGINT, run_id VARCHAR, mapping_key VARCHAR UNIQUE, job_id VARCHAR, endpoint_family VARCHAR, endpoint VARCHAR, list_page INTEGER, external_id VARCHAR, ocid VARCHAR, tender_ref VARCHAR, canonical_match BOOLEAN, new_canonical_match BOOLEAN, duplicate_count INTEGER, response_hash VARCHAR, created_at VARCHAR",
    "discovery_capabilities": "capability_id BIGINT, run_id VARCHAR, endpoint_family VARCHAR, endpoint VARCHAR, parameter_name VARCHAR, parameter_value VARCHAR, status VARCHAR, record_count INTEGER, response_hash VARCHAR, observed_at VARCHAR, notes VARCHAR",
}


def _sha(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()[:32]


def _base_params(perpage: int) -> dict[str, str | int]:
    return {"search": "", "perpage": perpage, "sortby": "", "order": "asc", "page": 1, "tender_ref": "", "title": "", "pe:name": "", "procurementMethod:title": "", "procurementCategory:title": "", "close_at": "", "published_at": "", "addendum_added": ""}


def _job_id(endpoint: str, params: dict) -> str:
    return _sha(endpoint + "?" + urllib.parse.urlencode(sorted(params.items())))


def _create_ledger(connection: duckdb.DuckDBPyConnection) -> None:
    for table, definition in DISCOVERY_SCHEMA.items():
        connection.execute(f'CREATE TABLE IF NOT EXISTS "{table}" ({definition})')
    connection.execute("CREATE SEQUENCE IF NOT EXISTS discovery_event_seq START 1")
    connection.execute("CREATE SEQUENCE IF NOT EXISTS discovery_response_seq START 1")
    connection.execute("CREATE SEQUENCE IF NOT EXISTS discovery_mapping_seq START 1")
    connection.execute("CREATE SEQUENCE IF NOT EXISTS discovery_capability_seq START 1")


def _insert_job(connection: duckdb.DuckDBPyConnection, run: str, endpoint_family: str, endpoint: str, params: dict, *, cohort_year: int | None = None, filter_field: str | None = None, filter_value: str | None = None) -> bool:
    job_id = _job_id(endpoint, params)
    now = utc_now()
    result = connection.execute(
        "INSERT INTO discovery_jobs VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 'pending', 0, 0, NULL, NULL, NULL, NULL, NULL, ?, ?) ON CONFLICT (job_id) DO NOTHING",
        [job_id, run, endpoint_family, endpoint, BASE_URL + endpoint, json.dumps(params, sort_keys=True), cohort_year, filter_field, filter_value, now, now],
    )
    return result.fetchone()[0] if result.description else True


def _canonical_context(source_run: str, country: str) -> tuple[set[str], set[str], Path, str]:
    roots = country_paths(country)
    source_path = roots.enriched / source_run / "source_enrichment.parquet"
    eligibility_path = roots.enriched / source_run / "enrichment_eligibility.parquet"
    if not source_path.exists() or not eligibility_path.exists():
        raise FileNotFoundError(f"Completed source run outputs are incomplete: {roots.enriched / source_run}")
    canonical = canonical_root(country)
    connection = duckdb.connect()
    pending = {row[0] for row in connection.execute("SELECT ocid FROM read_parquet(?) WHERE state = 'mapping_pending' AND ocid IS NOT NULL", [str(eligibility_path)]).fetchall()}
    validated = {row[0] for row in connection.execute("SELECT ocid FROM read_parquet(?) WHERE ocid IS NOT NULL", [str(source_path)]).fetchall()}
    connection.close()
    source_sha = source_hash(roots.raw / "ocds_full.jsonl.gz", roots.raw / "manifest.json")
    return pending, validated, canonical, source_sha


def _date_values(canonical: Path, pending: set[str], field: str, years: list[int]) -> dict[int, list[str]]:
    connection = duckdb.connect()
    table = "releases" if field == "published_at" else "tenders"
    column = "release_date" if field == "published_at" else "period_end"
    rows = connection.execute(f"SELECT ocid, try_cast({column} AS DATE) FROM read_parquet(?) WHERE ocid IN ({','.join('?' for _ in pending)}) AND try_cast({column} AS DATE) IS NOT NULL", [str(canonical / f"{table}.parquet"), *pending]).fetchall() if pending else []
    connection.close()
    by_year: dict[int, list[str]] = {year: [] for year in years}
    for _, value in rows:
        value_text = value.isoformat() if hasattr(value, "isoformat") else str(value)
        year = int(value_text[:4])
        if year in by_year:
            by_year[year].append(value_text[:10])
    selected: dict[int, list[str]] = {}
    for year, values in by_year.items():
        unique = sorted(set(values))
        if not unique:
            continue
        positions = sorted(set((0, len(unique) // 2, len(unique) - 1)))
        selected[year] = [unique[index] for index in positions]
    return selected


def _financial_year_resume_pages(resume_run_root: Path) -> dict[int, list[int]]:
    ledger_path = resume_run_root / "ledger.duckdb"
    if not ledger_path.exists():
        raise FileNotFoundError(f"Discovery resume run not found: {resume_run_root.name}")
    connection = duckdb.connect(str(ledger_path), read_only=True)
    rows = connection.execute(
        "SELECT status, params_json FROM discovery_jobs WHERE endpoint = '/api/get/explored-contracts'"
    ).fetchall()
    connection.close()
    successful: dict[int, list[int]] = {}
    failed: dict[int, list[int]] = {}
    for status, params_json in rows:
        params = json.loads(params_json)
        clauses = json.loads(params.get("clauses", "[]"))
        if not clauses or clauses[0].get("col") != "financial_year_id":
            continue
        year_id = int(clauses[0]["value"])
        page = int(params.get("page", 1))
        target = successful if status == "succeeded" else failed if status == "permanent_failed" else None
        if target is not None:
            target.setdefault(year_id, []).append(page)
    pages: dict[int, list[int]] = {}
    for year_id, values in successful.items():
        next_page = max(values) + 1
        pages[year_id] = sorted(set(failed.get(year_id, []) + [next_page]))
    for year_id, values in failed.items():
        pages.setdefault(year_id, sorted(set(values)))
    return pages


def plan(source_run: str, *, country: str = "ke", from_year: int = 2018, to_year: int = 2025, max_jobs: int = 250, config_path: Path | None = None, contract_only: bool = False, financial_year_json_only: bool = False, financial_year_json_resume_run: str | None = None) -> dict:
    if country != "ke" or from_year > to_year:
        raise ValueError("country must be ke and from_year must be <= to_year")
    pending, validated, canonical, source_sha = _canonical_context(source_run, country)
    config = load_config(config_path)
    roots = country_paths(country)
    run = run_id(source_sha, "mapping-discovery")
    output_root = roots.enriched / run
    output_root.mkdir(parents=True, exist_ok=True)
    connection = duckdb.connect(str(output_root / "ledger.duckdb"))
    _create_ledger(connection)
    connection.execute("INSERT INTO run_metadata VALUES (?, ?, ?, ?, ?, ?, 'planned', ?)", [run, country, source_run, source_sha, json.dumps({"version": DISCOVERY_VERSION, "config": config.__dict__, "financial_year_json_resume_run": financial_year_json_resume_run}), utc_now(), max_jobs])
    jobs: list[tuple] = []
    resume_pages = _financial_year_resume_pages(roots.enriched / financial_year_json_resume_run) if financial_year_json_resume_run else {}
    years = list(range(from_year, to_year + 1)) + [2026]
    for endpoint in LIST_ENDPOINTS:
        metadata_values: dict[str, str] = {}
        for perpage in (100, 1000, 5000):
            params = _base_params(perpage)
            jobs.append((endpoint, params, None, "perpage", str(perpage)))
        for field in ("tender_ref", "title", "pe:name", "procurementMethod:title", "procurementCategory:title", "addendum_added"):
            values = connection.execute(f"SELECT DISTINCT {('tender_number' if field == 'tender_ref' else 'title' if field == 'title' else 'procuring_entity_name' if field == 'pe:name' else 'procurement_method' if field == 'procurementMethod:title' else 'procurement_category' if field == 'procurementCategory:title' else 'published_date_raw')} FROM read_parquet(?) WHERE {('tender_number' if field == 'tender_ref' else 'title' if field == 'title' else 'procuring_entity_name' if field == 'pe:name' else 'procurement_method' if field == 'procurementMethod:title' else 'procurement_category' if field == 'procurementCategory:title' else 'published_date_raw')} IS NOT NULL ORDER BY 1 LIMIT 1", [str(roots.enriched / source_run / "source_enrichment.parquet")]).fetchone()
            if field == "addendum_added":
                values = ("1",)
            if values and values[0]:
                params = _base_params(100)
                params[field] = values[0]
                metadata_values[field] = str(values[0])
                jobs.append((endpoint, params, None, field, str(values[0])))
        for field in ("published_at", "close_at"):
            for year, values in _date_values(canonical, pending, field, years).items():
                for value in values:
                    params = _base_params(100)
                    params[field] = value
                    jobs.append((endpoint, params, year, field, value))
        for date_field in ("published_at", "close_at"):
            for year, values in _date_values(canonical, pending, date_field, years).items():
                for value in values:
                    for metadata_field in ("tender_ref", "title", "pe:name", "procurementMethod:title", "procurementCategory:title"):
                        metadata_value = metadata_values.get(metadata_field)
                        if not metadata_value:
                            continue
                        params = _base_params(100)
                        params[date_field] = value
                        params[metadata_field] = metadata_value
                        jobs.append((endpoint, params, year, f"{date_field}+{metadata_field}", f"{value}|{metadata_value}"))
    for endpoint in ARCHIVE_ENDPOINTS:
        if endpoint == "/api/get/explored-contracts":
            for year_id, label in FINANCIAL_YEAR_IDS:
                clauses = json.dumps([{"col": "financial_year_id", "value": year_id, "type": "nominal"}], separators=(",", ":"))
                pages = resume_pages.get(year_id, [1])
                for page in pages:
                    jobs.append((endpoint, {"perpage": 10, "page": page, "clauses": clauses}, int(label[:4]), "financial_year", label))
        elif endpoint == "/api/contract":
            jobs.append((endpoint, {"perpage": 50, "page": 1}, None, "contract_archive", ""))
        else:
            jobs.append((endpoint, {"perpage": 100, "page": 1}, None, "archive_control", ""))
    if contract_only:
        jobs = [job for job in jobs if job[0] == "/api/contract"]
    if financial_year_json_only:
        jobs = [job for job in jobs if job[0] == "/api/get/explored-contracts"]
    jobs = jobs[:max_jobs]
    for endpoint, params, year, field, value in jobs:
        _insert_job(connection, run, "archive" if endpoint in ARCHIVE_ENDPOINTS else "list", endpoint, params, cohort_year=year, filter_field=field, filter_value=value)
    connection.execute("UPDATE run_metadata SET status = 'planned' WHERE run_id = ?", [run])
    planned = connection.execute("SELECT count(*) FROM discovery_jobs WHERE run_id = ?", [run]).fetchone()[0]
    connection.close()
    return {"run_id": run, "source_run_id": source_run, "source_snapshot_sha256": source_sha, "status": "planned", "planned_jobs": planned, "pending_canonical": len(pending), "validated_canonical": len(validated), "max_jobs": max_jobs, "output_root": str(output_root)}


def _extract_records(payload: bytes) -> tuple[list[dict], str]:
    value = json.loads(payload)
    if isinstance(value, list):
        return [item for item in value if isinstance(item, dict)], "root"
    if not isinstance(value, dict):
        return [], "unsupported"
    for key in ("data", "results", "records", "items"):
        if isinstance(value.get(key), list):
            return [item for item in value[key] if isinstance(item, dict)], key
    return [], "unsupported"


def _save_response(connection, run: str, job_id: str, url: str, status: int, headers: dict, payload: bytes, root: Path, cache_hit: bool) -> tuple[str, str]:
    digest = hashlib.sha256(payload).hexdigest()
    path = root / f"{job_id}-{digest[:12]}.json"
    if not path.exists():
        path.write_bytes(payload)
    connection.execute("INSERT INTO discovery_responses VALUES (nextval('discovery_response_seq'), ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)", [run, job_id, url, utc_now(), status, headers.get("Content-Type"), digest, str(path), len(payload), cache_hit])
    return digest, str(path)


def _record_event(connection, job_id: str, attempt: int, state: str, wait: float, status: int | None, retryable: bool, error_class: str | None, message: str | None, digest: str | None) -> None:
    connection.execute("INSERT INTO discovery_events VALUES (nextval('discovery_event_seq'), ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)", [job_id, attempt, state, wait, status, retryable, error_class, message, digest, utc_now()])


def _process_mapping_rows(connection, run: str, job: tuple, payload: bytes, digest: str, canonical: set[str], validated: set[str], seen_keys: set[str] | None = None) -> int:
    records, _ = _extract_records(payload)
    endpoint_family = job[2]
    endpoint = job[3]
    params = json.loads(job[5])
    page = int(params.get("page", 1))
    inserted = 0
    duplicate_counts: dict[str, int] = {}
    seen_keys = seen_keys if seen_keys is not None else set()
    for record in records:
        tender = record.get("tender") if isinstance(record.get("tender"), dict) else record
        external_id = tender.get("id")
        ocid = tender.get("ocid")
        if external_id is None or not ocid:
            continue
        external_id = str(external_id)
        key = _sha(f"{ocid}|{external_id}")
        if key in seen_keys:
            duplicate_counts[key] = duplicate_counts.get(key, 0) + 1
            continue
        connection.execute("INSERT INTO discovery_mappings VALUES (nextval('discovery_mapping_seq'), ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)", [run, key, job[0], endpoint_family, endpoint, page, external_id, ocid, tender.get("tender_ref"), ocid in canonical, ocid in canonical and ocid not in validated, 0, digest, utc_now()])
        inserted += 1
        seen_keys.add(key)
    for key, count in duplicate_counts.items():
        connection.execute("UPDATE discovery_mappings SET duplicate_count = duplicate_count + ? WHERE mapping_key = ?", [count, key])
    return inserted


def _enqueue_next_page(connection, job: tuple, payload: bytes, max_jobs: int) -> None:
    data = json.loads(payload)
    params = json.loads(job[5])
    page = int(params.get("page", 1))
    last_page = int(data.get("last_page") or page) if isinstance(data, dict) else page
    if page >= last_page:
        return
    count = connection.execute("SELECT count(*) FROM discovery_jobs WHERE run_id = ?", [job[1]]).fetchone()[0]
    if count >= max_jobs:
        return
    next_params = dict(params)
    next_params["page"] = page + 1
    _insert_job(connection, job[1], job[2], job[3], next_params, cohort_year=job[6], filter_field=job[7], filter_value=job[8])


def _enqueue_contract_fallback(connection, job: tuple, max_jobs: int) -> None:
    params = json.loads(job[5])
    if job[3] != "/api/contract" or int(params.get("perpage", 0)) != 50:
        return
    page = int(params.get("page", 1))
    first_page = (page - 1) * 5 + 1
    for fallback_page in range(first_page, first_page + 5):
        if connection.execute("SELECT count(*) FROM discovery_jobs WHERE run_id = ?", [job[1]]).fetchone()[0] >= max_jobs:
            break
        _insert_job(connection, job[1], "archive", job[3], {"perpage": 10, "page": fallback_page}, cohort_year=job[6], filter_field="contract_page_split", filter_value=str(fallback_page))


def execute(run: str, *, country: str = "ke", config_path: Path | None = None, sleep: Callable[[float], None] = time.sleep, randomizer: Callable[[], float] = random.random) -> dict:
    roots = country_paths(country)
    output_root = roots.enriched / run
    connection = duckdb.connect(str(output_root / "ledger.duckdb"))
    _create_ledger(connection)
    metadata = connection.execute("SELECT source_run_id, source_snapshot_sha256, max_jobs FROM run_metadata WHERE run_id = ?", [run]).fetchone()
    if not metadata:
        raise FileNotFoundError(f"Discovery run not found: {run}")
    source_run, _, max_jobs = metadata
    connection.execute("UPDATE discovery_jobs SET status='retryable_failed', attempts=0, next_attempt_at=0, error_message=NULL, updated_at=? WHERE run_id=? AND status IN ('permanent_failed', 'running') AND error_class IN ('TimeoutError', 'URLError', 'http_408', 'http_425', 'http_429', 'http_500', 'http_502', 'http_503', 'http_504')", [utc_now(), run])
    _, validated, canonical_root_path, _ = _canonical_context(source_run, country)
    canonical = set(row[0] for row in connection.execute("SELECT ocid FROM read_parquet(?) WHERE ocid IS NOT NULL", [str(canonical_root_path / "releases.parquet")]).fetchall())
    seen_mapping_keys = set(row[0] for row in connection.execute("SELECT mapping_key FROM discovery_mappings WHERE run_id = ?", [run]).fetchall())
    config: EngineConfig = load_config(config_path)
    cache = _cache_connection(roots)
    response_root = output_root / "responses"
    response_root.mkdir(exist_ok=True)
    limiter = RateLimiter(config.refill_rate_per_second, config.jitter_seconds, sleeper=sleep, randomizer=randomizer)
    while True:
        job = connection.execute("SELECT * FROM discovery_jobs WHERE run_id = ? AND status IN ('pending','retryable_failed') AND next_attempt_at <= ? ORDER BY CASE WHEN endpoint = '/api/get/explored-contracts' THEN 0 ELSE 1 END, try_cast(json_extract_string(params_json, '$.page') AS INTEGER), created_at, job_id LIMIT 1", [run, _now()]).fetchone()
        if not job:
            next_ready = connection.execute("SELECT min(next_attempt_at) FROM discovery_jobs WHERE run_id = ? AND status IN ('pending','retryable_failed')", [run]).fetchone()[0]
            if next_ready is None:
                break
            sleep(max(0.0, next_ready - _now()))
            continue
        job_id, _, endpoint_family, endpoint, url, params_json, *_ = job
        attempts = job[10] + 1
        wait = limiter.wait()
        connection.execute("UPDATE discovery_jobs SET status='running', attempts=?, updated_at=? WHERE job_id=?", [attempts, utc_now(), job_id])
        params = json.loads(params_json)
        try:
            cached = _cache_lookup(cache, "list", url, params_json, None)
            if cached:
                _, status, content_type, digest, path, _, _ = cached
                payload = Path(path).read_bytes()
                headers = {"Content-Type": content_type} if content_type else {}
                _save_response(connection, run, job_id, url, status, headers, payload, response_root, True)
            else:
                status, headers, payload = _fetch(url, params, config.request_timeout_seconds)
                digest, path = _save_response(connection, run, job_id, url, status, headers, payload, response_root, False)
                if status == 200:
                    _cache_store(cache, "list", url, params_json, None, status, headers.get("Content-Type"), digest, path, None, run)
            if status == 200:
                records, shape = _extract_records(payload)
                connection.execute("INSERT INTO discovery_capabilities VALUES (nextval('discovery_capability_seq'), ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)", [run, endpoint_family, endpoint, job[7], job[8], "supported" if shape != "unsupported" else "unsupported_shape", len(records), digest, utc_now(), shape])
                _process_mapping_rows(connection, run, job, payload, digest, canonical, validated, seen_mapping_keys)
                _enqueue_next_page(connection, job, payload, max_jobs)
                connection.execute("UPDATE discovery_jobs SET status='succeeded', http_status=200, response_hash=?, response_path=?, updated_at=? WHERE job_id=?", [digest, path, utc_now(), job_id])
                _record_event(connection, job_id, attempts, "succeeded", wait, status, False, None, None, digest)
                limiter.success()
                continue
            retryable, error_class = classify_status(status, None, config.retry_statuses)
            if retryable and attempts < config.max_attempts:
                delay = min(config.max_backoff_seconds, 2 ** attempts) + randomizer() * config.jitter_seconds
                connection.execute("UPDATE discovery_jobs SET status='retryable_failed', next_attempt_at=?, http_status=?, error_class=?, error_message=?, response_hash=?, response_path=?, updated_at=? WHERE job_id=?", [_now() + delay, status, error_class, "retryable HTTP response", digest, path, utc_now(), job_id])
                _record_event(connection, job_id, attempts, "retryable_failed", wait, status, True, error_class, "retryable HTTP response", digest)
                continue
            connection.execute("UPDATE discovery_jobs SET status='permanent_failed', http_status=?, error_class=?, error_message=?, response_hash=?, response_path=?, updated_at=? WHERE job_id=?", [status, error_class, "permanent HTTP response", digest, path, utc_now(), job_id])
            _record_event(connection, job_id, attempts, "permanent_failed", wait, status, False, error_class, "permanent HTTP response", digest)
        except Exception as error:
            retryable, error_class = classify_status(None, error, config.retry_statuses)
            state = "retryable_failed" if retryable and attempts < config.max_attempts else "permanent_failed"
            if state == "permanent_failed":
                _enqueue_contract_fallback(connection, job, max_jobs)
            next_at = _now() + min(config.max_backoff_seconds, 2 ** attempts)
            connection.execute("UPDATE discovery_jobs SET status=?, next_attempt_at=?, error_class=?, error_message=?, updated_at=? WHERE job_id=?", [state, next_at, error_class, str(error), utc_now(), job_id])
            _record_event(connection, job_id, attempts, state, wait, None, state == "retryable_failed", error_class, str(error), None)
    counts = {row[0]: row[1] for row in connection.execute("SELECT status,count(*) FROM discovery_jobs WHERE run_id=? GROUP BY status", [run]).fetchall()}
    mapping_count = connection.execute("SELECT count(*) FROM discovery_mappings WHERE run_id=?", [run]).fetchone()[0]
    new_matches = connection.execute("SELECT count(*) FROM discovery_mappings WHERE run_id=? AND new_canonical_match", [run]).fetchone()[0]
    connection.execute("UPDATE run_metadata SET status=? WHERE run_id=?", ["complete" if not counts.get("permanent_failed") and not counts.get("retryable_failed") else "warn", run])
    cache.close()
    connection.close()
    return {"run_id": run, "status": "complete" if not counts.get("permanent_failed") and not counts.get("retryable_failed") else "warn", "job_counts": counts, "mapping_count": mapping_count, "new_canonical_matches": new_matches, "output_root": str(output_root)}


def report(run: str, *, country: str = "ke") -> dict:
    roots = country_paths(country)
    output_root = roots.enriched / run
    ledger_path = output_root / "ledger.duckdb"
    if not ledger_path.exists():
        raise FileNotFoundError(f"Discovery run not found: {run}")
    connection = duckdb.connect(str(ledger_path))
    metadata = connection.execute("SELECT source_run_id, source_snapshot_sha256, status, max_jobs FROM run_metadata WHERE run_id=?", [run]).fetchone()
    if not metadata:
        raise FileNotFoundError(f"Discovery run not found: {run}")
    source_run, source_sha, status, max_jobs = metadata
    job_counts = {str(row[0]): row[1] for row in connection.execute("SELECT status,count(*) FROM discovery_jobs WHERE run_id=? GROUP BY status ORDER BY status", [run]).fetchall()}
    mapping_count = connection.execute("SELECT count(*) FROM discovery_mappings WHERE run_id=?", [run]).fetchone()[0]
    new_matches = connection.execute("SELECT count(*) FROM discovery_mappings WHERE run_id=? AND new_canonical_match", [run]).fetchone()[0]
    duplicate_rows = connection.execute("SELECT coalesce(sum(duplicate_count),0) FROM discovery_mappings WHERE run_id=?", [run]).fetchone()[0]
    capability_rows = connection.execute("SELECT endpoint_family,endpoint,parameter_name,parameter_value,status,record_count,notes FROM discovery_capabilities WHERE run_id=? ORDER BY endpoint,parameter_name", [run]).fetchall()
    errors = {str(row[0]): row[1] for row in connection.execute("SELECT error_class,count(*) FROM discovery_jobs WHERE run_id=? AND error_class IS NOT NULL GROUP BY error_class ORDER BY error_class", [run]).fetchall()}
    safe_run = run.replace("'", "''")
    mappings_path = str(output_root / "mapping_discovery_mappings.parquet").replace("'", "''")
    capabilities_path = str(output_root / "mapping_discovery_capabilities.parquet").replace("'", "''")
    connection.execute(f"COPY (SELECT * FROM discovery_mappings WHERE run_id = '{safe_run}') TO '{mappings_path}' (FORMAT PARQUET, COMPRESSION ZSTD)")
    connection.execute(f"COPY (SELECT * FROM discovery_capabilities WHERE run_id = '{safe_run}') TO '{capabilities_path}' (FORMAT PARQUET, COMPRESSION ZSTD)")
    connection.close()
    value = {
        "run_id": run,
        "source_run_id": source_run,
        "source_snapshot_sha256": source_sha,
        "discovery_version": DISCOVERY_VERSION,
        "generated_at": utc_now(),
        "status": status,
        "max_jobs": max_jobs,
        "job_counts": job_counts,
        "mapping_count": mapping_count,
        "new_canonical_matches": new_matches,
        "duplicate_observations": duplicate_rows,
        "error_counts": errors,
        "capabilities": [dict(zip(("endpoint_family", "endpoint", "parameter_name", "parameter_value", "status", "record_count", "notes"), row)) for row in capability_rows],
        "output_root": str(output_root),
        "limitations": ["List and archive responses establish candidate mappings only. Detail OCID validation is required before promotion.", "A bounded probe does not measure exhaustive historical coverage."],
    }
    (output_root / "mapping_discovery_report.json").write_text(json.dumps(value, indent=2) + "\n", encoding="utf-8")
    lines = ["# Kenya mapping discovery report", "", f"Run: `{run}`", f"Status: `{status}`", "", "## Requests", ""]
    lines.extend(f"- `{key}`: {count}" for key, count in job_counts.items())
    lines.extend(["", "## Mappings", "", f"- Observed mappings: {mapping_count}", f"- New canonical matches: {new_matches}", f"- Duplicate observations: {duplicate_rows}", "", "## Errors", ""])
    lines.extend(f"- `{key}`: {count}" for key, count in errors.items())
    lines.extend(["", "Detail validation is a separate promotion stage. This report does not accept candidate mappings as validated enrichment.", ""])
    (output_root / "mapping_discovery_report.md").write_text("\n".join(lines), encoding="utf-8")
    return value


def _validated_ocids(roots, source_run: str) -> set[str]:
    paths = {roots.enriched / source_run / "source_enrichment.parquet"}
    paths.update(roots.enriched.glob("*/source_enrichment.parquet"))
    values: set[str] = set()
    connection = duckdb.connect()
    for path in sorted(path for path in paths if path.exists()):
        values.update(row[0] for row in connection.execute("SELECT DISTINCT ocid FROM read_parquet(?) WHERE ocid IS NOT NULL", [str(path)]).fetchall())
    connection.close()
    return values


def promote(discovery_run: str, *, country: str = "ke", sample_per_cohort: int = 100, all_mappings: bool = False, config_path: Path | None = None) -> dict:
    """Create an immutable child detail run from newly discovered mappings."""
    if country != "ke" or sample_per_cohort < 1:
        raise ValueError("country must be ke and sample_per_cohort must be positive")
    roots = country_paths(country)
    discovery_root = roots.enriched / discovery_run
    connection = duckdb.connect(str(discovery_root / "ledger.duckdb"), read_only=True)
    metadata = connection.execute("SELECT source_run_id, source_snapshot_sha256 FROM run_metadata WHERE run_id = ?", [discovery_run]).fetchone()
    if not metadata:
        raise FileNotFoundError(f"Discovery run not found: {discovery_run}")
    source_run, source_sha = metadata
    canonical = canonical_root(country)
    existing = _validated_ocids(roots, source_run)
    rows = connection.execute("""
        SELECT mapping_id, endpoint, list_page, response_hash, external_id, ocid, tender_ref
        FROM discovery_mappings
        WHERE run_id = ? AND new_canonical_match
        ORDER BY mapping_id
    """, [discovery_run]).fetchall()
    release_month = dict(connection.execute("SELECT ocid, coalesce(strftime(try_cast(release_date AS DATE), '%Y-%m'), 'unknown') FROM read_parquet(?)", [str(canonical / "releases.parquet")]).fetchall())
    connection.close()
    by_ocid: dict[str, tuple] = {}
    for row in rows:
        if row[5] in existing:
            continue
        current = by_ocid.get(row[5])
        if current is None or (str(row[4]), str(row[0])) < (str(current[4]), str(current[0])):
            by_ocid[row[5]] = row
    candidates = sorted(by_ocid.values(), key=lambda row: (release_month.get(row[5], "unknown"), hashlib.sha256(row[5].encode()).hexdigest(), row[5]))
    if not all_mappings:
        selected: list[tuple] = []
        counts: dict[str, int] = {}
        for row in candidates:
            cohort = release_month.get(row[5], "unknown")
            if counts.get(cohort, 0) >= sample_per_cohort:
                continue
            selected.append(row)
            counts[cohort] = counts.get(cohort, 0) + 1
        candidates = selected
    config = load_config(config_path)
    child_run = run_id(source_sha, "source-enrich-promotion")
    output_root = roots.enriched / child_run
    output_root.mkdir(parents=True, exist_ok=True)
    (output_root / "responses").mkdir(exist_ok=True)
    ledger = duckdb.connect(str(output_root / "ledger.duckdb"))
    _create_detail_ledger(ledger)
    _create_sequences(ledger)
    ledger.execute("INSERT INTO run_metadata (run_id, country, source_snapshot_sha256, config_json, created_at, status, detail_limit, resume_count) VALUES (?, ?, ?, ?, ?, 'planned', ?, 0)", [child_run, country, source_sha, json.dumps({"promotion_parent": discovery_run, "source_run_id": source_run, "sample_per_cohort": None if all_mappings else sample_per_cohort, "all_mappings": all_mappings, "version": DISCOVERY_VERSION, "config": config.__dict__}), utc_now(), len(candidates)])
    for mapping_id, endpoint, page, response_hash, external_id, ocid, tender_ref in candidates:
        ledger.execute("INSERT INTO source_mappings VALUES (nextval('mapping_seq'), ?, ?, ?, ?, ?, ?, ?, ?, ?)", [child_run, endpoint, page, response_hash, external_id, ocid, tender_ref, True, utc_now()])
        _insert_detail_job(ledger, child_run, "detail", config.detail_endpoint, BASE_URL + config.detail_endpoint.format(id=external_id), {}, ocid, external_id)
    ledger.close()
    result = {"discovery_run_id": discovery_run, "parent_source_run_id": source_run, "run_id": child_run, "status": "planned", "candidate_mappings": len(rows), "selected_mappings": len(candidates), "sample_per_cohort": None if all_mappings else sample_per_cohort, "all_mappings": all_mappings, "output_root": str(output_root)}
    (output_root / "promotion_plan.json").write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    return result


def combine(child_run: str, *, country: str = "ke", baseline_run: str | None = None, additional_child_runs: tuple[str, ...] = ()) -> dict:
    """Materialize a new deduplicated view from validated baseline and child rows."""
    roots = country_paths(country)
    child_root = roots.enriched / child_run
    child_ledger = child_root / "ledger.duckdb"
    metadata_connection = duckdb.connect(str(child_ledger), read_only=True)
    metadata = metadata_connection.execute("SELECT source_snapshot_sha256, config_json FROM run_metadata WHERE run_id = ?", [child_run]).fetchone()
    metadata_connection.close()
    if not metadata:
        raise FileNotFoundError(f"Promotion run not found: {child_run}")
    source_sha, config_json = metadata
    config = json.loads(config_json)
    baseline_run = baseline_run or config.get("source_run_id")
    if not baseline_run:
        raise ValueError("The child run does not record a baseline source run")
    baseline = roots.enriched / baseline_run / "source_enrichment.parquet"
    child_paths = [child_root / "source_enrichment.parquet"] + [roots.enriched / run / "source_enrichment.parquet" for run in additional_child_runs]
    if not baseline.exists() or any(not path.exists() for path in child_paths):
        raise FileNotFoundError("Baseline and completed child materializations are required")
    connection = duckdb.connect()
    combined_run = run_id(source_sha, "source-enrich-combined")
    output_root = roots.enriched / combined_run
    output_root.mkdir(parents=True, exist_ok=True)
    columns = [row[0] for row in connection.execute("DESCRIBE SELECT * FROM read_parquet(?)", [str(baseline)]).fetchall()]
    column_sql = ", ".join(f'"{column}"' for column in columns)
    sources = [(baseline_run, baseline_run, baseline)] + [(run, baseline_run, path) for run, path in zip(additional_child_runs[:], child_paths[1:])]
    sources.insert(1, (child_run, baseline_run, child_paths[0]))
    source_sql = "\n            UNION ALL\n".join(f"SELECT {column_sql}, ? AS source_run_id, ? AS parent_source_run_id FROM read_parquet(?)" for _ in sources)
    query = f"""
        WITH rows AS (
            {source_sql}
        ), ranked AS (
            SELECT *, row_number() OVER (PARTITION BY ocid ORDER BY source_run_id, external_record_id) AS rn FROM rows
        )
        SELECT * EXCLUDE (rn) FROM ranked WHERE rn = 1
    """
    parameters = [value for source in sources for value in (source[0], source[1], str(source[2]))]
    connection.execute("CREATE OR REPLACE TABLE combined AS " + query, parameters)
    combined_path = output_root / "source_enrichment_combined.parquet"
    connection.execute("COPY combined TO ? (FORMAT PARQUET, COMPRESSION ZSTD)", [str(combined_path)])
    connection.execute("COPY (SELECT ocid, source_run_id, parent_source_run_id, source_content_sha256, raw_response_path, external_record_id FROM combined) TO ? (FORMAT PARQUET, COMPRESSION ZSTD)", [str(output_root / "source_enrichment_provenance.parquet")])
    rows = connection.execute("SELECT count(*), count(DISTINCT ocid) FROM combined").fetchone()
    connection.close()
    result = {"run_id": combined_run, "baseline_run_id": baseline_run, "child_run_ids": [child_run, *additional_child_runs], "source_snapshot_sha256": source_sha, "rows": rows[0], "unique_ocids": rows[1], "output_root": str(output_root), "status": "complete"}
    (output_root / "combined_manifest.json").write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    return result
