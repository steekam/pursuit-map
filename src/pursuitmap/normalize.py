from __future__ import annotations

import gzip
import json
from collections.abc import Iterator
from datetime import UTC, datetime
from pathlib import Path

import duckdb

from .paths import PARQUET_ROOT, RAW_ROOT, WORKING_ROOT, ensure_data_dirs
from .provenance import parquet_checksums, source_hash, utc_now, write_run_manifest


TABLE_COLUMNS = {
    "releases": ["source_snapshot_sha256", "ocid", "release_id", "release_date_raw", "release_date", "release_date_status", "tags_json", "initiation_type", "buyer_id", "buyer_name", "publisher_name", "language", "raw_json"],
    "buyers": ["source_snapshot_sha256", "buyer_id", "name", "normalized_name", "identifier_status"],
    "suppliers": ["source_snapshot_sha256", "supplier_id", "name", "normalized_name", "identifier_status"],
    "procurement_plans": ["source_snapshot_sha256", "ocid", "release_id", "release_date", "planning_present", "rationale", "budget_description", "budget_amount_raw", "budget_amount", "budget_currency", "budget_status", "period_start_raw", "period_start", "period_start_status", "period_end_raw", "period_end", "period_end_status", "items_count", "raw_json"],
    "procurement_plan_items": ["source_snapshot_sha256", "ocid", "release_id", "release_date", "buyer_id", "buyer_name", "item_id", "description", "classification_scheme", "classification_id", "classification_description", "quantity", "unit_name", "value_amount_raw", "value_amount", "value_currency", "value_status", "period_start_raw", "period_start", "period_start_status", "period_end_raw", "period_end", "period_end_status", "raw_json"],
    "tenders": ["source_snapshot_sha256", "ocid", "release_id", "release_date", "buyer_id", "buyer_name", "tender_id", "title", "description", "status", "procurement_method", "procurement_method_details", "category", "main_procurement_category", "additional_categories_json", "procuring_entity_id", "procuring_entity_name", "enquiry_start_raw", "enquiry_start", "enquiry_start_status", "enquiry_end_raw", "enquiry_end", "enquiry_end_status", "period_start_raw", "period_start", "period_start_status", "period_end_raw", "period_end", "period_end_status", "value_amount_raw", "value_amount", "value_currency", "value_status", "raw_json"],
    "awards": ["source_snapshot_sha256", "ocid", "release_id", "release_date", "buyer_id", "buyer_name", "award_id", "title", "description", "status", "date_raw", "date", "date_status", "value_amount_raw", "value_amount", "value_currency", "value_status", "raw_json"],
    "award_suppliers": ["source_snapshot_sha256", "ocid", "release_id", "release_date", "award_id", "supplier_id", "supplier_name", "identifier_status"],
    "contracts": ["source_snapshot_sha256", "ocid", "release_id", "release_date", "buyer_id", "buyer_name", "contract_id", "award_id", "title", "description", "status", "date_signed_raw", "date_signed", "date_signed_status", "period_start_raw", "period_start", "period_start_status", "period_end_raw", "period_end", "period_end_status", "value_amount_raw", "value_amount", "value_currency", "value_status", "raw_json"],
    "documents": ["source_snapshot_sha256", "ocid", "release_id", "release_date", "lifecycle_type", "parent_id", "document_id", "document_type", "title", "url", "date_published_raw", "date_published", "date_published_status"],
    "identity_audit": ["source_snapshot_sha256", "entity_type", "source_id", "source_name", "normalized_name", "identifier_status", "name_variant_count", "id_variant_count", "source_record_count"],
}

SENTINEL_DATES = {"0001-01-01T00:00:00Z", "0001-01-01T00:00:00+00:00", "0001-01-01T00:00:00"}


def normalize_name(value: object) -> str | None:
    if value is None:
        return None
    collapsed = " ".join(str(value).strip().lower().split())
    return collapsed or None


def as_json(value: object) -> str | None:
    return None if value is None else json.dumps(value, ensure_ascii=False, sort_keys=True)


def number(value: object) -> float | None:
    if value in (None, ""):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def date_info(value: object) -> tuple[str | None, str | None, str]:
    if value in (None, ""):
        return None, None, "missing"
    raw = str(value)
    if raw in SENTINEL_DATES:
        return raw, None, "sentinel"
    try:
        parsed = datetime.fromisoformat(raw.replace("Z", "+00:00"))
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=UTC)
        return raw, parsed.astimezone(UTC).isoformat(), "valid"
    except ValueError:
        return raw, None, "invalid"


def period_info(value: object) -> tuple[str | None, str | None, str, str | None, str | None, str]:
    period = value if isinstance(value, dict) else {}
    start_raw, start, start_status = date_info(period.get("startDate", period.get("start")))
    end_raw, end, end_status = date_info(period.get("endDate", period.get("end")))
    return start_raw, start, start_status, end_raw, end, end_status


