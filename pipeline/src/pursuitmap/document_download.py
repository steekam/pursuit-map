from __future__ import annotations

import hashlib
import json
import mimetypes
import random
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Callable

import duckdb

from .paths import country_paths, ensure_data_dirs
from .provenance import run_id, utc_now
from .http_client import RateLimiter, parse_retry_after
from .job_runner import DurableJobRunner, JobOutcome, RunnerPolicy


RETRY_STATUSES = (408, 425, 429, 500, 502, 503, 504)
LEDGER_SCHEMA = {
    "download_jobs": "job_id VARCHAR PRIMARY KEY, source_run_id VARCHAR, ocid VARCHAR, release_id VARCHAR, document_id VARCHAR, source_url VARCHAR, normalized_url VARCHAR, status VARCHAR, attempts INTEGER, http_status INTEGER, content_type VARCHAR, response_hash VARCHAR, response_path VARCHAR, validation_status VARCHAR, error_class VARCHAR, error_message VARCHAR, created_at VARCHAR, updated_at VARCHAR",
    "download_job_refs": "reference_id BIGINT, job_id VARCHAR, ocid VARCHAR, release_id VARCHAR, document_id VARCHAR, source_url VARCHAR, created_at VARCHAR",
    "download_events": "event_id BIGINT, job_id VARCHAR, attempt INTEGER, state VARCHAR, http_status INTEGER, response_hash VARCHAR, error_class VARCHAR, error_message VARCHAR, created_at VARCHAR",
}


