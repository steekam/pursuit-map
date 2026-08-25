from __future__ import annotations

import hashlib
import json
import time
from pathlib import Path
from urllib.parse import urlencode

import duckdb
from openpyxl import load_workbook

from .durable_source_enrichment import BASE_URL, RateLimiter, _fetch, classify_status, load_config
from .paths import canonical_root, country_paths
from .provenance import run_id, source_hash, utc_now


FINANCIAL_YEARS = ((39, "2026-2027"), (36, "2025-2026"), (22, "2024-2025"), (21, "2023-2024"), (20, "2022-2023"), (19, "2021-2022"), (13, "2020-2021"), (14, "2019-2020"), (15, "2018-2019"), (38, "2016-2017"), (37, "2015-2016"))


def capture(country: str = "ke", config_path: Path | None = None) -> dict:
    if country != "ke":
        raise ValueError("The contract export capture supports country=ke")
    roots = country_paths(country)
    source_sha = source_hash(roots.raw / "ocds_full.jsonl.gz", roots.raw / "manifest.json")
    run = run_id(source_sha, "contract-export")
    output_root = roots.enriched / run
    output_root.mkdir(parents=True, exist_ok=True)
    raw_root = output_root / "raw"
    raw_root.mkdir(exist_ok=True)
    config = load_config(config_path)
    limiter = RateLimiter(config.refill_rate_per_second, config.jitter_seconds)
    rows: list[tuple] = []
    files: list[dict] = []
    failures: list[dict] = []
    for year_id, label in FINANCIAL_YEARS:
        clauses = json.dumps([{"col": "financial_year_id", "value": year_id, "type": "nominal"}], separators=(",", ":"))
        url = f"{BASE_URL}/api/export-published-contracts"
        params = {"clauses": clauses}
        payload = b""
        status = None
        headers: dict = {}
        error_text = None
        for attempt in range(1, config.max_attempts + 1):
            limiter.wait()
            try:
                status, headers, payload = _fetch(url, params, 60)
                if status == 200:
                    break
                retryable, error_class = classify_status(status, None, config.retry_statuses)
                error_text = error_class
                if not retryable:
                    break
            except Exception as error:
                retryable, error_class = classify_status(None, error, config.retry_statuses)
                error_text = error_class
                if not retryable:
                    break
            time.sleep(min(config.max_backoff_seconds, 2 ** attempt))
        if status != 200:
            failures.append({"financial_year": label, "status": status, "error": error_text})
            continue
        digest = hashlib.sha256(payload).hexdigest()
        path = raw_root / f"contracts-{label}.xlsx"
        path.write_bytes(payload)
        files.append({"financial_year": label, "financial_year_id": year_id, "url": url, "params": params, "status": status, "sha256": digest, "bytes": len(payload), "path": str(path), "retrieved_at": utc_now()})
        workbook = load_workbook(path, read_only=True, data_only=True)
        sheet = workbook.active
        header = [str(cell.value or "").strip() for cell in next(sheet.iter_rows(max_row=1))]
        for row_number, values in enumerate(sheet.iter_rows(min_row=2, values_only=True), start=2):
            if not any(value is not None and str(value).strip() for value in values):
                continue
            values = list(values) + [None] * (len(header) - len(values))
            rows.append((label, year_id, digest, row_number, *[None if value is None else str(value) for value in values[:len(header)]]))
        workbook.close()
    data_path = output_root / "contract_export_rows.parquet"
    report_path = output_root / "contract_export_report.json"
    connection = duckdb.connect()
    if rows:
        header = [str(cell.value or "").strip() for cell in next(load_workbook(files[0]["path"], read_only=True, data_only=True).active.iter_rows(max_row=1))]
        names = ["financial_year", "financial_year_id", "source_file_sha256", "source_row_number"] + [f"field_{index}_{name.lower().replace(' ', '_').replace('.', '')}" for index, name in enumerate(header)]
        types = ",".join(f'"{name}" VARCHAR' for name in names)
        connection.execute(f"CREATE TABLE export_rows ({types})")
        connection.executemany(f"INSERT INTO export_rows VALUES ({','.join('?' for _ in names)})", rows)
        connection.execute("COPY export_rows TO ? (FORMAT PARQUET, COMPRESSION ZSTD)", [str(data_path)])
    known_refs: dict[str, set[str]] = {}
    for enrichment_path in roots.enriched.glob("*/source_enrichment.parquet"):
        for tender_number, ocid in connection.execute("SELECT tender_number, ocid FROM read_parquet(?) WHERE tender_number IS NOT NULL AND ocid IS NOT NULL", [str(enrichment_path)]).fetchall():
            known_refs.setdefault(str(tender_number).strip().lower(), set()).add(str(ocid))
    export_reference_values = [row[19].strip().lower() for row in rows if len(row) > 19 and row[19]]
    exact = sum(1 for value in export_reference_values if value in known_refs)
    exact_ocids = len({ocid for value in export_reference_values for ocid in known_refs.get(value, set())})
    connection.close()
    report = {"run_id": run, "source_snapshot_sha256": source_sha, "generated_at": utc_now(), "files": files, "failures": failures, "export_rows": len(rows), "exact_known_enrichment_reference_matches": exact, "exact_match_unique_validated_ocids": exact_ocids, "accepted_canonical_additions": 0, "limitation": "The Excel export contains no OCID or tender ID. Exact tender-reference matches remain diagnostics until an OCID-bearing response validates the join.", "output_root": str(output_root)}
    report_path.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    return report
