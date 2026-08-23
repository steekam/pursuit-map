from __future__ import annotations

import hashlib
import json
import random
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Callable

import duckdb

from .paths import canonical_root, country_paths, ensure_data_dirs
from .provenance import parquet_checksums, run_id, source_hash, utc_now, write_run_manifest
from .source_enrichment import SCHEMA, parse_tender_payload


BASE_URL = "https://tenders.go.ke"
LEDGER_SCHEMA = {
    "run_metadata": "run_id VARCHAR PRIMARY KEY, country VARCHAR, source_snapshot_sha256 VARCHAR, config_json VARCHAR, created_at VARCHAR, status VARCHAR, detail_limit INTEGER, resume_count INTEGER",
    "request_jobs": "job_id VARCHAR PRIMARY KEY, run_id VARCHAR, job_type VARCHAR, endpoint VARCHAR, url VARCHAR, params_json VARCHAR, expected_ocid VARCHAR, external_id VARCHAR, status VARCHAR, attempts INTEGER, next_attempt_at DOUBLE, lease_owner VARCHAR, lease_until DOUBLE, http_status INTEGER, error_class VARCHAR, error_message VARCHAR, response_hash VARCHAR, response_path VARCHAR, observed_ocid VARCHAR, created_at VARCHAR, updated_at VARCHAR",
    "request_events": "event_id BIGINT, job_id VARCHAR, attempt INTEGER, state VARCHAR, wait_seconds DOUBLE, http_status INTEGER, retryable BOOLEAN, error_class VARCHAR, error_message VARCHAR, response_hash VARCHAR, created_at VARCHAR",
    "source_mappings": "mapping_id BIGINT, run_id VARCHAR, list_endpoint VARCHAR, list_page INTEGER, list_response_hash VARCHAR, external_id VARCHAR, ocid VARCHAR, tender_ref VARCHAR, canonical_match BOOLEAN, created_at VARCHAR",
    "source_responses": "response_id BIGINT, run_id VARCHAR, job_id VARCHAR, url VARCHAR, retrieved_at VARCHAR, http_status INTEGER, content_type VARCHAR, response_hash VARCHAR, response_path VARCHAR, response_bytes BIGINT",
}
CACHE_SCHEMA = {
    "cached_responses": "cache_key VARCHAR PRIMARY KEY, job_type VARCHAR, url VARCHAR, params_json VARCHAR, expected_ocid VARCHAR, http_status INTEGER, content_type VARCHAR, response_hash VARCHAR, response_path VARCHAR, observed_ocid VARCHAR, source_run_id VARCHAR, cached_at VARCHAR",
}


@dataclass(frozen=True)
class EngineConfig:
    source: str
    source_version: str
    api_version: str
    list_endpoints: tuple[str, ...]
    detail_endpoint: str
    per_page: int = 100
    request_timeout_seconds: int = 30
    concurrency: int = 1
    refill_rate_per_second: float = 1.0
    jitter_seconds: float = 1.0
    max_attempts: int = 6
    max_backoff_seconds: int = 600
    circuit_breaker_429_count: int = 3
    circuit_breaker_pause_seconds: int = 60
    retry_statuses: tuple[int, ...] = (408, 425, 429, 500, 502, 503, 504)


def load_config(path: Path | None = None) -> EngineConfig:
    path = path or Path(__file__).resolve().parents[3] / "config" / "sources" / "kenya_ppip.json"
    value = json.loads(path.read_text(encoding="utf-8"))
    return EngineConfig(
        source=value["source"], source_version=value["source_version"], api_version=value["api_version"],
        list_endpoints=tuple(value["list_endpoints"]), detail_endpoint=value["detail_endpoint"],
        per_page=value["per_page"], request_timeout_seconds=value["request_timeout_seconds"],
        concurrency=value["concurrency"], refill_rate_per_second=value["refill_rate_per_second"],
        jitter_seconds=value["jitter_seconds"], max_attempts=value["max_attempts"],
        max_backoff_seconds=value["max_backoff_seconds"], circuit_breaker_429_count=value["circuit_breaker_429_count"],
        circuit_breaker_pause_seconds=value["circuit_breaker_pause_seconds"], retry_statuses=tuple(value["retry_statuses"]),
    )


