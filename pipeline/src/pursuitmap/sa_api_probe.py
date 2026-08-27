from __future__ import annotations

import concurrent.futures
import hashlib
import json
import statistics
import time
from pathlib import Path

import duckdb

from .http_client import HttpClient, HttpPolicy
from .paths import canonical_root, country_paths
from .provenance import source_hash, utc_now, write_run_manifest


API = "https://ocds-api.etenders.gov.za"
STAGES = ((1.0, 1), (2.0, 1), (4.0, 1), (1.0, 2), (2.0, 2), (4.0, 2), (2.0, 4), (4.0, 4))
SAMPLE_SIZE = 10


def _id(*parts: object) -> str:
    return hashlib.sha256("|".join(map(str, parts)).encode()).hexdigest()[:32]


def _setup(c: duckdb.DuckDBPyConnection) -> None:
    c.execute("CREATE SEQUENCE IF NOT EXISTS probe_event_seq START 1")
    c.execute("CREATE TABLE IF NOT EXISTS probe_jobs (job_id VARCHAR PRIMARY KEY, run_id VARCHAR, stage_id VARCHAR, rate_per_second DOUBLE, concurrency INTEGER, request_kind VARCHAR, url VARCHAR, expected_ocid VARCHAR, status VARCHAR, attempts INTEGER, http_status INTEGER, response_hash VARCHAR, response_path VARCHAR, error_class VARCHAR, error_message VARCHAR, latency_seconds DOUBLE, created_at VARCHAR, updated_at VARCHAR)")
    c.execute("CREATE TABLE IF NOT EXISTS probe_events (event_id BIGINT, job_id VARCHAR, attempt INTEGER, state VARCHAR, http_status INTEGER, wait_seconds DOUBLE, error_class VARCHAR, error_message VARCHAR, response_hash VARCHAR, headers_json VARCHAR, created_at VARCHAR)")
    c.execute("CREATE TABLE IF NOT EXISTS probe_stage_results (stage_id VARCHAR PRIMARY KEY, run_id VARCHAR, rate_per_second DOUBLE, concurrency INTEGER, requested INTEGER, succeeded INTEGER, canonical_matches INTEGER, http_429 INTEGER, http_5xx INTEGER, timeout_count INTEGER, other_errors INTEGER, median_latency_seconds DOUBLE, p95_latency_seconds DOUBLE, max_latency_seconds DOUBLE, requests_per_minute DOUBLE, coverage_gained DOUBLE, coverage_per_request DOUBLE, coverage_per_minute DOUBLE, passed BOOLEAN, rejection_reason VARCHAR, created_at VARCHAR)")


def _progress(c, root: Path, run_id: str, stage: str, **extra) -> None:
    counts = {r[0]: r[1] for r in c.execute("SELECT status,count(*) FROM probe_jobs WHERE run_id=? GROUP BY 1", [run_id]).fetchall()}
    value = {"run_id": run_id, "stage": stage, "updated_at": utc_now(), "job_counts": counts, **extra}
    temp = root / "sa_api_capacity_probe_progress.json.tmp"
    temp.write_text(json.dumps(value, indent=2) + "\n", encoding="utf-8")
    temp.replace(root / "sa_api_capacity_probe_progress.json")


def plan(parent_run_id: str) -> dict:
    roots = country_paths("za")
    parent_report = roots.enriched / parent_run_id / "sa_api_supervisor_report.json"
    if not parent_report.exists():
        parent_report = roots.enriched / parent_run_id / "sa_api_bulk_report.json"
    if not parent_report.exists():
        raise FileNotFoundError(parent_report)
    source_sha = source_hash(roots.raw / "ocds_full.jsonl.gz", roots.raw / "manifest.json")
    parent = json.loads(parent_report.read_text(encoding="utf-8"))
    if parent.get("source_snapshot_sha256") != source_sha:
        raise ValueError("parent run source snapshot does not match current source snapshot")
    run_id = f"sa-api-probe-{time.strftime('%Y%m%dT%H%M%SZ', time.gmtime())}-{source_sha[:12]}"
    root = roots.enriched / run_id
    root.mkdir(parents=True, exist_ok=False)
    (root / "responses").mkdir()
    c = duckdb.connect(str(root / "ledger.duckdb"))
    _setup(c)
    canonical = str(canonical_root("za") / "releases.parquet")
    ocids = [r[0] for r in c.execute("SELECT ocid FROM read_parquet(?) WHERE ocid IS NOT NULL ORDER BY sha256(ocid) LIMIT ?", [canonical, SAMPLE_SIZE]).fetchall()]
    for index, (rate, concurrency) in enumerate(STAGES, 1):
        stage_id = f"stage-{index:02d}-{rate:g}rps-c{concurrency}"
        for sample_index, ocid in enumerate(ocids):
            url = f"{API}/api/OCDSReleases/release/{ocid}"
            c.execute("INSERT INTO probe_jobs VALUES (?, ?, ?, ?, ?, 'exact_ocid', ?, ?, 'pending', 0, NULL, NULL, NULL, NULL, NULL, NULL, ?, ?)", [_id(run_id, stage_id, sample_index), run_id, stage_id, rate, concurrency, url, ocid, utc_now(), utc_now()])
    _progress(c, root, run_id, "planned", parent_run_id=parent_run_id, stages=len(STAGES), sample_size=len(ocids), next_action="run_stage_01")
    c.close()
    return {"run_id": run_id, "parent_run_id": parent_run_id, "source_snapshot_sha256": source_sha, "stages": len(STAGES), "sample_size": len(ocids), "output_root": str(root)}


