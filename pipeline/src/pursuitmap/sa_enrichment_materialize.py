from __future__ import annotations

import hashlib
import json
import time
from pathlib import Path

import duckdb

from .paths import canonical_root, country_paths
from .provenance import sha256_file, source_hash, utc_now, write_run_manifest


VERSION = "sa-api-combined-1"
API_FIELDS = (
    "province",
    "delivery_location",
    "special_conditions",
    "contact_person",
    "briefing_session",
    "tenderers",
    "parties",
    "documents",
)
CANONICAL_FIELDS = {
    "title": "title",
    "description": "description",
    "procurement_method": "procurement_method",
    "procurement_method_details": "procurement_method_details",
    "category": "category",
    "main_procurement_category": "main_procurement_category",
    "additional_categories": "additional_categories_json",
    "procuring_entity": "procuring_entity_name",
    "period_start": "period_start",
    "period_end": "period_end",
    "value_amount": "value_amount",
}


def _present(value: object) -> bool:
    if value is None or value == "" or value == {} or value == []:
        return False
    if isinstance(value, str) and value.strip() in {"", "[]", "{}"}:
        return False
    return True


def _api_fields(payload: dict) -> dict[str, object]:
    tender = payload.get("tender") or {}
    return {
        "province": tender.get("province"),
        "delivery_location": tender.get("deliveryLocation"),
        "special_conditions": tender.get("specialConditions"),
        "contact_person": tender.get("contactPerson"),
        "briefing_session": tender.get("briefingSession"),
        "tenderers": tender.get("tenderers") or [],
        "parties": payload.get("parties") or [],
        "documents": tender.get("documents") or [],
    }


