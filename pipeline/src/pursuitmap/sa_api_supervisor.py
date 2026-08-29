from __future__ import annotations

import concurrent.futures
import hashlib
import json
import signal
import threading
import time
from pathlib import Path

import duckdb

from .paths import canonical_root, country_paths
from .provenance import source_hash, utc_now, write_run_manifest
from .sa_api_enrichment import _cache_connection, _cache_key, _sha256
from .http_client import HttpClient, HttpPolicy


RETRY_STATUSES = {408, 425, 429, 500, 502, 503, 504}
CAPACITY_LEVELS = (1, 2, 4, 8)
MAX_ATTEMPTS = 6
ZERO_YIELD_LIMIT = 3
FLUSHABLE_FAILURES = frozenset({"http_408", "http_425", "http_429", "http_500", "http_502", "http_503", "http_504", "TimeoutError", "URLError", "ConnectionError", "LeaseRecovery"})


def _job_id(run_id: str, probe: str, key: str) -> str:
    return hashlib.sha256(f"{run_id}|{probe}|{key}".encode()).hexdigest()[:32]


def _setup(c: duckdb.DuckDBPyConnection) -> None:
    c.execute("CREATE SEQUENCE IF NOT EXISTS supervisor_event_seq START 1")
    c.execute("CREATE TABLE IF NOT EXISTS supervisor_jobs (job_id VARCHAR PRIMARY KEY, run_id VARCHAR, parent_run_id VARCHAR, probe_family VARCHAR, endpoint VARCHAR, request_json VARCHAR, expected_ocid VARCHAR, status VARCHAR, attempts INTEGER, http_status INTEGER, response_hash VARCHAR, response_path VARCHAR, error_class VARCHAR, error_message VARCHAR, created_at VARCHAR, updated_at VARCHAR)")
    c.execute("CREATE TABLE IF NOT EXISTS supervisor_events (event_id BIGINT, job_id VARCHAR, attempt INTEGER, state VARCHAR, http_status INTEGER, retryable BOOLEAN, wait_seconds DOUBLE, error_class VARCHAR, error_message VARCHAR, response_hash VARCHAR, created_at VARCHAR, elapsed_seconds DOUBLE, transport_attempts INTEGER)")
    c.execute("CREATE TABLE IF NOT EXISTS supervisor_probe_results (probe_id VARCHAR PRIMARY KEY, run_id VARCHAR, probe_family VARCHAR, endpoint VARCHAR, request_json VARCHAR, status VARCHAR, observed_count INTEGER, new_canonical_count INTEGER, response_hash VARCHAR, response_path VARCHAR, error_class VARCHAR, created_at VARCHAR)")
    c.execute("CREATE TABLE IF NOT EXISTS supervisor_capacity_tests (test_id VARCHAR PRIMARY KEY, run_id VARCHAR, concurrency INTEGER, requested INTEGER, succeeded INTEGER, http_429 INTEGER, http_5xx INTEGER, timeouts INTEGER, elapsed_seconds DOUBLE, requests_per_minute DOUBLE, selected BOOLEAN, created_at VARCHAR)")
    c.execute("CREATE TABLE IF NOT EXISTS supervisor_matches (match_id VARCHAR PRIMARY KEY, run_id VARCHAR, parent_run_id VARCHAR, ocid VARCHAR, source_kind VARCHAR, probe_family VARCHAR, response_hash VARCHAR, response_path VARCHAR, validation_status VARCHAR, observed_ocid VARCHAR, created_at VARCHAR)")
    c.execute("ALTER TABLE supervisor_events ADD COLUMN IF NOT EXISTS elapsed_seconds DOUBLE")
    c.execute("ALTER TABLE supervisor_events ADD COLUMN IF NOT EXISTS transport_attempts INTEGER")