def value_info(value: object) -> tuple[str | None, float | None, str | None, str]:
    value_obj = value if isinstance(value, dict) else {}
    raw_value = value_obj.get("amount")
    raw = None if raw_value is None else str(raw_value)
    currency = value_obj.get("currency")
    if raw_value in (None, ""):
        return raw, None, currency, "missing"
    parsed = number(raw_value)
    if parsed is None:
        return raw, None, currency, "invalid"
    if parsed == 0:
        return raw, parsed, currency, "zero"
    return raw, parsed, currency, "negative" if parsed < 0 else "valid"


def identifier_status(identifier: object) -> str:
    if identifier in (None, ""):
        return "missing"
    return "placeholder" if str(identifier).strip() in {"0", "000000", "UNKNOWN", "N/A"} else "present"


def iter_releases(path: Path) -> Iterator[dict]:
    opener = gzip.open if path.suffix == ".gz" else open
    with opener(path, "rt", encoding="utf-8") as handle:
        for line_number, line in enumerate(handle, 1):
            if not line.strip():
                continue
            payload = json.loads(line)
            if isinstance(payload, dict) and isinstance(payload.get("releases"), list):
                yield from (release for release in payload["releases"] if isinstance(release, dict))
            elif isinstance(payload, dict):
                yield payload
            else:
                raise ValueError(f"Expected an object on line {line_number}")


def _document_rows(ocid: str, release_id: str, release_date: str | None, lifecycle_type: str, parent_id: str | None, documents: list[dict]) -> list[tuple]:
    rows = []
    for document in documents:
        raw, parsed, status = date_info(document.get("datePublished"))
        rows.append((ocid, release_id, release_date, lifecycle_type, parent_id, document.get("id"), document.get("documentType"), document.get("title"), document.get("url"), raw, parsed, status))
    return rows


def build_rows(release: dict) -> dict[str, list[tuple]]:
    ocid = release.get("ocid")
    release_id = release.get("id")
    release_date_raw, release_date, release_date_status = date_info(release.get("date"))
    buyer = release.get("buyer") or {}
    publisher = release.get("publisher") or {}
    rows = {name: [] for name in TABLE_COLUMNS}
    rows["releases"].append((ocid, release_id, release_date_raw, release_date, release_date_status, as_json(release.get("tag") or []), release.get("initiationType"), buyer.get("id"), buyer.get("name"), publisher.get("name"), release.get("language"), as_json(release)))
    if buyer.get("id") or buyer.get("name"):
        rows["buyers"].append((buyer.get("id"), buyer.get("name"), normalize_name(buyer.get("name")), identifier_status(buyer.get("id"))))

    planning = release.get("planning")
    if isinstance(planning, dict):
        budget = planning.get("budget") or {}
        budget_raw, budget_amount, budget_currency, budget_status = value_info(budget)
        psr, psp, pss, per, pep, pes = period_info(planning.get("period"))
        items = planning.get("items") or []
        rows["procurement_plans"].append((ocid, release_id, release_date, True, planning.get("rationale"), budget.get("description"), budget_raw, budget_amount, budget_currency, budget_status, psr, psp, pss, per, pep, pes, len(items), as_json(planning)))
        for item in items:
            isr, isp, iss, ier, iep, ies = period_info(item.get("period"))
            raw_value, amount, currency, value_status = value_info(item.get("value"))
            classification = item.get("classification") or {}
            rows["procurement_plan_items"].append((ocid, release_id, release_date, buyer.get("id"), buyer.get("name"), item.get("id"), item.get("description"), classification.get("scheme"), classification.get("id"), classification.get("description"), number(item.get("quantity")), (item.get("unit") or {}).get("name"), raw_value, amount, currency, value_status, isr, isp, iss, ier, iep, ies, as_json(item)))
        rows["documents"].extend(_document_rows(ocid, release_id, release_date, "planning", None, planning.get("documents") or []))

    tender = release.get("tender")
    if isinstance(tender, dict):
        er, ep, es, ee, eep, ees = period_info(tender.get("enquiryPeriod"))
        tsr, tsp, tss, ter, tep, tes = period_info(tender.get("tenderPeriod"))
        raw_value, amount, currency, value_status = value_info(tender.get("value"))
        procuring = tender.get("procuringEntity") or {}
        rows["tenders"].append((ocid, release_id, release_date, buyer.get("id"), buyer.get("name"), tender.get("id"), tender.get("title"), tender.get("description"), tender.get("status"), tender.get("procurementMethod"), tender.get("procurementMethodDetails"), tender.get("category"), tender.get("mainProcurementCategory"), as_json(tender.get("additionalProcurementCategories") or []), procuring.get("id"), procuring.get("name"), er, ep, es, ee, eep, ees, tsr, tsp, tss, ter, tep, tes, raw_value, amount, currency, value_status, as_json(tender)))
        rows["documents"].extend(_document_rows(ocid, release_id, release_date, "tender", tender.get("id"), tender.get("documents") or []))

    for award in release.get("awards") or []:
        award_date_raw, award_date, award_date_status = date_info(award.get("date"))
        raw_value, amount, currency, value_status = value_info(award.get("value"))
        rows["awards"].append((ocid, release_id, release_date, buyer.get("id"), buyer.get("name"), award.get("id"), award.get("title"), award.get("description"), award.get("status"), award_date_raw, award_date, award_date_status, raw_value, amount, currency, value_status, as_json(award)))
        for supplier in award.get("suppliers") or []:
            rows["suppliers"].append((supplier.get("id"), supplier.get("name"), normalize_name(supplier.get("name")), identifier_status(supplier.get("id"))))
            rows["award_suppliers"].append((ocid, release_id, release_date, award.get("id"), supplier.get("id"), supplier.get("name"), identifier_status(supplier.get("id"))))
        rows["documents"].extend(_document_rows(ocid, release_id, release_date, "award", award.get("id"), award.get("documents") or []))

    for contract in release.get("contracts") or []:
        dsr, dsp, dss = date_info(contract.get("dateSigned"))
        csr, csp, css, cer, cep, ces = period_info(contract.get("period"))
        raw_value, amount, currency, value_status = value_info(contract.get("value"))
        rows["contracts"].append((ocid, release_id, release_date, buyer.get("id"), buyer.get("name"), contract.get("id"), contract.get("awardID"), contract.get("title"), contract.get("description"), contract.get("status"), dsr, dsp, dss, csr, csp, css, cer, cep, ces, raw_value, amount, currency, value_status, as_json(contract)))
        rows["documents"].extend(_document_rows(ocid, release_id, release_date, "contract", contract.get("id"), contract.get("documents") or []))
    return rows


