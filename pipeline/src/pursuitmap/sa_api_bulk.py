from __future__ import annotations

import hashlib
import json
import signal
import time
import urllib.parse
from pathlib import Path

import duckdb

from .paths import canonical_root, country_paths, ensure_data_dirs
from .provenance import source_hash, utc_now, write_run_manifest
from .sa_api_enrichment import _fetch, _sha256


BASE_URL = "https://ocds-api.etenders.gov.za"
PAGE_SIZE = 1000


def _setup(connection: duckdb.DuckDBPyConnection) -> None:
    connection.execute("CREATE SEQUENCE IF NOT EXISTS event_seq START 1")
    connection.execute("CREATE TABLE IF NOT EXISTS bulk_jobs (job_id VARCHAR PRIMARY KEY, run_id VARCHAR, page INTEGER, date_from VARCHAR, date_to VARCHAR, url VARCHAR, status VARCHAR, attempts INTEGER, http_status INTEGER, response_hash VARCHAR, response_path VARCHAR, error_class VARCHAR, error_message VARCHAR, created_at VARCHAR, updated_at VARCHAR)")
    connection.execute("CREATE TABLE IF NOT EXISTS bulk_events (event_id BIGINT, job_id VARCHAR, attempt INTEGER, state VARCHAR, http_status INTEGER, response_hash VARCHAR, error_class VARCHAR, error_message VARCHAR, created_at VARCHAR)")
    connection.execute("CREATE TABLE IF NOT EXISTS bulk_responses (response_id BIGINT, run_id VARCHAR, job_id VARCHAR, url VARCHAR, retrieved_at VARCHAR, http_status INTEGER, response_hash VARCHAR, response_path VARCHAR, response_bytes BIGINT)")


def _job_id(run: str, url: str) -> str:
    return hashlib.sha256(f"{run}|{url}".encode()).hexdigest()[:32]


def _url(date_from: str, date_to: str, page: int) -> str:
    query = urllib.parse.urlencode({"PageNumber": page, "PageSize": PAGE_SIZE, "dateFrom": date_from, "dateTo": date_to})
    return f"{BASE_URL}/api/OCDSReleases?{query}"


def _write_progress(output_root: Path, run_id: str, connection: duckdb.DuckDBPyConnection, state: str) -> None:
    counts = {row[0]: row[1] for row in connection.execute("SELECT status,count(*) FROM bulk_jobs WHERE run_id=? GROUP BY 1", [run_id]).fetchall()}
    active = connection.execute("SELECT date_from,date_to,page,attempts FROM bulk_jobs WHERE run_id=? AND status='running' LIMIT 1", [run_id]).fetchone()
    progress = {
        "run_id": run_id,
        "state": state,
        "updated_at": utc_now(),
        "job_counts": counts,
        "responses": connection.execute("SELECT count(*) FROM bulk_responses WHERE run_id=?", [run_id]).fetchone()[0],
        "active_job": {"date_from": active[0], "date_to": active[1], "page": active[2], "attempts": active[3]} if active else None,
    }
    (output_root / "progress.json").write_text(json.dumps(progress, indent=2) + "\n", encoding="utf-8")


def _load_occurrences(connection: duckdb.DuckDBPyConnection, source_sha: str, run_id: str, output_root: Path) -> list[tuple]:
    occurrences = []
    rows = connection.execute(
        "SELECT DISTINCT r.response_hash,r.response_path,j.date_from,j.date_to "
        "FROM bulk_responses r JOIN bulk_jobs j ON j.job_id=r.job_id "
        "WHERE r.run_id=? AND r.http_status=200 ORDER BY r.response_hash",
        [run_id],
    ).fetchall()
    for digest, response_path, date_from, date_to in rows:
        payload = Path(response_path).read_bytes()
        data = json.loads(payload)
        for release in data.get("releases", []):
            if release.get("ocid"):
                occurrences.append((source_sha, run_id, release.get("ocid"), release.get("id"), release.get("date"), json.dumps(release, sort_keys=True), digest, str(output_root / "responses" / f"{digest}.json"), date_from, date_to))
    return occurrences