def _progress(c: duckdb.DuckDBPyConnection, root: Path, run_id: str, stage: str, **extra) -> None:
    counts = {r[0]: r[1] for r in c.execute("SELECT status,count(*) FROM supervisor_jobs WHERE run_id=? GROUP BY 1", [run_id]).fetchall()}
    total = c.execute("SELECT count(DISTINCT ocid) FROM read_parquet(?)", [str(canonical_root("za") / "releases.parquet")]).fetchone()[0]
    matched = c.execute("SELECT count(DISTINCT ocid) FROM supervisor_matches WHERE run_id=? AND validation_status IN ('validated','bulk_observation','cache_hit')", [run_id]).fetchone()[0]
    value = {"run_id": run_id, "stage": stage, "updated_at": utc_now(), "job_counts": counts, "canonical_matches": matched, "canonical_total": total, "coverage": matched / total if total else 0, **extra}
    temporary = root / "progress.json.tmp"
    temporary.write_text(json.dumps(value, indent=2) + "\n", encoding="utf-8")
    temporary.replace(root / "progress.json")


def _parent_matches(c: duckdb.DuckDBPyConnection, parent_run_id: str, run_id: str) -> int:
    parent_root = country_paths("za").enriched / parent_run_id
    parent_parquet = parent_root / "sa_api_bulk_releases.parquet"
    if not parent_parquet.exists():
        return 0
    canonical = str(canonical_root("za") / "releases.parquet")
    rows = c.execute("SELECT DISTINCT b.ocid,b.response_hash,b.response_path FROM read_parquet(?) b JOIN read_parquet(?) k USING(ocid)", [str(parent_parquet), canonical]).fetchall()
    for ocid, digest, path in rows:
        c.execute("INSERT OR IGNORE INTO supervisor_matches VALUES (?, ?, ?, ?, 'bulk', 'monthly_bulk', ?, ?, 'bulk_observation', ?, ?)", [_job_id(run_id, "bulk", ocid), run_id, parent_run_id, ocid, digest, path, ocid, utc_now()])
    return len(rows)


def _cache_matches(c: duckdb.DuckDBPyConnection, run_id: str, parent_run_id: str) -> int:
    roots = country_paths("za")
    cache_path = roots.enriched / "sa-api-cache.duckdb"
    if not cache_path.exists():
        return 0
    cache = _cache_connection(roots)
    canonical = str(canonical_root("za") / "releases.parquet")
    rows = cache.execute("SELECT ocid,response_hash,response_path,observed_ocid FROM responses WHERE http_status=200").fetchall()
    count = 0
    for ocid, digest, path, observed in rows:
        if observed != ocid or not c.execute("SELECT 1 FROM read_parquet(?) WHERE ocid=? LIMIT 1", [canonical, ocid]).fetchone():
            continue
        c.execute("INSERT OR IGNORE INTO supervisor_matches VALUES (?, ?, ?, ?, 'cache', 'exact_ocid_cache', ?, ?, 'cache_hit', ?, ?)", [_job_id(run_id, "cache", ocid), run_id, parent_run_id, ocid, digest, path, observed, utc_now()])
        count += 1
    cache.close()
    return count