def _one(job, client: HttpClient, root: Path) -> dict:
    job_id, ocid, url, attempts = job
    started = time.monotonic()
    result = client.request(url)
    latency = time.monotonic() - started
    digest = hashlib.sha256(result.body).hexdigest() if result.body else None
    path = root / "responses" / f"{digest}.json" if digest else None
    if path and not path.exists():
        path.write_bytes(result.body)
    valid = False
    error_class = result.error_class
    error_message = result.error_message
    if result.status == 200:
        try:
            body = json.loads(result.body)
            valid = body.get("ocid") == ocid and isinstance(body.get("tender"), dict)
            if not valid:
                error_class, error_message = "ocid_mismatch", "response OCID or tender object did not validate"
        except json.JSONDecodeError as error:
            error_class, error_message = "malformed_json", str(error)
    return {"job_id": job_id, "ocid": ocid, "status": "succeeded" if valid else "failed", "http_status": result.status, "digest": digest, "path": str(path) if path else None, "latency": latency, "attempts": result.attempts, "wait": result.wait_seconds, "headers": result.headers, "error_class": error_class, "error_message": error_message, "valid": valid}


def run(run_id: str, *, timeout: int = 90) -> dict:
    roots = country_paths("za")
    root = roots.enriched / run_id
    c = duckdb.connect(str(root / "ledger.duckdb"))
    _setup(c)
    source_sha = source_hash(roots.raw / "ocds_full.jsonl.gz", roots.raw / "manifest.json")
    stages = c.execute("SELECT DISTINCT stage_id,rate_per_second,concurrency FROM probe_jobs WHERE run_id=? ORDER BY stage_id", [run_id]).fetchall()
    all_results = []
    for stage_id, rate, concurrency in stages:
        jobs = c.execute("SELECT job_id,expected_ocid,url,attempts FROM probe_jobs WHERE run_id=? AND stage_id=? AND status='pending' ORDER BY job_id", [run_id, stage_id]).fetchall()
        policy = HttpPolicy(rate_per_second=rate, jitter_seconds=1.0, timeout_seconds=timeout, max_attempts=2)
        client = HttpClient(policy)
        started = time.monotonic()
        with concurrent.futures.ThreadPoolExecutor(max_workers=concurrency) as pool:
            results = list(pool.map(lambda job: _one(job, client, root), jobs))
        elapsed = time.monotonic() - started
        latencies = [r["latency"] for r in results]
        statuses = [r["http_status"] for r in results]
        succeeded = sum(r["valid"] for r in results)
        passed = succeeded == len(results) and not any(s == 429 or (s and s >= 500) for s in statuses)
        reason = None if passed else "validation or server error threshold exceeded"
        p95 = sorted(latencies)[max(0, int(len(latencies) * 0.95) - 1)] if latencies else 0
        for result in results:
            attempt = result["attempts"]
            c.execute("UPDATE probe_jobs SET status=?, attempts=?, http_status=?, response_hash=?, response_path=?, error_class=?, error_message=?, latency_seconds=?, updated_at=? WHERE job_id=?", [result["status"], attempt, result["http_status"], result["digest"], result["path"], result["error_class"], result["error_message"], result["latency"], utc_now(), result["job_id"]])
            c.execute("INSERT INTO probe_events VALUES (nextval('probe_event_seq'), ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)", [result["job_id"], attempt, result["status"], result["http_status"], result["wait"], result["error_class"], result["error_message"], result["digest"], json.dumps(result["headers"], sort_keys=True), utc_now()])
        rpm = len(results) / elapsed * 60 if elapsed else 0
        row = [stage_id, run_id, rate, concurrency, len(results), succeeded, succeeded, statuses.count(429), sum(s is not None and s >= 500 for s in statuses), sum(r["error_class"] == "TimeoutError" for r in results), sum(not r["valid"] and r["error_class"] not in {"TimeoutError"} and not (r["http_status"] == 429 or (r["http_status"] and r["http_status"] >= 500)) for r in results), statistics.median(latencies) if latencies else 0, p95, max(latencies) if latencies else 0, rpm, 0, succeeded / len(results) if results else 0, succeeded / elapsed * 60 if elapsed else 0, passed, reason, utc_now()]
        c.execute("INSERT OR REPLACE INTO probe_stage_results VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)", row)
        _progress(c, root, run_id, stage_id, current_rate=rate, current_concurrency=concurrency, completed_stages=len(all_results) + 1, next_action="next_stage" if passed else "reduce_capacity")
        all_results.extend(results)
        if not passed:
            break
    _materialize(c, root, run_id, source_sha)
    result = report(run_id)
    c.close()
    return result