def _sha256(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def _now() -> float:
    return time.monotonic()


def _idempotency(*parts: object) -> str:
    return _sha256("|".join(str(part) for part in parts).encode())[:32]


class RateLimiter:
    def __init__(self, rate: float, jitter: float, *, clock: Callable[[], float] = _now, sleeper: Callable[[float], None] = time.sleep, randomizer: Callable[[], float] = random.random) -> None:
        self.interval = 1.0 / rate
        self.jitter = jitter
        self.clock = clock
        self.sleeper = sleeper
        self.randomizer = randomizer
        self.next_at = 0.0

    def wait(self) -> float:
        now = self.clock()
        delay = max(0.0, self.next_at - now) + self.randomizer() * self.jitter
        if delay:
            self.sleeper(delay)
        self.next_at = max(self.next_at, self.clock()) + self.interval
        return delay

    def slow_down(self, factor: float = 2.0) -> None:
        self.interval = min(60.0, self.interval * factor)


def classify_status(status: int | None, error: Exception | None, retry_statuses: tuple[int, ...]) -> tuple[bool, str]:
    if status in retry_statuses:
        return True, f"http_{status}"
    if status is not None:
        return False, f"http_{status}"
    if isinstance(error, (TimeoutError, urllib.error.URLError, ConnectionError)):
        return True, error.__class__.__name__
    return False, error.__class__.__name__ if error else "unknown"


def _create_ledger(connection: duckdb.DuckDBPyConnection) -> None:
    for table, definition in LEDGER_SCHEMA.items():
        connection.execute(f'CREATE TABLE IF NOT EXISTS "{table}" ({definition})')
    connection.execute("ALTER TABLE run_metadata ADD COLUMN IF NOT EXISTS started_at VARCHAR")
    connection.execute("ALTER TABLE run_metadata ADD COLUMN IF NOT EXISTS finished_at VARCHAR")
    connection.execute("ALTER TABLE request_jobs ADD COLUMN IF NOT EXISTS cache_hit BOOLEAN DEFAULT FALSE")


def _insert_job(connection: duckdb.DuckDBPyConnection, run: str, job_type: str, endpoint: str, url: str, params: dict, expected_ocid: str | None = None, external_id: str | None = None) -> None:
    job_id = _idempotency(run, job_type, endpoint, json.dumps(params, sort_keys=True), expected_ocid, external_id)
    now = utc_now()
    connection.execute("""INSERT INTO request_jobs (job_id, run_id, job_type, endpoint, url, params_json, expected_ocid, external_id, status, attempts, next_attempt_at, lease_owner, lease_until, http_status, error_class, error_message, response_hash, response_path, observed_ocid, created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'pending', 0, 0, NULL, NULL, NULL, NULL, NULL, NULL, NULL, NULL, ?, ?) ON CONFLICT (job_id) DO NOTHING""", [job_id, run, job_type, endpoint, url, json.dumps(params, sort_keys=True), expected_ocid, external_id, now, now])


def _ledger_path(roots, run: str) -> Path:
    path = roots.enriched / run
    path.mkdir(parents=True, exist_ok=True)
    (path / "responses").mkdir(exist_ok=True)
    return path / "ledger.duckdb"


def plan(country: str = "ke", *, limit: int = 25, config_path: Path | None = None) -> dict:
    if country != "ke":
        raise ValueError("The Kenya PPIP engine only supports country=ke")
    ensure_data_dirs(country)
    roots = country_paths(country)
    config = load_config(config_path)
    source_sha = source_hash(roots.raw / "ocds_full.jsonl.gz", roots.raw / "manifest.json")
    run = run_id(source_sha, "source-enrich")
    ledger_path = _ledger_path(roots, run)
    connection = duckdb.connect(str(ledger_path))
    _create_ledger(connection)
    connection.execute("INSERT INTO run_metadata (run_id, country, source_snapshot_sha256, config_json, created_at, status, detail_limit, resume_count) VALUES (?, ?, ?, ?, ?, 'planned', ?, 0)", [run, country, source_sha, json.dumps(config.__dict__), utc_now(), limit])
    for endpoint in config.list_endpoints:
        params = {"search": "", "perpage": config.per_page, "sortby": "", "order": "asc", "page": 1, "tender_ref": "", "title": "", "pe:name": "", "procurementMethod:title": "", "procurementCategory:title": "", "close_at": "", "published_at": "", "addendum_added": ""}
        _insert_job(connection, run, "list", endpoint, BASE_URL + endpoint, params)
    connection.close()
    return {"run_id": run, "country": country, "status": "planned", "detail_limit": limit, "ledger": str(ledger_path), "source_snapshot_sha256": source_sha}


def _fetch(url: str, params: dict, timeout: int) -> tuple[int, dict, bytes]:
    query = urllib.parse.urlencode(params) if params else ""
    request_url = url + ("?" + query if query else "")
    request = urllib.request.Request(request_url, headers={"User-Agent": "PursuitMap/0.1 durable-source-enrichment", "Accept": "application/json"})
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return response.status, dict(response.headers), response.read()
    except urllib.error.HTTPError as error:
        return error.code, dict(error.headers), error.read()


def _save_response(connection, run: str, job_id: str, url: str, status: int, headers: dict, payload: bytes, response_root: Path) -> tuple[str, str]:
    digest = _sha256(payload)
    path = response_root / f"{job_id}-{digest[:12]}.json"
    if not path.exists():
        path.write_bytes(payload)
    connection.execute("INSERT INTO source_responses VALUES (nextval('response_seq'), ?, ?, ?, ?, ?, ?, ?, ?, ?)", [run, job_id, url, utc_now(), status, headers.get("Content-Type"), digest, str(path), len(payload)])
    return digest, str(path)


def _record_event(connection, job_id: str, attempt: int, state: str, wait_seconds: float, status: int | None, retryable: bool, error_class: str | None, error_message: str | None, response_hash: str | None) -> None:
    connection.execute("INSERT INTO request_events VALUES (nextval('event_seq'), ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)", [job_id, attempt, state, wait_seconds, status, retryable, error_class, error_message, response_hash, utc_now()])


def _create_sequences(connection) -> None:
    connection.execute("CREATE SEQUENCE IF NOT EXISTS event_seq START 1")
    connection.execute("CREATE SEQUENCE IF NOT EXISTS response_seq START 1")
    connection.execute("CREATE SEQUENCE IF NOT EXISTS mapping_seq START 1")


def _cache_path(roots) -> Path:
    roots.enriched.mkdir(parents=True, exist_ok=True)
    return roots.enriched / "source-cache.duckdb"


def _cache_connection(roots) -> duckdb.DuckDBPyConnection:
    connection = duckdb.connect(str(_cache_path(roots)))
    for table, definition in CACHE_SCHEMA.items():
        connection.execute(f'CREATE TABLE IF NOT EXISTS "{table}" ({definition})')
    return connection


def _cache_key(job_type: str, url: str, params_json: str, expected_ocid: str | None) -> str:
    return _sha256("|".join((job_type, url, params_json, expected_ocid or "")).encode())


def _cache_lookup(cache, job_type: str, url: str, params_json: str, expected_ocid: str | None):
    key = _cache_key(job_type, url, params_json, expected_ocid)
    return cache.execute("SELECT cache_key, http_status, content_type, response_hash, response_path, observed_ocid, source_run_id FROM cached_responses WHERE cache_key = ? AND http_status = 200", [key]).fetchone()


def _cache_store(cache, job_type: str, url: str, params_json: str, expected_ocid: str | None, status: int, content_type: str | None, response_hash: str, response_path: str, observed_ocid: str | None, source_run_id: str) -> None:
    cache.execute("INSERT OR REPLACE INTO cached_responses VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)", [_cache_key(job_type, url, params_json, expected_ocid), job_type, url, params_json, expected_ocid, status, content_type, response_hash, response_path, observed_ocid, source_run_id, utc_now()])


def _list_success(connection, run: str, job: tuple, payload: bytes, response_hash: str, config: EngineConfig, detail_limit: int) -> None:
    job_id, _, _, endpoint, _, params_json, *_ = job
    data = json.loads(payload)
    records = data.get("data") or []
    page = int(json.loads(params_json).get("page", 1))
    canonical_root = canonical_root_for_run(connection, run)
    for record in records:
        ocid = record.get("ocid")
        external_id = str(record.get("id")) if record.get("id") is not None else None
        if not ocid or not external_id:
            continue
        match = connection.execute("SELECT count(*) FROM read_parquet(?) WHERE ocid = ?", [str(canonical_root / "tenders.parquet"), ocid]).fetchone()[0] > 0
        existing = connection.execute("SELECT count(*) FROM source_mappings WHERE run_id = ? AND ocid = ? AND external_id = ?", [run, ocid, external_id]).fetchone()[0]
        if not existing:
            connection.execute("INSERT INTO source_mappings VALUES (nextval('mapping_seq'), ?, ?, ?, ?, ?, ?, ?, ?, ?)", [run, endpoint, page, response_hash, external_id, ocid, record.get("tender_ref"), match, utc_now()])
        if match:
            _insert_job(connection, run, "detail", config.detail_endpoint, BASE_URL + config.detail_endpoint.format(id=external_id), {}, ocid, external_id)
    next_page = data.get("next_page_url")
    matched = connection.execute("SELECT count(DISTINCT expected_ocid) FROM request_jobs WHERE run_id = ? AND job_type = 'detail'", [run]).fetchone()[0]
    last_page = int(data.get("last_page") or page)
    if next_page and page < last_page and (detail_limit == 0 or matched < detail_limit):
        next_params = json.loads(params_json)
        next_params["page"] = page + 1
        _insert_job(connection, run, "list", endpoint, BASE_URL + endpoint, next_params)


def canonical_root_for_run(connection, run: str) -> Path:
    source_sha = connection.execute("SELECT source_snapshot_sha256 FROM run_metadata WHERE run_id = ?", [run]).fetchone()[0]
    del source_sha
    return canonical_root("ke")


def _materialize(connection, run: str, output_root: Path) -> dict:
    rows = []
    canonical = canonical_root("ke")
    source_sha = connection.execute("SELECT source_snapshot_sha256 FROM run_metadata WHERE run_id = ?", [run]).fetchone()[0]
    for job_id, url, response_path, expected_ocid, retrieved_at, http_status, response_hash in connection.execute("""SELECT j.job_id, j.url, j.response_path, j.expected_ocid, r.retrieved_at, r.http_status, r.response_hash
        FROM request_jobs j JOIN (SELECT *, row_number() OVER (PARTITION BY job_id ORDER BY response_id DESC) AS rn FROM source_responses) r ON r.job_id = j.job_id
        WHERE j.run_id = ? AND j.job_type = 'detail' AND j.status = 'succeeded' AND r.rn = 1 ORDER BY j.job_id""", [run]).fetchall():
        payload = Path(response_path).read_bytes()
        parsed = parse_tender_payload(payload)
        release_id = connection.execute("SELECT min(release_id) FROM read_parquet(?) WHERE ocid = ?", [str(canonical / "tenders.parquet"), expected_ocid]).fetchone()[0]
        rows.append((source_sha, "ke", expected_ocid, release_id, job_id, url, retrieved_at, http_status, response_hash, *(parsed.get(column) for column in SCHEMA[9:-1]), response_path))
    parquet = output_root / "source_enrichment.parquet"
    if rows:
        placeholders = ",".join("(" + ",".join("?" for _ in SCHEMA) + ")" for _ in rows)
        connection.execute(f"CREATE OR REPLACE TABLE source_enrichment AS SELECT * FROM (VALUES {placeholders}) AS t({','.join(SCHEMA)})", [value for row in rows for value in row])
    else:
        connection.execute("CREATE OR REPLACE TABLE source_enrichment AS SELECT " + ",".join(f"CAST(NULL AS VARCHAR) AS {column}" for column in SCHEMA) + " WHERE FALSE")
    connection.execute("COPY source_enrichment TO ? (FORMAT PARQUET, COMPRESSION ZSTD)", [str(parquet)])
    return {"rows": len(rows), "parquet": str(parquet)}


def execute(run: str, *, country: str = "ke", config_path: Path | None = None, sleep: Callable[[float], None] = time.sleep, randomizer: Callable[[], float] = random.random) -> dict:
    roots = country_paths(country)
    config = load_config(config_path)
    ledger_path = roots.enriched / run / "ledger.duckdb"
    if not ledger_path.exists():
        raise FileNotFoundError(f"Run not found: {run}")
    connection = duckdb.connect(str(ledger_path))
    _create_ledger(connection)
    _create_sequences(connection)
    cache = _cache_connection(roots)
    connection.execute("UPDATE run_metadata SET status = 'running', resume_count = resume_count + 1 WHERE run_id = ?", [run])
    started_at = connection.execute("SELECT started_at FROM run_metadata WHERE run_id = ?", [run]).fetchone()[0]
    if not started_at:
        started_at = utc_now()
        connection.execute("UPDATE run_metadata SET started_at = ? WHERE run_id = ?", [started_at, run])
    limiter = RateLimiter(config.refill_rate_per_second, config.jitter_seconds, sleeper=sleep, randomizer=randomizer)
    consecutive_429 = 0
    while True:
        job = connection.execute("SELECT * FROM request_jobs WHERE run_id = ? AND status IN ('pending','retryable_failed') AND next_attempt_at <= ? ORDER BY job_type, created_at, job_id LIMIT 1", [run, _now()]).fetchone()
        if job is None:
            next_ready = connection.execute("SELECT min(next_attempt_at) FROM request_jobs WHERE run_id = ? AND status IN ('pending','retryable_failed')", [run]).fetchone()[0]
            if next_ready is None:
                break
            sleep(max(0.0, next_ready - _now()))
            continue
        job_id, _, job_type, endpoint, url, params_json, expected_ocid, external_id, _, attempts, *_ = job
        attempt = attempts + 1
        wait_seconds = limiter.wait()
        connection.execute("UPDATE request_jobs SET status = 'running', attempts = ?, updated_at = ? WHERE job_id = ?", [attempt, utc_now(), job_id])
        try:
            cached = _cache_lookup(cache, job_type, url, params_json, expected_ocid)
            cache_hit = cached is not None
            if cache_hit:
                _, status, content_type, digest, path, observed_ocid, source_run_id = cached
                headers = {"Content-Type": content_type} if content_type else {}
                payload = Path(path).read_bytes()
                connection.execute("INSERT INTO source_responses VALUES (nextval('response_seq'), ?, ?, ?, ?, ?, ?, ?, ?, ?)", [run, job_id, url, utc_now(), status, content_type, digest, path, len(payload)])
                connection.execute("UPDATE request_jobs SET cache_hit = TRUE, updated_at = ? WHERE job_id = ?", [utc_now(), job_id])
            else:
                status, headers, payload = _fetch(url, json.loads(params_json), config.request_timeout_seconds)
                digest, path = _save_response(connection, run, job_id, url, status, headers, payload, roots.enriched / run / "responses")
            connection.execute("UPDATE request_jobs SET http_status = ?, response_hash = ?, response_path = ?, updated_at = ? WHERE job_id = ?", [status, digest, path, utc_now(), job_id])
            if status == 200:
                observed_ocid = None
                if job_type == "detail":
                    parsed = parse_tender_payload(payload)
                    observed_ocid = parsed.get("ocid")
                    if parsed.get("ocid") != expected_ocid:
                        raise ValueError("source_record_mismatch")
                connection.execute("UPDATE request_jobs SET status = 'succeeded', http_status = ?, response_hash = ?, response_path = ?, updated_at = ? WHERE job_id = ?", [status, digest, path, utc_now(), job_id])
                if not cache_hit:
                    _cache_store(cache, job_type, url, params_json, expected_ocid, status, headers.get("Content-Type"), digest, path, observed_ocid, run)
                _record_event(connection, job_id, attempt, "cache_hit" if cache_hit else "succeeded", wait_seconds, status, False, None, None, digest)
                if job_type == "list":
                    detail_limit = connection.execute("SELECT detail_limit FROM run_metadata WHERE run_id = ?", [run]).fetchone()[0]
                    _list_success(connection, run, job, payload, digest, config, detail_limit)
                consecutive_429 = 0
                continue
            retryable, error_class = classify_status(status, None, config.retry_statuses)
            if retryable and attempt < config.max_attempts:
                if status == 429:
                    consecutive_429 += 1
                    limiter.slow_down()
                    if consecutive_429 >= config.circuit_breaker_429_count:
                        sleep(config.circuit_breaker_pause_seconds)
                        consecutive_429 = 0
                retry_after = headers.get("Retry-After")
                delay = min(config.max_backoff_seconds, float(retry_after) if retry_after and retry_after.isdigit() else 2 ** attempt) + randomizer() * config.jitter_seconds
                connection.execute("UPDATE request_jobs SET status = 'retryable_failed', next_attempt_at = ?, http_status = ?, error_class = ?, error_message = ?, response_hash = ?, response_path = ?, updated_at = ? WHERE job_id = ?", [_now() + delay, status, error_class, "retryable HTTP response", digest, path, utc_now(), job_id])
                _record_event(connection, job_id, attempt, "retryable_failed", wait_seconds, status, True, error_class, "retryable HTTP response", digest)
            else:
                connection.execute("UPDATE request_jobs SET status = 'permanent_failed', http_status = ?, error_class = ?, error_message = ?, response_hash = ?, response_path = ?, updated_at = ? WHERE job_id = ?", [status, error_class, "permanent HTTP response", digest, path, utc_now(), job_id])
                _record_event(connection, job_id, attempt, "permanent_failed", wait_seconds, status, False, error_class, "permanent HTTP response", digest)
        except ValueError as error:
            connection.execute("UPDATE request_jobs SET status = 'permanent_failed', error_class = 'validation', error_message = ?, updated_at = ? WHERE job_id = ?", [str(error), utc_now(), job_id])
            _record_event(connection, job_id, attempt, "permanent_failed", wait_seconds, status if 'status' in locals() else None, False, "validation", str(error), None)
        except Exception as error:
            retryable, error_class = classify_status(None, error, config.retry_statuses)
            status = "retryable_failed" if retryable and attempt < config.max_attempts else "permanent_failed"
            connection.execute("UPDATE request_jobs SET status = ?, error_class = ?, error_message = ?, next_attempt_at = ?, updated_at = ? WHERE job_id = ?", [status, error_class, str(error), _now() + min(config.max_backoff_seconds, 2 ** attempt), utc_now(), job_id])
            _record_event(connection, job_id, attempt, status, wait_seconds, None, status == "retryable_failed", error_class, str(error), None)
    output_root = roots.enriched / run
    materialized = _materialize(connection, run, output_root)
    finished_at = utc_now()
    connection.execute("UPDATE run_metadata SET status = 'complete', finished_at = ? WHERE run_id = ?", [finished_at, run])
    counts = {row[0]: row[1] for row in connection.execute("SELECT status, count(*) FROM request_jobs WHERE run_id = ? GROUP BY 1", [run]).fetchall()}
    source_sha = connection.execute("SELECT source_snapshot_sha256 FROM run_metadata WHERE run_id = ?", [run]).fetchone()[0]
    mapping_counts = {str(row[0]).lower(): row[1] for row in connection.execute("SELECT canonical_match, count(*) FROM source_mappings WHERE run_id = ? GROUP BY 1", [run]).fetchall()}
    detail_total = connection.execute("SELECT count(*) FROM request_jobs WHERE run_id = ? AND job_type = 'detail'", [run]).fetchone()[0]
    status_counts = {str(row[0]): row[1] for row in connection.execute("SELECT http_status, count(*) FROM source_responses WHERE run_id = ? GROUP BY 1", [run]).fetchall()}
    wait_stats = connection.execute("SELECT coalesce(avg(wait_seconds), 0), coalesce(quantile_cont(wait_seconds, 0.95), 0), count(*) FILTER (WHERE error_class = 'http_429') FROM request_events WHERE job_id IN (SELECT job_id FROM request_jobs WHERE run_id = ?)", [run]).fetchone()
    field_coverage = {}
    parquet = Path(materialized["parquet"])
    if parquet.exists() and materialized["rows"]:
        for column in ("title", "procuring_entity_name", "procuring_entity_pin", "procurement_method", "procurement_category", "published_date_raw", "close_date_raw", "financial_year", "attachments_json"):
            field_coverage[column] = connection.execute(f"SELECT count(*) FILTER (WHERE {column} IS NOT NULL AND trim(cast({column} AS VARCHAR)) <> '') FROM read_parquet(?)", [str(parquet)]).fetchone()[0]
    elapsed_seconds = max(0.0, (datetime.fromisoformat(finished_at) - datetime.fromisoformat(started_at)).total_seconds())
    response_count = connection.execute("SELECT count(*) FROM source_responses WHERE run_id = ?", [run]).fetchone()[0]
    cache_hits = connection.execute("SELECT count(*) FROM request_jobs WHERE run_id = ? AND cache_hit = TRUE", [run]).fetchone()[0]
    report = {"run_id": run, "country": country, "source_snapshot_sha256": source_sha, "source": config.source, "source_version": config.source_version, "api_version": config.api_version, "rate_policy": {"concurrency": config.concurrency, "refill_rate_per_second": config.refill_rate_per_second, "jitter_seconds": config.jitter_seconds}, "job_counts": {key: counts.get(key, 0) for key in ("succeeded", "pending", "retryable_failed", "permanent_failed")}, "mapping_counts": mapping_counts, "mapping_total": sum(mapping_counts.values()), "detail_jobs": detail_total, "detail_match_rate": materialized["rows"] / detail_total if detail_total else 0, "field_coverage": field_coverage, "http_status_counts": status_counts, "accepted_detail_rows": materialized["rows"], "response_count": response_count, "network_requests": response_count - cache_hits, "cache_hits": cache_hits, "cache_path": str(_cache_path(roots)), "duplicate_mapping_rows": connection.execute("SELECT count(*) - count(DISTINCT ocid || '|' || external_id) FROM source_mappings WHERE run_id = ?", [run]).fetchone()[0], "average_wait_seconds": wait_stats[0], "p95_wait_seconds": wait_stats[1], "effective_request_rate_per_second": response_count / elapsed_seconds if elapsed_seconds else 0, "rate_limit_events": wait_stats[2], "elapsed_seconds": elapsed_seconds, "output_root": str(output_root), "ledger": str(ledger_path), "status": "pass" if not counts.get("permanent_failed") and not counts.get("retryable_failed") else "warn"}
    write_run_manifest("source-enrich", source_sha, {"country": country, "report": report, "ledger": str(ledger_path), "output_root": str(output_root)}, run=run, working_root=roots.working)
    (output_root / "source_enrichment_execution_report.json").write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    (output_root / "source_enrichment_execution_report.md").write_text(render_report(report), encoding="utf-8")
    cache.close()
    connection.close()
    return report


def render_report(report: dict) -> str:
    lines = ["# Kenya PPIP source-enrichment execution report", "", f"Run: `{report['run_id']}`", f"Status: `{report['status']}`", "", "## Counts", ""]
    lines.extend(f"- `{key}`: {value}" for key, value in report["job_counts"].items())
    lines.extend(["", "## Mapping", ""])
    lines.extend(f"- `{key}`: {value}" for key, value in report["mapping_counts"].items())
    lines.extend(["", f"Accepted detail rows: {report['accepted_detail_rows']}", f"Stored responses: {report['response_count']}", f"Network requests: {report['network_requests']}", f"Cache hits: {report['cache_hits']}", f"Detail match rate: {report['detail_match_rate']:.3f}", f"Average wait: {report['average_wait_seconds']:.3f}s", f"P95 wait: {report['p95_wait_seconds']:.3f}s", f"Rate-limit events: {report['rate_limit_events']}", ""])
    lines.extend(["## Field coverage", ""])
    lines.extend(f"- `{key}`: {value}" for key, value in report["field_coverage"].items())
    return "\n".join(lines)


def report(run: str, country: str = "ke") -> dict:
    path = country_paths(country).enriched / run / "source_enrichment_execution_report.json"
    if not path.exists():
        raise FileNotFoundError(path)
    return json.loads(path.read_text(encoding="utf-8"))


def resume(run: str, **kwargs) -> dict:
    return execute(run, **kwargs)


def compatibility_enrich_source(country: str = "ke", *, limit: int = 25) -> dict:
    planned = plan(country, limit=limit)
    return execute(planned["run_id"], country=country)