def plan(parent_run_id: str) -> dict:
    roots = country_paths("za")
    parent_root = roots.enriched / parent_run_id
    parent_report = parent_root / "sa_api_bulk_report.json"
    if not parent_report.exists():
        raise FileNotFoundError(parent_report)
    parent = json.loads(parent_report.read_text(encoding="utf-8"))
    source_sha = source_hash(roots.raw / "ocds_full.jsonl.gz", roots.raw / "manifest.json")
    if parent.get("source_snapshot_sha256") != source_sha:
        raise ValueError("parent run source snapshot does not match current source snapshot")
    run_id = f"sa-api-supervisor-{time.strftime('%Y%m%dT%H%M%SZ', time.gmtime())}-{source_sha[:12]}"
    root = roots.enriched / run_id
    root.mkdir(parents=True, exist_ok=False)
    (root / "responses").mkdir()
    c = duckdb.connect(str(root / "ledger.duckdb"))
    _setup(c)
    seeded_bulk = _parent_matches(c, parent_run_id, run_id)
    seeded_cache = _cache_matches(c, run_id, parent_run_id)
    canonical = str(canonical_root("za") / "releases.parquet")
    rows = c.execute("SELECT ocid FROM read_parquet(?) WHERE ocid IS NOT NULL AND ocid NOT IN (SELECT ocid FROM supervisor_matches WHERE run_id=?) ORDER BY ocid", [canonical, run_id]).fetchall()
    for (ocid,) in rows:
        url = f"https://ocds-api.etenders.gov.za/api/OCDSReleases/release/{ocid}"
        request_json = json.dumps({"url": url, "ocid": ocid}, sort_keys=True)
        c.execute("INSERT INTO supervisor_jobs VALUES (?, ?, ?, 'exact_ocid', ?, ?, ?, 'pending', 0, NULL, NULL, NULL, NULL, NULL, ?, ?)", [_job_id(run_id, "exact_ocid", ocid), run_id, parent_run_id, url, request_json, ocid, utc_now(), utc_now()])
    _progress(c, root, run_id, "planned", parent_run_id=parent_run_id, next_action="capacity_probe", cache_hits=seeded_cache, bulk_matches=seeded_bulk)
    c.close()
    return {"run_id": run_id, "parent_run_id": parent_run_id, "source_snapshot_sha256": source_sha, "seeded_bulk_matches": seeded_bulk, "seeded_cache_hits": seeded_cache, "detail_jobs": len(rows), "output_root": str(root)}


def _classify(error: Exception | None, status: int | None, attempt: int) -> tuple[str, bool, str]:
    if status in (400, 401, 403, 404):
        return "permanent_failed", False, f"http_{status}"
    if status in RETRY_STATUSES:
        return ("retryable_failed" if attempt < MAX_ATTEMPTS else "permanent_failed", attempt < MAX_ATTEMPTS, f"http_{status}")
    if isinstance(error, (TimeoutError, ConnectionError)):
        return ("retryable_failed" if attempt < MAX_ATTEMPTS else "permanent_failed", attempt < MAX_ATTEMPTS, type(error).__name__)
    if isinstance(error, json.JSONDecodeError):
        return "permanent_failed", False, "malformed_json"
    if error:
        return "permanent_failed", False, type(error).__name__
    return "permanent_failed", False, "unknown"


def _fetch_job(job: tuple, client: HttpClient) -> dict:
    job_id, ocid, url, attempts = job
    started = time.monotonic()
    result = client.request(url)
    elapsed = time.monotonic() - started
    digest = _sha256(result.body) if result.body else None
    if result.status == 200:
        try:
            if not result.body:
                raise ValueError("empty_http_200")
            release = json.loads(result.body)
            if release.get("ocid") != ocid or not release.get("id") or not isinstance(release.get("tender"), dict):
                raise ValueError("source_record_mismatch_or_invalid_release")
        except (json.JSONDecodeError, ValueError) as error:
            return {"job_id": job_id, "ocid": ocid, "status": 200, "headers": result.headers, "payload": result.body, "digest": digest, "waited": result.wait_seconds, "elapsed": elapsed, "state": "permanent_failed", "retryable": False, "error_class": "malformed_json" if isinstance(error, json.JSONDecodeError) else str(error), "error_message": str(error), "transport_attempts": result.attempts}
        return {"job_id": job_id, "ocid": ocid, "status": 200, "headers": result.headers, "payload": result.body, "digest": digest, "waited": result.wait_seconds, "elapsed": elapsed, "state": "succeeded", "retryable": False, "error_class": None, "error_message": None, "transport_attempts": result.attempts}
    state, retryable, error_class = _classify(None, result.status, MAX_ATTEMPTS)
    return {"job_id": job_id, "ocid": ocid, "status": result.status, "headers": result.headers, "payload": result.body, "digest": digest, "waited": result.wait_seconds, "elapsed": elapsed, "state": state, "retryable": retryable, "error_class": result.error_class or error_class, "error_message": result.error_message, "transport_attempts": result.attempts}


