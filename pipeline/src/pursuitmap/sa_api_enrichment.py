from __future__ import annotations

import hashlib
import json
import random
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Callable

import duckdb

from .paths import canonical_root, country_paths, ensure_data_dirs
from .provenance import source_hash, utc_now, write_run_manifest


CONFIG_PATH = Path(__file__).resolve().parents[3] / "config" / "sources" / "south_africa_ocds_api.json"
RETRY_STATUSES = (408, 425, 429, 500, 502, 503, 504)
LEDGER_SCHEMA = {
    "run_metadata": "run_id VARCHAR PRIMARY KEY, source_snapshot_sha256 VARCHAR, config_json VARCHAR, status VARCHAR, requested_limit INTEGER, created_at VARCHAR, finished_at VARCHAR",
    "request_jobs": "job_id VARCHAR PRIMARY KEY, run_id VARCHAR, ocid VARCHAR, url VARCHAR, status VARCHAR, attempts INTEGER, http_status INTEGER, error_class VARCHAR, error_message VARCHAR, response_hash VARCHAR, response_path VARCHAR, observed_ocid VARCHAR, cache_hit BOOLEAN, created_at VARCHAR, updated_at VARCHAR",
    "request_events": "event_id BIGINT, job_id VARCHAR, attempt INTEGER, state VARCHAR, http_status INTEGER, retryable BOOLEAN, error_class VARCHAR, error_message VARCHAR, response_hash VARCHAR, created_at VARCHAR",
    "source_responses": "response_id BIGINT, run_id VARCHAR, job_id VARCHAR, url VARCHAR, retrieved_at VARCHAR, http_status INTEGER, content_type VARCHAR, response_hash VARCHAR, response_path VARCHAR, response_bytes BIGINT",
}