def plan() -> dict:
    ensure_data_dirs("za")
    roots = country_paths("za")
    source_sha = source_hash(roots.raw / "ocds_full.jsonl.gz", roots.raw / "manifest.json")
    run = f"sa-api-bulk-{time.strftime('%Y%m%dT%H%M%SZ', time.gmtime())}-{source_sha[:12]}"
    output_root = roots.enriched / run
    output_root.mkdir(parents=True, exist_ok=False)
    (output_root / "responses").mkdir()
    connection = duckdb.connect(str(output_root / "ledger.duckdb"))
    _setup(connection)
    months = connection.execute("SELECT DISTINCT strftime(try_cast(release_date AS DATE), '%Y-%m') FROM read_parquet(?) WHERE release_date IS NOT NULL ORDER BY 1", [str(canonical_root("za") / "releases.parquet")]).fetchall()
    for (month,) in months:
        date_from = f"{month}-01"
        date_to = (connection.execute("SELECT (date_trunc('month', ?::DATE) + interval '1 month' - interval '1 day')::DATE", [date_from]).fetchone()[0]).isoformat()
        url = _url(date_from, date_to, 1)
        connection.execute("INSERT INTO bulk_jobs VALUES (?, ?, 1, ?, ?, ?, 'pending', 0, NULL, NULL, NULL, NULL, NULL, ?, ?)", [_job_id(run, url), run, date_from, date_to, url, utc_now(), utc_now()])
    connection.close()
    return {"run_id": run, "source_snapshot_sha256": source_sha, "month_jobs": len(months), "output_root": str(output_root)}