def _run_pool(jobs: list[tuple], client: HttpClient, workers: int):
    """Keep all worker slots filled while jobs remain."""
    iterator = iter(jobs)
    with concurrent.futures.ThreadPoolExecutor(max_workers=workers) as pool:
        futures = {}
        for _ in range(min(workers, len(jobs))):
            job = next(iterator, None)
            if job is not None:
                futures[pool.submit(_fetch_job, job, client)] = job
        while futures:
            done, _ = concurrent.futures.wait(futures, return_when=concurrent.futures.FIRST_COMPLETED)
            for future in done:
                del futures[future]
                yield future.result()
                job = next(iterator, None)
                if job is not None:
                    futures[pool.submit(_fetch_job, job, client)] = job


def _write_match(c, run_id, parent_run_id, result, root):
    if result["state"] != "succeeded":
        return False
    path = root / "responses" / f"{result['digest']}.json"
    if not path.exists():
        path.write_bytes(result["payload"])
    c.execute("INSERT OR IGNORE INTO supervisor_matches VALUES (?, ?, ?, ?, 'detail', 'exact_ocid', ?, ?, 'validated', ?, ?)", [_job_id(run_id, "detail", result["ocid"]), run_id, parent_run_id, result["ocid"], result["digest"], str(path), result["ocid"], utc_now()])
    return True


def run(run_id: str, *, timeout: int = 90, rate: float = 1.0, max_concurrency: int = 4) -> dict:
    roots = country_paths("za")
    root = roots.enriched / run_id
    c = duckdb.connect(str(root / "ledger.duckdb"))
    _setup(c)
    parent_run_id = c.execute("SELECT parent_run_id FROM supervisor_jobs WHERE run_id=? LIMIT 1", [run_id]).fetchone()[0]
    source_sha = source_hash(roots.raw / "ocds_full.jsonl.gz", roots.raw / "manifest.json")
    c.execute("UPDATE supervisor_jobs SET status='retryable_failed', error_class='LeaseRecovery', error_message='recovered after interruption', updated_at=? WHERE run_id=? AND status='running'", [utc_now(), run_id])
    _progress(c, root, run_id, "capacity_probe", parent_run_id=parent_run_id)
    stop = threading.Event()

    def interrupted(signum, frame):
        stop.set()
        _progress(c, root, run_id, "interrupted", parent_run_id=parent_run_id, next_action="resume")
        raise KeyboardInterrupt(f"received signal {signum}")

    signal.signal(signal.SIGINT, interrupted)
    signal.signal(signal.SIGTERM, interrupted)
    client = HttpClient(HttpPolicy(rate_per_second=rate, jitter_seconds=1.0, timeout_seconds=timeout, max_attempts=MAX_ATTEMPTS))
    probe_rows = c.execute("SELECT job_id,expected_ocid,endpoint,attempts FROM supervisor_jobs WHERE run_id=? AND status='pending' ORDER BY expected_ocid LIMIT 4", [run_id]).fetchall()
    selected = 1
    for level in CAPACITY_LEVELS:
        if level > max_concurrency or not probe_rows:
            break
        started = time.monotonic()
        with concurrent.futures.ThreadPoolExecutor(max_workers=level) as pool:
            results = list(pool.map(lambda job: _fetch_job(job, client), probe_rows))
        elapsed = time.monotonic() - started
        successes = sum(r["state"] == "succeeded" for r in results)
        statuses = [r["status"] for r in results]
        c.execute("INSERT OR REPLACE INTO supervisor_capacity_tests VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)", [_job_id(run_id, "capacity", str(level)), run_id, level, len(results), successes, statuses.count(429), sum(s >= 500 for s in statuses if s), sum(r["error_class"] == "TimeoutError" for r in results), elapsed, len(results) / elapsed * 60 if elapsed else 0, successes == len(results), utc_now()])
        if successes != len(results) or 429 in statuses or any(s and s >= 500 for s in statuses):
            break
        selected = level
    _progress(c, root, run_id, "exact_ocid", parent_run_id=parent_run_id, selected_concurrency=selected)
    while not stop.is_set():
        jobs = c.execute("SELECT job_id,expected_ocid,endpoint,attempts FROM supervisor_jobs WHERE run_id=? AND status IN ('pending','retryable_failed') ORDER BY expected_ocid LIMIT ?", [run_id, selected * 4]).fetchall()
        if not jobs:
            break
        for result in _run_pool(jobs, client, selected):
            attempt = c.execute("SELECT attempts FROM supervisor_jobs WHERE job_id=?", [result["job_id"]]).fetchone()[0] + 1
            c.execute("UPDATE supervisor_jobs SET status=?, attempts=?, http_status=?, response_hash=?, error_class=?, error_message=?, updated_at=? WHERE job_id=?", [result["state"], attempt, result["status"], result["digest"], result["error_class"], result["error_message"], utc_now(), result["job_id"]])
            c.execute("INSERT INTO supervisor_events VALUES (nextval('supervisor_event_seq'), ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)", [result["job_id"], attempt, result["state"], result["status"], result["retryable"], result["waited"], result["error_class"], result["error_message"], result["digest"], utc_now(), result["elapsed"], result["transport_attempts"]])
            if result["state"] == "succeeded":
                _write_match(c, run_id, parent_run_id, result, root)
        _progress(c, root, run_id, "exact_ocid", parent_run_id=parent_run_id, selected_concurrency=selected)
    _materialize(c, root, run_id, parent_run_id, source_sha)
    c.close()
    return report(run_id)