def _sql_type(column: str) -> str:
    if column in {"quantity", "value_amount"}:
        return "DOUBLE"
    if column in {"planning_present"}:
        return "BOOLEAN"
    return "VARCHAR"


def _identity_audit(rows: dict[str, list[tuple]]) -> list[tuple]:
    observations: dict[tuple, dict[str, set]] = {}
    for entity_type, table in (("buyer", "buyers"), ("supplier", "suppliers")):
        for identifier, name, normalized, status in rows[table]:
            key = (entity_type, identifier, normalized)
            item = observations.setdefault(key, {"names": set(), "ids": set(), "count": 0, "status": status})
            item["names"].add(name)
            item["ids"].add(identifier)
            item["count"] += 1
    return [(entity_type, source_id, sorted(data["names"], key=lambda value: "" if value is None else str(value))[0] if data["names"] else None, normalized, data["status"], len(data["names"]), len(data["ids"]), data["count"]) for (entity_type, source_id, normalized), data in observations.items()]


def normalize(source_path: Path | None = None) -> dict:
    ensure_data_dirs()
    source_path = source_path or next((path for path in (RAW_ROOT / "ocds_full.jsonl.gz", RAW_ROOT / "ocds_full.jsonl") if path.exists()), RAW_ROOT / "ocds_full.jsonl.gz")
    if not source_path.exists():
        raise FileNotFoundError(f"Source not found: {source_path}. Run `pursuitmap ingest za` first.")
    source_sha = source_hash(source_path, source_path.parent / "manifest.json")
    rows = {name: [] for name in TABLE_COLUMNS}
    release_count = 0
    for release in iter_releases(source_path):
        release_count += 1
        built = build_rows(release)
        for table, table_rows in built.items():
            rows[table].extend(table_rows)
    rows["identity_audit"] = _identity_audit(rows)
    for table in ("buyers", "suppliers"):
        rows[table] = list({(row[0], row[1]): row for row in rows[table]}.values())
    for table in TABLE_COLUMNS:
        rows[table] = [(source_sha, *row) for row in rows[table]]

    database_path = WORKING_ROOT / "south_africa.duckdb"
    connection = duckdb.connect(str(database_path))
    for table, columns in TABLE_COLUMNS.items():
        connection.execute(f'DROP TABLE IF EXISTS "{table}"')
        definitions = ", ".join(f'"{column}" {_sql_type(column)}' for column in columns)
        connection.execute(f'CREATE TABLE "{table}" ({definitions})')
        if rows[table]:
            placeholders = ", ".join("?" for _ in columns)
            connection.executemany(f'INSERT INTO "{table}" VALUES ({placeholders})', rows[table])
        connection.execute(f'COPY "{table}" TO ? (FORMAT PARQUET, COMPRESSION ZSTD)', [str(PARQUET_ROOT / f"{table}.parquet")])
    connection.close()

    manifest = {
        "normalized_at": utc_now(),
        "source_path": str(source_path),
        "source_snapshot_sha256": source_sha,
        "release_count": release_count,
        "row_counts": {table: len(table_rows) for table, table_rows in rows.items()},
        "database": str(database_path),
        "parquet_root": str(PARQUET_ROOT),
        "parquet_sha256": parquet_checksums(PARQUET_ROOT),
    }
    run, run_manifest_path = write_run_manifest("normalize", source_sha, manifest)
    manifest["run_id"] = run
    manifest["run_manifest"] = str(run_manifest_path)
    (WORKING_ROOT / "normalization_manifest.json").write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    return manifest