def _sha256(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def _job_id(run: str, ocid: str) -> str:
    return _sha256(f"{run}|{ocid}".encode())[:32]


def _cache_key(ocid: str) -> str:
    return _sha256(f"etenders-ocds-api-v1|{ocid}".encode())


def _load_config() -> dict:
    return json.loads(CONFIG_PATH.read_text(encoding="utf-8"))


def _setup(connection: duckdb.DuckDBPyConnection) -> None:
    connection.execute("CREATE SEQUENCE IF NOT EXISTS event_seq START 1")
    connection.execute("CREATE SEQUENCE IF NOT EXISTS response_seq START 1")
    for name, definition in LEDGER_SCHEMA.items():
        connection.execute(f'CREATE TABLE IF NOT EXISTS "{name}" ({definition})')


def _cache_connection(roots) -> duckdb.DuckDBPyConnection:
    cache = duckdb.connect(str(roots.enriched / "sa-api-cache.duckdb"))
    cache.execute("CREATE TABLE IF NOT EXISTS responses (cache_key VARCHAR PRIMARY KEY, ocid VARCHAR, http_status INTEGER, content_type VARCHAR, response_hash VARCHAR, response_path VARCHAR, observed_ocid VARCHAR, cached_at VARCHAR)")
    return cache


def _write_progress(connection: duckdb.DuckDBPyConnection, output_root: Path, run_id: str, phase: str) -> None:
    counts = {row[0]: row[1] for row in connection.execute("SELECT status,count(*) FROM request_jobs WHERE run_id=? GROUP BY 1", [run_id]).fetchall()}
    value = {"run_id": run_id, "phase": phase, "updated_at": utc_now(), "job_counts": counts, "materialization": str(output_root / "sa_api_tender_details.parquet")}
    temporary = output_root / "progress.json.tmp"
    temporary.write_text(json.dumps(value, indent=2) + "\n", encoding="utf-8")
    temporary.replace(output_root / "progress.json")


def plan(*, limit: int = 25) -> dict:
    ensure_data_dirs("za")
    roots = country_paths("za")
    config = _load_config()
    source_sha = source_hash(roots.raw / "ocds_full.jsonl.gz", roots.raw / "manifest.json")
    run = f"sa-api-enrich-{time.strftime('%Y%m%dT%H%M%SZ', time.gmtime())}-{source_sha[:12]}"
    output_root = roots.enriched / run
    output_root.mkdir(parents=True, exist_ok=False)
    (output_root / "responses").mkdir()
    connection = duckdb.connect(str(output_root / "ledger.duckdb"))
    _setup(connection)
    ocids = [row[0] for row in connection.execute("SELECT DISTINCT ocid FROM read_parquet(?) WHERE ocid IS NOT NULL", [str(canonical_root("za") / "tenders.parquet")]).fetchall()]
    ocids = sorted(ocids, key=lambda value: hashlib.sha256(value.encode()).hexdigest())[:limit]
    connection.execute("INSERT INTO run_metadata VALUES (?, ?, ?, 'planned', ?, ?, NULL)", [run, source_sha, json.dumps(config, sort_keys=True), limit, utc_now()])
    for ocid in ocids:
        job_id = _job_id(run, ocid)
        url = config["base_url"] + config["detail_endpoint"].format(ocid=ocid)
        connection.execute("INSERT INTO request_jobs VALUES (?, ?, ?, ?, 'pending', 0, NULL, NULL, NULL, NULL, NULL, NULL, FALSE, ?, ?)", [job_id, run, ocid, url, utc_now(), utc_now()])
    connection.close()
    return {"run_id": run, "source_snapshot_sha256": source_sha, "requested": len(ocids), "output_root": str(output_root), "ledger": str(output_root / "ledger.duckdb")}


def _fetch(url: str, timeout: int) -> tuple[int, dict, bytes]:
    request = urllib.request.Request(url, headers={"User-Agent": "PursuitMap/0.1 sa-api-enrichment", "Accept": "application/json"})
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return response.status, dict(response.headers), response.read()
    except urllib.error.HTTPError as error:
        return error.code, dict(error.headers), error.read()


def _save(connection, run: str, job_id: str, url: str, status: int, headers: dict, payload: bytes, root: Path) -> tuple[str, str]:
    digest = _sha256(payload)
    path = root / "responses" / f"{digest}.json"
    if not path.exists():
        path.write_bytes(payload)
    connection.execute("INSERT INTO source_responses VALUES (nextval('response_seq'), ?, ?, ?, ?, ?, ?, ?, ?, ?)", [run, job_id, url, utc_now(), status, headers.get("Content-Type"), digest, str(path), len(payload)])
    return digest, str(path)


def _materialize(connection, run: str, output_root: Path, source_sha: str) -> dict:
    rows = []
    for job_id, ocid, response_path, response_hash, retrieved_at in connection.execute("SELECT j.job_id, j.ocid, j.response_path, j.response_hash, r.retrieved_at FROM request_jobs j JOIN (SELECT *, row_number() OVER (PARTITION BY job_id ORDER BY response_id DESC) AS rn FROM source_responses) r ON r.job_id=j.job_id AND r.rn=1 WHERE j.run_id=? AND j.status='succeeded'", [run]).fetchall():
        release = json.loads(Path(response_path).read_text(encoding="utf-8"))
        tender = release.get("tender") or {}
        contact = tender.get("contactPerson") or {}
        briefing = tender.get("briefingSession") or {}
        rows.append((source_sha, run, ocid, release.get("id"), release.get("date"), tender.get("province"), tender.get("deliveryLocation"), tender.get("specialConditions"), json.dumps(contact, sort_keys=True), json.dumps(briefing, sort_keys=True), json.dumps(tender.get("tenderers") or [], sort_keys=True), json.dumps(release.get("parties") or [], sort_keys=True), response_hash, response_path, retrieved_at))
    columns = "source_snapshot_sha256,run_id,ocid,release_id,release_date,province,delivery_location,special_conditions,contact_json,briefing_session_json,tenderers_json,parties_json,response_hash,response_path,retrieved_at"
    connection.execute("CREATE OR REPLACE TABLE sa_api_tender_details AS SELECT * FROM (VALUES " + ",".join("(" + ",".join("?" for _ in columns.split(",")) + ")" for _ in rows) + f") AS t({columns})" if rows else "CREATE OR REPLACE TABLE sa_api_tender_details AS SELECT CAST(NULL AS VARCHAR) AS ocid WHERE FALSE", [value for row in rows for value in row] if rows else [])
    parquet = output_root / "sa_api_tender_details.parquet"
    connection.execute("COPY sa_api_tender_details TO ? (FORMAT PARQUET, COMPRESSION ZSTD)", [str(parquet)])
    coverage = {}
    if rows:
        for column in ("province", "delivery_location", "special_conditions", "contact_json", "briefing_session_json", "tenderers_json", "parties_json"):
            coverage[column] = connection.execute(f"SELECT count(*) FILTER (WHERE {column} IS NOT NULL AND trim({column}) NOT IN ('', '{{}}', '[]')) FROM sa_api_tender_details").fetchone()[0]
    return {"rows": len(rows), "parquet": str(parquet), "field_coverage": coverage}


def run(run_id: str, *, timeout: int = 30, rate: float = 1.0, jitter: float = 1.0, max_attempts: int = 6, sleep: Callable[[float], None] = time.sleep, randomizer: Callable[[], float] = random.random) -> dict:
    roots = country_paths("za")
    output_root = roots.enriched / run_id
    connection = duckdb.connect(str(output_root / "ledger.duckdb"))
    _setup(connection)
    cache = _cache_connection(roots)
    source_sha = connection.execute("SELECT source_snapshot_sha256 FROM run_metadata WHERE run_id=?", [run_id]).fetchone()[0]
    connection.execute("UPDATE request_jobs SET status='pending', updated_at=? WHERE run_id=? AND status='running'", [utc_now(), run_id])
    connection.execute("UPDATE run_metadata SET status='running' WHERE run_id=?", [run_id])
    _write_progress(connection, output_root, run_id, "running")
    next_at = 0.0
    while True:
        job = connection.execute("SELECT job_id, ocid, url, attempts FROM request_jobs WHERE run_id=? AND status IN ('pending','retryable_failed') ORDER BY ocid LIMIT 1", [run_id]).fetchone()
        if job is None:
            break
        job_id, ocid, url, attempts = job
        wait = max(0.0, next_at - time.monotonic()) + randomizer() * jitter
        if wait:
            sleep(wait)
        next_at = max(next_at, time.monotonic()) + 1.0 / rate
        attempt = attempts + 1
        connection.execute("UPDATE request_jobs SET status='running', attempts=?, updated_at=? WHERE job_id=?", [attempt, utc_now(), job_id])
        cached = cache.execute("SELECT http_status,content_type,response_hash,response_path,observed_ocid FROM responses WHERE cache_key=? AND http_status=200", [_cache_key(ocid)]).fetchone()
        try:
            if cached:
                status, content_type, digest, path, observed = cached
                payload = Path(path).read_bytes()
                connection.execute("UPDATE request_jobs SET cache_hit=TRUE WHERE job_id=?", [job_id])
            else:
                status, headers, payload = _fetch(url, timeout)
                digest, path = _save(connection, run_id, job_id, url, status, headers, payload, output_root)
                content_type, observed = headers.get("Content-Type"), None
            if status == 200:
                release = json.loads(payload)
                observed = release.get("ocid")
                if observed != ocid or not release.get("id") or not isinstance(release.get("tender"), dict):
                    raise ValueError("source_record_mismatch_or_invalid_release")
                if cached:
                    connection.execute("INSERT INTO source_responses VALUES (nextval('response_seq'), ?, ?, ?, ?, ?, ?, ?, ?, ?)", [run_id, job_id, url, utc_now(), status, content_type, digest, path, len(payload)])
                connection.execute("UPDATE request_jobs SET status='succeeded', http_status=?, response_hash=?, response_path=?, observed_ocid=?, updated_at=? WHERE job_id=?", [status, digest, path, observed, utc_now(), job_id])
                cache.execute("INSERT OR REPLACE INTO responses VALUES (?, ?, ?, ?, ?, ?, ?, ?)", [_cache_key(ocid), ocid, status, content_type, digest, path, observed, utc_now()])
                state, retryable, error_class, error_message = "succeeded", False, None, None
            else:
                retryable = status in RETRY_STATUSES and attempt < max_attempts
                state, error_class, error_message = ("retryable_failed" if retryable else "permanent_failed"), f"http_{status}", "HTTP response"
                connection.execute("UPDATE request_jobs SET status=?, http_status=?, error_class=?, error_message=?, response_hash=?, response_path=?, updated_at=? WHERE job_id=?", [state, status, error_class, error_message, digest, path, utc_now(), job_id])
            connection.execute("INSERT INTO request_events VALUES (nextval('event_seq'), ?, ?, ?, ?, ?, ?, ?, ?, ?)", [job_id, attempt, state, status, retryable, error_class, error_message, digest, utc_now()])
        except (ValueError, json.JSONDecodeError) as error:
            connection.execute("UPDATE request_jobs SET status='permanent_failed', error_class='validation', error_message=?, updated_at=? WHERE job_id=?", [str(error), utc_now(), job_id])
            connection.execute("INSERT INTO request_events VALUES (nextval('event_seq'), ?, ?, 'permanent_failed', NULL, FALSE, 'validation', ?, NULL, ?)", [job_id, attempt, str(error), utc_now()])
        except Exception as error:
            state = "retryable_failed" if attempt < max_attempts else "permanent_failed"
            connection.execute("UPDATE request_jobs SET status=?, error_class=?, error_message=?, updated_at=? WHERE job_id=?", [state, type(error).__name__, str(error), utc_now(), job_id])
            connection.execute("INSERT INTO request_events VALUES (nextval('event_seq'), ?, ?, ?, NULL, ?, ?, ?, NULL, ?)", [job_id, attempt, state, state == "retryable_failed", type(error).__name__, str(error), utc_now()])
        _write_progress(connection, output_root, run_id, "running")
    materialized = _materialize(connection, run_id, output_root, source_sha)
    counts = {row[0]: row[1] for row in connection.execute("SELECT status,count(*) FROM request_jobs WHERE run_id=? GROUP BY 1", [run_id]).fetchall()}
    report = {"run_id": run_id, "source_snapshot_sha256": source_sha, "job_counts": counts, "accepted_rows": materialized["rows"], "field_coverage": materialized["field_coverage"], "cache_hits": connection.execute("SELECT count(*) FROM request_jobs WHERE run_id=? AND cache_hit", [run_id]).fetchone()[0], "output_root": str(output_root), "status": "pass" if not counts.get("permanent_failed") and not counts.get("retryable_failed") else "warn"}
    (output_root / "sa_api_enrichment_report.json").write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    connection.execute("UPDATE run_metadata SET status=?, finished_at=? WHERE run_id=?", [report["status"], utc_now(), run_id])
    _write_progress(connection, output_root, run_id, report["status"])
    write_run_manifest("sa-api-enrich", source_sha, {"report": report, "output_root": str(output_root)}, run=run_id, working_root=roots.working)
    cache.close()
    connection.close()
    return report


def report(run_id: str) -> dict:
    path = country_paths("za").enriched / run_id / "sa_api_enrichment_report.json"
    if not path.exists():
        raise FileNotFoundError(path)
    return json.loads(path.read_text(encoding="utf-8"))