def _materialize(c, root: Path, run_id: str, parent_run_id: str, source_sha: str) -> None:
    c.execute("CREATE OR REPLACE TABLE sa_api_supervisor_matches AS SELECT * FROM supervisor_matches WHERE run_id=?", [run_id])
    c.execute("COPY sa_api_supervisor_matches TO ? (FORMAT PARQUET, COMPRESSION ZSTD)", [str(root / "sa_api_supervisor_matches.parquet")])
    c.execute("COPY supervisor_probe_results TO ? (FORMAT PARQUET, COMPRESSION ZSTD)", [str(root / "sa_api_supervisor_probe_results.parquet")])
    c.execute("COPY supervisor_capacity_tests TO ? (FORMAT PARQUET, COMPRESSION ZSTD)", [str(root / "sa_api_supervisor_capacity.parquet")])
    canonical = str(canonical_root("za") / "releases.parquet")
    total = c.execute("SELECT count(DISTINCT ocid) FROM read_parquet(?)", [canonical]).fetchone()[0]
    matched = c.execute("SELECT count(DISTINCT ocid) FROM supervisor_matches WHERE run_id=? AND validation_status IN ('validated','bulk_observation','cache_hit')", [run_id]).fetchone()[0]
    jobs = {r[0]: r[1] for r in c.execute("SELECT status,count(*) FROM supervisor_jobs WHERE run_id=? GROUP BY 1", [run_id]).fetchall()}
    latency = c.execute("SELECT coalesce(avg(elapsed_seconds), 0), coalesce(quantile_cont(elapsed_seconds, 0.95), 0), coalesce(sum(transport_attempts), 0) FROM supervisor_events WHERE job_id IN (SELECT job_id FROM supervisor_jobs WHERE run_id=?)", [run_id]).fetchone()
    result = {"run_id": run_id, "parent_run_id": parent_run_id, "source_snapshot_sha256": source_sha, "canonical_total": total, "baseline_and_validated_matches": matched, "coverage": matched / total if total else 0, "job_counts": jobs, "requests": c.execute("SELECT count(*) FROM supervisor_events WHERE job_id IN (SELECT job_id FROM supervisor_jobs WHERE run_id=?)", [run_id]).fetchone()[0], "cache_hits": c.execute("SELECT count(*) FROM supervisor_matches WHERE run_id=? AND validation_status='cache_hit'", [run_id]).fetchone()[0], "average_request_elapsed_seconds": latency[0], "p95_request_elapsed_seconds": latency[1], "transport_attempts": latency[2], "terminal_condition": "all_jobs_terminal" if not jobs.get("pending") and not jobs.get("retryable_failed") else "work_remaining", "status": "pass" if not jobs.get("pending") and not jobs.get("retryable_failed") and not jobs.get("permanent_failed") else "warn", "outputs": {"matches": str(root / "sa_api_supervisor_matches.parquet"), "probe_results": str(root / "sa_api_supervisor_probe_results.parquet"), "capacity": str(root / "sa_api_supervisor_capacity.parquet")}}
    (root / "sa_api_supervisor_report.json").write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    (root / "sa_api_supervisor_report.md").write_text("# South Africa API supervisor report\n\n" + "\n".join(f"- {key}: {value}" for key, value in result.items() if key != "outputs") + "\n", encoding="utf-8")
    write_run_manifest("sa-api-supervisor", source_sha, {"report": result, "output_root": str(root)}, run=run_id, working_root=country_paths("za").working)
    _progress(c, root, run_id, "complete", parent_run_id=parent_run_id, terminal_condition=result["terminal_condition"])