def _digest(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()[:16]


def materialize(supervisor_run_id: str, *, normalization_run_id: str | None = None) -> dict:
    roots = country_paths("za")
    supervisor_root = roots.enriched / supervisor_run_id
    ledger_path = supervisor_root / "ledger.duckdb"
    if not ledger_path.exists():
        raise FileNotFoundError(ledger_path)
    source_sha = source_hash(roots.raw / "ocds_full.jsonl.gz", roots.raw / "manifest.json")
    canonical = canonical_root("za", normalization_run_id)
    normalization_run_id = normalization_run_id or json.loads(
        (roots.working / "normalization_manifest.json").read_text(encoding="utf-8")
    )["run_id"]
    run_id = f"sa-api-combined-{time.strftime('%Y%m%dT%H%M%SZ', time.gmtime())}-{_digest(supervisor_run_id + source_sha)}"
    output_root = roots.enriched / run_id
    output_root.mkdir(parents=True, exist_ok=False)
    connection = duckdb.connect(str(ledger_path), read_only=True)
    output_connection = duckdb.connect()
    matches = connection.execute(
        """SELECT DISTINCT ON (ocid) ocid, parent_run_id, source_kind, probe_family,
                  response_hash, response_path, validation_status, observed_ocid
           FROM supervisor_matches
           WHERE run_id=? AND validation_status IN ('validated','bulk_observation','cache_hit')
           ORDER BY ocid, CASE validation_status WHEN 'validated' THEN 0 WHEN 'cache_hit' THEN 1 ELSE 2 END,
                    response_hash""",
        [supervisor_run_id],
    ).fetchall()
    canonical_path = str(canonical / "tenders.parquet")
    canonical_rows = connection.execute(
        "SELECT * FROM read_parquet(?) ORDER BY ocid, release_id", [canonical_path]
    ).fetchall()
    canonical_columns = [row[0] for row in connection.execute("DESCRIBE SELECT * FROM read_parquet(?)", [canonical_path]).fetchall()]
    canonical_by_ocid = {row[canonical_columns.index("ocid")]: dict(zip(canonical_columns, row)) for row in canonical_rows}
    rows: list[dict] = []
    api_presence = {field: 0 for field in API_FIELDS}
    for ocid, parent_run_id, source_kind, probe_family, response_hash, response_path, validation_status, observed_ocid in matches:
        source = canonical_by_ocid.get(ocid)
        if source is None or not response_path or not Path(response_path).exists():
            continue
        payload = json.loads(Path(response_path).read_text(encoding="utf-8"))
        fields = _api_fields(payload)
        for field, value in fields.items():
            api_presence[field] += int(_present(value))
        row = {
            "source_snapshot_sha256": source_sha,
            "combined_run_id": run_id,
            "supervisor_run_id": supervisor_run_id,
            "parent_run_id": parent_run_id,
            "normalization_run_id": normalization_run_id,
            "ocid": ocid,
            "release_id": source.get("release_id"),
            "source_kind": source_kind,
            "probe_family": probe_family,
            "validation_status": validation_status,
            "observed_ocid": observed_ocid,
            "response_hash": response_hash,
            "response_path": response_path,
            "api_release_date": payload.get("date"),
            "api_release_id": payload.get("id"),
        }
        row.update({f"canonical_{field}": source.get(column) for field, column in CANONICAL_FIELDS.items()})
        row.update({f"api_{field}_json": json.dumps(value, ensure_ascii=False, sort_keys=True) if isinstance(value, (dict, list)) else value for field, value in fields.items()})
        rows.append(row)
    columns = list(rows[0]) if rows else ["source_snapshot_sha256", "combined_run_id", "ocid"]
    if rows:
        values = [tuple(row[column] for column in columns) for row in rows]
        placeholders = ",".join("(" + ",".join("?" for _ in columns) + ")" for _ in values)
        output_connection.execute(f"CREATE TABLE combined AS SELECT * FROM (VALUES {placeholders}) AS t({','.join(columns)})", [v for row in values for v in row])
    else:
        output_connection.execute("CREATE TABLE combined (source_snapshot_sha256 VARCHAR, combined_run_id VARCHAR, ocid VARCHAR)")
    output_path = output_root / "sa_api_combined.parquet"
    output_connection.execute("COPY combined TO ? (FORMAT PARQUET, COMPRESSION ZSTD)", [str(output_path)])
    total = len(canonical_rows)
    matched = len(rows)
    canonical_presence = {}
    for field, column in CANONICAL_FIELDS.items():
        canonical_presence[field] = sum(int(_present(row[canonical_columns.index(column)])) for row in canonical_rows)
    quality = {
        "version": VERSION,
        "source_snapshot_sha256": source_sha,
        "supervisor_run_id": supervisor_run_id,
        "normalization_run_id": normalization_run_id,
        "canonical_total": total,
        "combined_rows": matched,
        "coverage": matched / total if total else 0,
        "unmatched_canonical": total - matched,
        "field_coverage": {
            "canonical_baseline": {field: {"present": count, "denominator": total, "coverage": count / total if total else 0} for field, count in canonical_presence.items()},
            "api_enriched": {field: {"present": count, "denominator": matched, "coverage": count / matched if matched else 0} for field, count in api_presence.items()},
        },
        "limitations": [
            "API fields are observations from validated source responses.",
            "Coverage measures field presence, not correctness or commercial value.",
            "Two exact-OCID requests remain unresolved after repeated HTTP 500 responses.",
        ],
        "generated_at": utc_now(),
        "outputs": {"combined": str(output_path)},
    }
    (output_root / "sa_api_quality_report.json").write_text(json.dumps(quality, indent=2) + "\n", encoding="utf-8")
    lines = ["# South Africa API enrichment quality report", "", f"- Combined rows: {matched:,}/{total:,} ({quality['coverage']:.3%})", f"- Unmatched canonical records: {total - matched:,}", "", "## Field coverage", ""]
    for group, fields in quality["field_coverage"].items():
        lines.append(f"### {group}")
        lines.extend(f"- {field}: {value['present']:,}/{value['denominator']:,} ({value['coverage']:.3%})" for field, value in fields.items())
        lines.append("")
    lines.extend(["## Limitations", "", *[f"- {item}" for item in quality["limitations"]], ""])
    (output_root / "sa_api_quality_report.md").write_text("\n".join(lines), encoding="utf-8")
    manifest_payload = {"supervisor_run_id": supervisor_run_id, "normalization_run_id": normalization_run_id, "quality_report": quality, "output_root": str(output_root), "checksums": {output_path.name: sha256_file(output_path)}}
    _, manifest_path = write_run_manifest("sa-api-combined", source_sha, manifest_payload, run=run_id, working_root=roots.working)
    output_connection.close()
    connection.close()
    quality["run_id"] = run_id
    quality["manifest"] = str(manifest_path)
    return quality
