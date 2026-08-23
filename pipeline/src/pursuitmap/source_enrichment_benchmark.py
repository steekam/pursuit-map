from __future__ import annotations

import hashlib
import json
import random
import time
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import UTC, datetime
from pathlib import Path

import duckdb

from .durable_source_enrichment import BASE_URL, load_config
from .paths import country_paths


def _request(url: str, timeout: int) -> tuple[int | None, bytes, str | None]:
    request = urllib.request.Request(url, headers={"User-Agent": "PursuitMap/0.1 capacity-benchmark", "Accept": "application/json"})
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return response.status, response.read(), None
    except urllib.error.HTTPError as error:
        return error.code, error.read(), None
    except Exception as error:
        return None, b"", error.__class__.__name__


def _one(external_id: str, expected_ocid: str, config, output: Path, scheduled_at: float) -> dict:
    delay = max(0.0, scheduled_at - time.monotonic())
    if delay:
        time.sleep(delay)
    started = time.monotonic()
    status, payload, error_class = _request(BASE_URL + config.detail_endpoint.format(id=external_id), config.request_timeout_seconds)
    elapsed = time.monotonic() - started
    digest = hashlib.sha256(payload).hexdigest() if payload else None
    response_path = None
    observed_ocid = None
    validation = "not_checked"
    if payload:
        response_path = output / f"{external_id}-{digest}.json"
        response_path.write_bytes(payload)
        try:
            observed_ocid = json.loads(payload).get("ocid")
            validation = "valid" if status == 200 and observed_ocid == expected_ocid else "mismatch" if status == 200 else "http_error"
        except json.JSONDecodeError:
            validation = "invalid_json"
    return {"external_id": external_id, "expected_ocid": expected_ocid, "http_status": status, "error_class": error_class, "response_sha256": digest, "response_path": str(response_path) if response_path else None, "observed_ocid": observed_ocid, "validation": validation, "elapsed_seconds": elapsed}


def benchmark(run: str, *, country: str = "ke", sample_per_level: int = 20, rates: tuple[float, ...] = (1.0, 2.0, 4.0), concurrency: tuple[int, ...] = (1, 2, 4)) -> dict:
    roots = country_paths(country)
    config = load_config()
    ledger_path = roots.enriched / run / "ledger.duckdb"
    if not ledger_path.exists():
        raise FileNotFoundError(ledger_path)
    connection = duckdb.connect(str(ledger_path), read_only=True)
    targets = connection.execute("SELECT external_id, ocid FROM source_mappings WHERE canonical_match ORDER BY mapping_id LIMIT ?", [sample_per_level * len(rates)]).fetchall()
    source_sha = connection.execute("SELECT source_snapshot_sha256 FROM run_metadata WHERE run_id = ?", [run]).fetchone()[0]
    connection.close()
    if len(targets) < sample_per_level * len(rates):
        raise ValueError("Not enough verified detail IDs for the requested benchmark")
    benchmark_id = datetime.now(UTC).strftime("source-capacity-%Y%m%dT%H%M%SZ")
    output = roots.enriched / benchmark_id
    responses = output / "responses"
    responses.mkdir(parents=True, exist_ok=True)
    levels = []
    for index, (rate, workers) in enumerate(zip(rates, concurrency)):
        selected = targets[index * sample_per_level:(index + 1) * sample_per_level]
        rng = random.Random(f"{run}:{rate}:{workers}")
        origin = time.monotonic()
        schedule = [origin + (position / rate) + rng.random() * min(0.5, 1.0 / rate) for position in range(len(selected))]
        results = []
        with ThreadPoolExecutor(max_workers=workers) as executor:
            futures = [executor.submit(_one, external_id, ocid, config, responses, when) for (external_id, ocid), when in zip(selected, schedule)]
            for future in as_completed(futures):
                results.append(future.result())
        status_counts: dict[str, int] = {}
        for result in results:
            key = str(result["http_status"] or result["error_class"] or "unknown")
            status_counts[key] = status_counts.get(key, 0) + 1
        levels.append({"requested": len(results), "rate_per_second": rate, "concurrency": workers, "status_counts": status_counts, "valid_ocids": sum(result["validation"] == "valid" for result in results), "mean_elapsed_seconds": sum(result["elapsed_seconds"] for result in results) / len(results), "results": sorted(results, key=lambda result: result["external_id"])})
    report = {"benchmark_id": benchmark_id, "source_run_id": run, "source_snapshot_sha256": source_sha, "source": config.source, "levels": levels, "limitations": ["This is a bounded capacity probe, not a production fetch.", "The benchmark uses verified PPIP IDs and does not spoof identity or bypass rate limits.", "A concurrency setting is safe for production only if status, timeout, and OCID validation results remain acceptable."], "status": "pass" if all(level["valid_ocids"] == level["requested"] for level in levels) else "warn"}
    (output / "capacity_report.json").write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    return report