def report(run_id: str) -> dict:
    path = country_paths("za").enriched / run_id / "sa_api_supervisor_report.json"
    if not path.exists():
        raise FileNotFoundError(path)
    return json.loads(path.read_text(encoding="utf-8"))


def flush_permanent_failures(run_id: str, reasons: tuple[str, ...] = ()) -> dict:
    """Requeue selected permanent failures for a later supervisor run."""
    root = country_paths("za").enriched / run_id
    ledger = root / "ledger.duckdb"
    if not ledger.exists():
        raise FileNotFoundError(ledger)
    selected = frozenset(reasons) if reasons else FLUSHABLE_FAILURES
    unsupported = sorted(selected - FLUSHABLE_FAILURES)
    if unsupported:
        raise ValueError(f"unsupported flush reasons: {', '.join(unsupported)}")
    c = duckdb.connect(str(ledger))
    _setup(c)
    rows = c.execute("SELECT job_id, attempts, error_class FROM supervisor_jobs WHERE run_id=? AND status='permanent_failed' AND error_class IN (SELECT * FROM UNNEST(?))", [run_id, list(selected)]).fetchall()
    now = utc_now()
    for job_id, attempts, error_class in rows:
        c.execute("UPDATE supervisor_jobs SET status='retryable_failed', attempts=0, error_message='requeued by reason-based flush', updated_at=? WHERE job_id=?", [now, job_id])
        c.execute("INSERT INTO supervisor_events VALUES (nextval('supervisor_event_seq'), ?, ?, 'requeued', ?, TRUE, 0, ?, 'requeued by reason-based flush', NULL, ?, NULL, NULL)", [job_id, attempts, error_class, now])
    _progress(c, root, run_id, "flushed", flushed_count=len(rows), flushed_reasons=sorted(selected), next_action="resume")
    c.close()
    counts: dict[str, int] = {}
    for _, _, error_class in rows:
        counts[error_class] = counts.get(error_class, 0) + 1
    return {"run_id": run_id, "requeued": len(rows), "reasons": sorted(selected), "counts_by_reason": counts, "next_action": f"pursuitmap sa-api-supervise resume --run-id {run_id}"}


def status(run_id: str) -> dict:
    root = country_paths("za").enriched / run_id
    progress = root / "progress.json"
    if progress.exists():
        return json.loads(progress.read_text(encoding="utf-8"))
    raise FileNotFoundError(progress)