def _sha256(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def _job_id(url: str) -> str:
    return _sha256(url.encode())[:32]


def normalize_url(value: str, base_url: str = "https://tenders.go.ke") -> str:
    parsed = urllib.parse.urlsplit(urllib.parse.urljoin(base_url, value.strip()))
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise ValueError("invalid_document_url")
    return urllib.parse.urlunsplit((parsed.scheme.lower(), parsed.netloc.lower(), parsed.path, parsed.query, ""))


def _create_ledger(connection: duckdb.DuckDBPyConnection) -> None:
    connection.execute("CREATE SEQUENCE IF NOT EXISTS download_event_seq START 1")
    connection.execute("CREATE SEQUENCE IF NOT EXISTS download_reference_seq START 1")
    for table, definition in LEDGER_SCHEMA.items():
        connection.execute(f'CREATE TABLE IF NOT EXISTS "{table}" ({definition})')


def _attachment_url(value: dict) -> str | None:
    for key in ("url", "source_url", "document_url"):
        if value.get(key):
            return str(value[key])
    return None


def plan(input_parquet: Path, output_root: Path, *, source_run_id: str, source_snapshot_sha256: str, base_url: str = "https://tenders.go.ke") -> dict:
    """Create one job per unique attachment URL and retain every record reference."""
    output_root.mkdir(parents=True, exist_ok=True)
    (output_root / "files").mkdir(exist_ok=True)
    ledger_path = output_root / "ledger.duckdb"
    connection = duckdb.connect(str(ledger_path))
    _create_ledger(connection)
    rows: dict[str, dict] = {}
    columns = {row[0] for row in connection.execute("DESCRIBE SELECT * FROM read_parquet(?)", [str(input_parquet)]).fetchall()}
    if "attachments_json" in columns:
        source_rows = ((ocid, release_id, document.get("document_id"), document) for ocid, release_id, attachments_json in connection.execute("SELECT ocid, release_id, attachments_json FROM read_parquet(?)", [str(input_parquet)]).fetchall() for document in json.loads(attachments_json or "[]"))
    elif {"ocid", "release_id", "document_id", "url"}.issubset(columns):
        source_rows = ((ocid, release_id, document_id, {"id": document_id, "url": url, "title": title, "documentType": document_type}) for ocid, release_id, document_id, title, url, document_type in connection.execute("SELECT ocid, release_id, document_id, title, url, document_type FROM read_parquet(?)", [str(input_parquet)]).fetchall())
    else:
        raise ValueError("document plan requires attachments_json or canonical document columns")
    for ocid, release_id, document_id, document in source_rows:
        if not isinstance(document, dict):
            continue
        raw_url = _attachment_url(document)
        if not raw_url:
            continue
        try:
            url = normalize_url(raw_url, base_url)
        except ValueError:
            continue
        item = rows.setdefault(url, {"ocids": [], "release_ids": [], "document_ids": [], "references": []})
        item["ocids"].append(ocid)
        item["release_ids"].append(release_id)
        item["references"].append({"ocid": ocid, "release_id": release_id, "document_id": str(document_id) if document_id is not None else None, "source_url": url})
        if document_id is not None:
            item["document_ids"].append(str(document_id))
    now = utc_now()
    for url, refs in rows.items():
        job_id = _job_id(url)
        connection.execute("""INSERT INTO download_jobs (job_id, source_run_id, ocid, release_id, document_id, source_url, normalized_url, status, attempts, http_status, content_type, response_hash, response_path, validation_status, error_class, error_message, created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?, 'pending', 0, NULL, NULL, NULL, NULL, NULL, NULL, NULL, ?, ?) ON CONFLICT (job_id) DO NOTHING""", [job_id, source_run_id, json.dumps(sorted(set(refs["ocids"]))), json.dumps(sorted(set(refs["release_ids"]))), json.dumps(sorted(set(refs["document_ids"]))), url, url, now, now])
        connection.execute("DELETE FROM download_job_refs WHERE job_id = ?", [job_id])
        for reference in {json.dumps(value, sort_keys=True) for value in refs["references"]}:
            value = json.loads(reference)
            connection.execute("INSERT INTO download_job_refs VALUES (nextval('download_reference_seq'), ?, ?, ?, ?, ?, ?)", [job_id, value["ocid"], value["release_id"], value["document_id"], value["source_url"], now])
    connection.close()
    return {"run_id": output_root.name, "source_run_id": source_run_id, "source_snapshot_sha256": source_snapshot_sha256, "jobs": len(rows), "ledger": str(ledger_path), "output_root": str(output_root)}


def _fetch(url: str, timeout: int) -> tuple[int, dict, bytes]:
    request = urllib.request.Request(url, headers={"User-Agent": "PursuitMap/0.1 document-downloader", "Accept": "*/*"})
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return response.status, dict(response.headers), response.read()
    except urllib.error.HTTPError as error:
        return error.code, dict(error.headers), error.read()


def _content_type(headers: dict, url: str) -> str:
    return (headers.get("Content-Type") or mimetypes.guess_type(url)[0] or "application/octet-stream").split(";", 1)[0].lower()


def _valid_content_type(content_type: str, url: str, payload: bytes) -> bool:
    if content_type in {"text/html", "application/xhtml+xml"} and url.lower().split("?", 1)[0].endswith((".pdf", ".doc", ".docx", ".xls", ".xlsx")):
        return False
    return bool(payload)


def _write_progress(connection: duckdb.DuckDBPyConnection, run_root: Path, *, phase: str, limit: int | None) -> None:
    counts = {str(row[0]): row[1] for row in connection.execute("SELECT status, count(*) FROM download_jobs GROUP BY 1").fetchall()}
    value = {"run_id": run_root.name, "phase": phase, "updated_at": utc_now(), "limit": limit, "job_counts": counts, "downloaded_files": connection.execute("SELECT count(*) FROM download_jobs WHERE status='succeeded'").fetchone()[0], "total_jobs": connection.execute("SELECT count(*) FROM download_jobs").fetchone()[0]}
    temporary = run_root / "progress.json.tmp"
    temporary.write_text(json.dumps(value, indent=2) + "\n", encoding="utf-8")
    temporary.replace(run_root / "progress.json")


def run(run_root: Path, *, timeout: int = 60, max_attempts: int = 4, rate_per_second: float = 1.0, jitter_seconds: float = 1.0, limit: int | None = None, sleep: Callable[[float], None] = time.sleep, randomizer: Callable[[], float] = random.random) -> dict:
    ledger_path = run_root / "ledger.duckdb"
    connection = duckdb.connect(str(ledger_path))
    _create_ledger(connection)
    (run_root / "files").mkdir(exist_ok=True)
    rows = connection.execute("SELECT job_id, normalized_url FROM download_jobs WHERE status IN ('pending', 'retryable_failed') ORDER BY job_id" + (f" LIMIT {int(limit)}" if limit is not None else "")).fetchall()
    runner = DurableJobRunner(connection, run_root.name, policy=RunnerPolicy(max_attempts=max_attempts, jitter_seconds=jitter_seconds), sleeper=sleep, randomizer=randomizer)
    limiter = RateLimiter(rate_per_second, jitter_seconds, sleeper=sleep, randomizer=randomizer)
    for job_id, url in rows:
        runner.add(job_id, {"job_id": job_id, "url": url})

    def handler(payload: dict) -> JobOutcome:
        job_id, url = payload["job_id"], payload["url"]
        limiter.wait()
        status, headers, response = _fetch(url, timeout)
        content_type = _content_type(headers, url)
        digest = _sha256(response)
        path = run_root / "files" / digest
        if response and not path.exists():
            path.write_bytes(response)
        retry_after = parse_retry_after(headers.get("Retry-After"))
        retryable = status in RETRY_STATUSES
        valid = status == 200 and _valid_content_type(content_type, url, response)
        if valid:
            references = connection.execute("SELECT source_run_id, ocid, release_id, document_id, source_url FROM download_jobs WHERE job_id = ?", [job_id]).fetchone()
            input_manifest = {"path": str(path), "source_url": references[4], "source_run_id": references[0], "ocids": json.loads(references[1]), "release_ids": json.loads(references[2]), "document_ids": json.loads(references[3]), "response_hash": digest, "content_type": content_type, "status": "captured"}
            (run_root / "files" / f"{digest}.input.json").write_text(json.dumps(input_manifest, indent=2) + "\n", encoding="utf-8")
            connection.execute("UPDATE download_jobs SET status='succeeded', attempts=attempts+1, http_status=?, content_type=?, response_hash=?, response_path=?, validation_status='pass', updated_at=? WHERE job_id=?", [status, content_type, digest, str(path), utc_now(), job_id])
            return JobOutcome(response_hash=digest)
        error_class = f"http_{status}" if status else "invalid_content"
        connection.execute("UPDATE download_jobs SET http_status=?, content_type=?, response_hash=?, response_path=?, validation_status='fail', error_class=?, error_message=?, updated_at=? WHERE job_id=?", [status, content_type, digest, str(path) if response else None, error_class, "empty or HTML document response" if status == 200 else "HTTP response", utc_now(), job_id])
        return JobOutcome(status="failed", retryable=retryable, error_class=error_class, error_message="HTTP response", response_hash=digest, retry_after_seconds=retry_after)

    _write_progress(connection, run_root, phase="running", limit=limit)
    runner_report = runner.run(handler, progress_path=run_root / "progress.json")
    connection.execute("UPDATE download_jobs SET status='retryable_failed' WHERE job_id IN (SELECT job_id FROM jobs WHERE run_id=? AND status='retryable_failed')", [run_root.name])
    connection.execute("UPDATE download_jobs SET status='permanent_failed' WHERE job_id IN (SELECT job_id FROM jobs WHERE run_id=? AND status='permanent_failed')", [run_root.name])
    counts = {row[0]: row[1] for row in connection.execute("SELECT status, count(*) FROM download_jobs GROUP BY 1").fetchall()}
    report = {"run_id": run_root.name, "job_counts": counts, "downloaded_files": connection.execute("SELECT count(*) FROM download_jobs WHERE status = 'succeeded'").fetchone()[0], "unique_response_hashes": connection.execute("SELECT count(DISTINCT response_hash) FROM download_jobs WHERE response_hash IS NOT NULL").fetchone()[0], "duplicate_url_jobs": connection.execute("SELECT count(*) - count(DISTINCT normalized_url) FROM download_jobs").fetchone()[0], "ledger": str(ledger_path), "output_root": str(run_root), "status": "pass" if not counts.get("permanent_failed") and not counts.get("retryable_failed") else "warn"}
    _write_progress(connection, run_root, phase="complete" if limit is None or not counts.get("pending") else "paused_limit", limit=limit)
    (run_root / "document_download_report.json").write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    connection.close()
    return report