def run(run_id: str, *, timeout: int = 90, rate: float = 1.0) -> dict:
    roots = country_paths("za")
    output_root = roots.enriched / run_id
    connection = duckdb.connect(str(output_root / "ledger.duckdb"))
    _setup(connection)
    prior_progress = output_root / "progress.json"
    if prior_progress.exists():
        previous = json.loads(prior_progress.read_text(encoding="utf-8"))
        if previous.get("state") == "running":
            _write_progress(output_root, run_id, connection, "interrupted")
    connection.execute("UPDATE bulk_jobs SET status='retryable_failed', error_class='LeaseRecovery', error_message='recovered after interrupted run', updated_at=? WHERE run_id=? AND status='running'", [utc_now(), run_id])
    source_sha = connection.execute("SELECT ?", [source_hash(roots.raw / "ocds_full.jsonl.gz", roots.raw / "manifest.json")]).fetchone()[0]
    _write_progress(output_root, run_id, connection, "running")

    def mark_interrupted(signum, frame):
        _write_progress(output_root, run_id, connection, "interrupted")
        raise KeyboardInterrupt(f"received signal {signum}")

    signal.signal(signal.SIGINT, mark_interrupted)
    signal.signal(signal.SIGTERM, mark_interrupted)
    occurrences = []
    next_at = 0.0
    while True:
        job = connection.execute("SELECT job_id,page,date_from,date_to,url,attempts FROM bulk_jobs WHERE run_id=? AND status IN ('pending','retryable_failed') ORDER BY date_from,page LIMIT 1", [run_id]).fetchone()
        if job is None:
            break
        job_id, page, date_from, date_to, url, attempts = job
        delay = max(0.0, next_at - time.monotonic())
        if delay:
            time.sleep(delay)
        next_at = max(next_at, time.monotonic()) + 1.0 / rate
        attempt = attempts + 1
        connection.execute("UPDATE bulk_jobs SET status='running', attempts=?, updated_at=? WHERE job_id=?", [attempt, utc_now(), job_id])
        try:
            status, _, payload = _fetch(url, timeout)
            digest = _sha256(payload)
            path = output_root / "responses" / f"{digest}.json"
            if not path.exists():
                path.write_bytes(payload)
            connection.execute("INSERT INTO bulk_responses VALUES (nextval('event_seq'), ?, ?, ?, ?, ?, ?, ?, ?)", [run_id, job_id, url, utc_now(), status, digest, str(path), len(payload)])
            data = json.loads(payload)
            if status != 200 or not isinstance(data.get("releases"), list):
                raise ValueError(f"invalid_bulk_response_http_{status}")
            for release in data["releases"]:
                if release.get("ocid"):
                    occurrences.append((source_sha, run_id, release.get("ocid"), release.get("id"), release.get("date"), json.dumps(release, sort_keys=True), digest, str(path), date_from, date_to))
            next_url = (data.get("links") or {}).get("next")
            if next_url:
                parsed = urllib.parse.parse_qs(urllib.parse.urlsplit(next_url).query)
                next_page = int(parsed["PageNumber"][0])
                if not connection.execute("SELECT 1 FROM bulk_jobs WHERE run_id=? AND url=?", [run_id, next_url]).fetchone():
                    connection.execute("INSERT INTO bulk_jobs VALUES (?, ?, ?, ?, ?, ?, 'pending', 0, NULL, NULL, NULL, NULL, NULL, ?, ?)", [_job_id(run_id, next_url), run_id, next_page, date_from, date_to, next_url, utc_now(), utc_now()])
            connection.execute("UPDATE bulk_jobs SET status='succeeded', http_status=?, response_hash=?, response_path=?, updated_at=? WHERE job_id=?", [status, digest, str(path), utc_now(), job_id])
            connection.execute("INSERT INTO bulk_events VALUES (nextval('event_seq'), ?, ?, 'succeeded', ?, ?, NULL, NULL, ?)", [job_id, attempt, status, digest, utc_now()])
            _write_progress(output_root, run_id, connection, "running")
        except Exception as error:
            state = "retryable_failed" if attempt < 6 else "permanent_failed"
            connection.execute("UPDATE bulk_jobs SET status=?, error_class=?, error_message=?, updated_at=? WHERE job_id=?", [state, type(error).__name__, str(error), utc_now(), job_id])
            connection.execute("INSERT INTO bulk_events VALUES (nextval('event_seq'), ?, ?, ?, NULL, NULL, ?, ?, ?)", [job_id, attempt, state, type(error).__name__, str(error), utc_now()])
            _write_progress(output_root, run_id, connection, "running")
    occurrences = _load_occurrences(connection, source_sha, run_id, output_root)
    columns = "source_snapshot_sha256,run_id,ocid,release_id,release_date,raw_json,response_hash,response_path,date_from,date_to"
    connection.execute("CREATE OR REPLACE TABLE sa_api_bulk_releases AS SELECT * FROM (VALUES " + ",".join("(" + ",".join("?" for _ in columns.split(",")) + ")" for _ in occurrences) + f") AS t({columns})" if occurrences else "CREATE OR REPLACE TABLE sa_api_bulk_releases AS SELECT CAST(NULL AS VARCHAR) AS ocid WHERE FALSE", [value for row in occurrences for value in row] if occurrences else [])
    parquet = output_root / "sa_api_bulk_releases.parquet"
    connection.execute("COPY sa_api_bulk_releases TO ? (FORMAT PARQUET, COMPRESSION ZSTD)", [str(parquet)])
    counts = {row[0]: row[1] for row in connection.execute("SELECT status,count(*) FROM bulk_jobs WHERE run_id=? GROUP BY 1", [run_id]).fetchall()}
    canonical_count = connection.execute("SELECT count(DISTINCT ocid) FROM read_parquet(?)", [str(canonical_root("za") / "releases.parquet")]).fetchone()[0]
    matched = connection.execute("SELECT count(DISTINCT ocid) FROM sa_api_bulk_releases WHERE ocid IN (SELECT ocid FROM read_parquet(?))", [str(canonical_root("za") / "releases.parquet")]).fetchone()[0]
    report = {"run_id": run_id, "source_snapshot_sha256": source_sha, "job_counts": counts, "release_observations": len(occurrences), "unique_observed_ocids": len({row[2] for row in occurrences}), "canonical_ocids": canonical_count, "canonical_matches": matched, "coverage": matched / canonical_count if canonical_count else 0, "parquet": str(parquet), "status": "pass" if not counts.get("permanent_failed") and not counts.get("retryable_failed") else "warn"}
    (output_root / "sa_api_bulk_report.json").write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    write_run_manifest("sa-api-bulk", source_sha, {"report": report, "output_root": str(output_root)}, run=run_id, working_root=roots.working)
    _write_progress(output_root, run_id, connection, "complete")
    connection.close()
    return report


def report(run_id: str) -> dict:
    path = country_paths("za").enriched / run_id / "sa_api_bulk_report.json"
    if not path.exists():
        raise FileNotFoundError(path)
    return json.loads(path.read_text(encoding="utf-8"))