def _materialize(c, root: Path, run_id: str, source_sha: str) -> None:
    c.execute("COPY probe_stage_results TO ? (FORMAT PARQUET, COMPRESSION ZSTD)", [str(root / "sa_api_capacity_probe_results.parquet")])
    c.execute("COPY (SELECT event_id,job_id,headers_json FROM probe_events WHERE job_id IN (SELECT job_id FROM probe_jobs WHERE run_id=?)) TO ? (FORMAT PARQUET, COMPRESSION ZSTD)", [run_id, str(root / "sa_api_capacity_probe_headers.parquet")])
    stages = c.execute("SELECT * FROM probe_stage_results WHERE run_id=? ORDER BY stage_id", [run_id]).fetchall()
    last = stages[-1] if stages else None
    passed = [r for r in stages if r[18]]
    selected = max(passed, key=lambda r: (r[2], r[3])) if passed else None
    final = {"run_id": run_id, "source_snapshot_sha256": source_sha, "stages_tested": len(stages), "highest_safe_rate_per_second": selected[2] if selected else None, "highest_safe_concurrency": selected[3] if selected else None, "selected_rate_per_second": selected[2] * 0.75 if selected else None, "selected_concurrency": selected[3] if selected else None, "stage_results": [{"stage_id": r[0], "rate_per_second": r[2], "concurrency": r[3], "requested": r[4], "succeeded": r[5], "canonical_matches": r[6], "passed": r[18], "rpm": r[14], "rejection_reason": r[19]} for r in stages], "terminal_condition": "capacity_boundary_found" if stages and not stages[-1][18] else "approved_stages_exhausted", "outputs": {"results": str(root / "sa_api_capacity_probe_results.parquet"), "headers": str(root / "sa_api_capacity_probe_headers.parquet")}}
    (root / "sa_api_capacity_probe_report.json").write_text(json.dumps(final, indent=2) + "\n", encoding="utf-8")
    (root / "sa_api_capacity_probe_report.md").write_text("# South Africa API capacity probe\n\n" + "\n".join(f"- {k}: {v}" for k, v in final.items() if k not in {"stage_results", "outputs"}) + "\n", encoding="utf-8")
    write_run_manifest("sa-api-capacity-probe", source_sha, {"report": final, "output_root": str(root)}, run=run_id, working_root=country_paths("za").working)
    _progress(c, root, run_id, "complete", selected_rate_per_second=final["selected_rate_per_second"], selected_concurrency=final["selected_concurrency"], terminal_condition=final["terminal_condition"])


def report(run_id: str) -> dict:
    path = country_paths("za").enriched / run_id / "sa_api_capacity_probe_report.json"
    if not path.exists():
        raise FileNotFoundError(path)
    return json.loads(path.read_text(encoding="utf-8"))


def status(run_id: str) -> dict:
    path = country_paths("za").enriched / run_id / "sa_api_capacity_probe_progress.json"
    if not path.exists():
        raise FileNotFoundError(path)
    return json.loads(path.read_text(encoding="utf-8"))
