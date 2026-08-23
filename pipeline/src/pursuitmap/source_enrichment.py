from __future__ import annotations

import hashlib
import html
import json
import re
import urllib.request
from datetime import UTC, datetime
from html.parser import HTMLParser
from pathlib import Path

import duckdb

from .paths import canonical_root, country_paths, ensure_data_dirs
from .provenance import parquet_checksums, run_id, source_hash, utc_now, write_run_manifest


SOURCE = "kenya_ppip_tender_page"
SCHEMA = [
    "source_snapshot_sha256", "country", "ocid", "release_id", "external_record_id",
    "source_url", "source_retrieved_at", "source_http_status", "source_content_sha256",
    "tender_number", "title", "procuring_entity_id", "procuring_entity_name",
    "procuring_entity_pin", "procurement_method", "procurement_method_code",
    "procurement_category", "procurement_category_code", "submission_methods_json",
    "reservation_scheme_json", "opening_venue", "published_date_raw", "close_date_raw",
    "opening_date_raw", "tender_fee_raw", "validity_days_raw", "financial_year",
    "preference_reservation_raw", "attachments_json", "raw_response_path",
]
LABELS = [
    "OCID", "TENDER NUMBER", "TITLE", "PROCUREMENT METHOD", "PROCUREMENT CATEGORY",
    "SUBMISSION METHODS", "RESERVATION SCHEME", "OPENING VENUE", "PUBLISHED DATE",
    "CLOSE DATE AND TIME", "TENDER FEE", "TENDER VALIDITY IN DAYS", "FINANCIAL YEAR",
    "PREFERENCE AND RESERVATION SCHEME", "PUBLIC LINK",
]


class _PageParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.text: list[str] = []
        self.hrefs: list[str] = []
        self._in_script = False

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag in {"script", "style"}:
            self._in_script = True
        for key, value in attrs:
            if key == "href" and value:
                self.hrefs.append(html.unescape(value))

    def handle_endtag(self, tag: str) -> None:
        if tag in {"script", "style"}:
            self._in_script = False

    def handle_data(self, data: str) -> None:
        if not self._in_script:
            value = " ".join(html.unescape(data).split())
            if value:
                self.text.append(value)


def _field_values(text: list[str]) -> dict[str, str]:
    upper = [value.upper() for value in text]
    positions = {label: upper.index(label) for label in LABELS if label in upper}
    result: dict[str, str] = {}
    ordered = sorted(positions.items(), key=lambda pair: pair[1])
    for index, (label, position) in enumerate(ordered):
        end = ordered[index + 1][1] if index + 1 < len(ordered) else len(text)
        values = text[position + 1:end]
        result[label] = "\n".join(values).strip()
    return result


def parse_tender_page(payload: bytes) -> dict:
    parser = _PageParser()
    parser.feed(payload.decode("utf-8", errors="replace"))
    fields = _field_values(parser.text)
    attachment_start = next((index for index, value in enumerate(parser.text) if value.upper() == "ATTACHMENTS"), None)
    attachments: list[dict[str, str | None]] = []
    if attachment_start is not None:
        for index, value in enumerate(parser.text[attachment_start + 1:], attachment_start + 1):
            if value.upper() in {"TENDER NOTICE", "TENDER DOCUMENT", "ADDENDUM", "CLARIFICATION"}:
                attachments.append({"description": parser.text[index + 1] if index + 1 < len(parser.text) else value, "source_url": next((href for href in parser.hrefs if href.lower().endswith('.pdf')), None)})
    return {
        "ocid": fields.get("OCID"), "tender_number": fields.get("TENDER NUMBER"),
        "title": fields.get("TITLE"), "procurement_method": fields.get("PROCUREMENT METHOD"),
        "procurement_category": fields.get("PROCUREMENT CATEGORY"),
        "submission_methods_json": json.dumps(fields.get("SUBMISSION METHODS", "").splitlines()),
        "reservation_scheme_json": json.dumps(fields.get("RESERVATION SCHEME", "").splitlines()),
        "opening_venue": fields.get("OPENING VENUE"), "published_date_raw": fields.get("PUBLISHED DATE"),
        "close_date_raw": fields.get("CLOSE DATE AND TIME"), "tender_fee_raw": fields.get("TENDER FEE"),
        "validity_days_raw": fields.get("TENDER VALIDITY IN DAYS"), "financial_year": fields.get("FINANCIAL YEAR"),
        "preference_reservation_raw": fields.get("PREFERENCE AND RESERVATION SCHEME"),
        "attachments_json": json.dumps(attachments, ensure_ascii=False, sort_keys=True),
    }


def parse_tender_payload(payload: bytes) -> dict:
    record = json.loads(payload)
    entity = record.get("pe") or {}
    method = record.get("procurement_method") or {}
    category = record.get("procurement_category") or {}
    year = record.get("financial_year") or {}
    return {
        "ocid": record.get("ocid"), "tender_number": record.get("tender_ref"),
        "title": record.get("title"), "procuring_entity_id": entity.get("id"),
        "procuring_entity_name": entity.get("name"), "procuring_entity_pin": entity.get("pin"),
        "procurement_method": method.get("title"), "procurement_method_code": method.get("code"),
        "procurement_category": category.get("title"), "procurement_category_code": category.get("code"),
        "submission_methods_json": json.dumps(record.get("submission_methods") or [], ensure_ascii=False, sort_keys=True),
        "reservation_scheme_json": json.dumps(record.get("bidder_categories") or [], ensure_ascii=False, sort_keys=True),
        "opening_venue": record.get("venue"), "published_date_raw": record.get("published_at"),
        "close_date_raw": record.get("close_at"), "opening_date_raw": record.get("opening_date"),
        "tender_fee_raw": None if record.get("tender_fee") is None else str(record.get("tender_fee")),
        "validity_days_raw": None if record.get("validity_in_days") is None else str(record.get("validity_in_days")),
        "financial_year": year.get("name"),
        "preference_reservation_raw": str(record.get("is_reservation")) if record.get("is_reservation") is not None else None,
        "attachments_json": json.dumps(record.get("documents") or [], ensure_ascii=False, sort_keys=True),
    }


def _page_id(ocid: str) -> str | None:
    match = re.match(r"^ocds-5whusi-(\d+)(?:-|$)", ocid or "")
    return match.group(1) if match else None


def _sha256(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def enrich_source(country: str = "ke", *, limit: int = 20, timeout: int = 30, ocids: list[str] | None = None) -> dict:
    if country != "ke":
        raise ValueError("The Kenya PPIP page adapter only supports country=ke")
    ensure_data_dirs(country)
    roots = country_paths(country)
    parquet_root = canonical_root(country)
    source_sha = source_hash(roots.raw / "ocds_full.jsonl.gz", roots.raw / "manifest.json")
    run = run_id(source_sha, "source-enrich")
    output_root = roots.enriched / run
    raw_root = output_root / "raw_pages"
    raw_root.mkdir(parents=True, exist_ok=False)
    connection = duckdb.connect()
    if ocids:
        placeholders = ",".join("?" for _ in ocids)
        targets = connection.execute(f"SELECT ocid, release_id FROM read_parquet(?) WHERE ocid IN ({placeholders}) ORDER BY ocid, release_id", [str(parquet_root / "tenders.parquet"), *ocids]).fetchall()
    else:
        targets = connection.execute("SELECT ocid, min(release_id) AS release_id FROM read_parquet(?) WHERE regexp_matches(ocid, '^ocds-5whusi-[1-9][0-9]+') GROUP BY ocid ORDER BY ocid LIMIT ?", [str(parquet_root / "tenders.parquet"), limit]).fetchall()
    rows: list[tuple] = []
    page_manifest: list[dict] = []
    for ocid, release_id in targets:
        external_id = _page_id(ocid)
        if not external_id:
            continue
        url = f"https://tenders.go.ke/api/tender/{external_id}"
        retrieved_at = utc_now()
        request = urllib.request.Request(url, headers={"User-Agent": "PursuitMap/0.1 source-enrichment"})
        try:
            with urllib.request.urlopen(request, timeout=timeout) as response:
                payload = response.read()
                status = response.status
        except Exception as error:
            page_manifest.append({"external_record_id": external_id, "source_url": url, "retrieved_at": retrieved_at, "error": str(error)})
            continue
        raw_path = raw_root / f"{external_id}.json"
        raw_path.write_bytes(payload)
        parsed = parse_tender_payload(payload)
        if parsed.get("ocid") != ocid:
            page_manifest.append({"external_record_id": external_id, "source_url": url, "retrieved_at": retrieved_at, "http_status": status, "error": "source_record_mismatch", "page_ocid": parsed.get("ocid"), "expected_ocid": ocid, "raw_page": str(raw_path)})
            continue
        rows.append((source_sha, country, ocid, release_id, external_id, url, retrieved_at, status, _sha256(payload), *(parsed.get(column) for column in SCHEMA[9:-1]), str(raw_path)))
        page_manifest.append({"external_record_id": external_id, "source_url": url, "retrieved_at": retrieved_at, "http_status": status, "content_sha256": _sha256(payload), "raw_page": str(raw_path)})
    connection.execute("CREATE TABLE source_enrichment AS SELECT * FROM (VALUES " + ",".join("(" + ",".join("?" for _ in SCHEMA) + ")" for _ in rows) + ") AS t(" + ",".join(SCHEMA) + ")" if rows else "CREATE TABLE source_enrichment AS SELECT " + ",".join(f"CAST(NULL AS VARCHAR) AS {column}" for column in SCHEMA) + " WHERE FALSE", [value for row in rows for value in row] if rows else [])
    parquet_path = output_root / "source_enrichment.parquet"
    connection.execute("COPY source_enrichment TO ? (FORMAT PARQUET, COMPRESSION ZSTD)", [str(parquet_path)])
    connection.close()
    manifest = {"country": country, "source": SOURCE, "source_url_template": "https://tenders.go.ke/api/tender/{external_record_id}", "source_snapshot_sha256": source_sha, "canonical_root": str(parquet_root), "output_root": str(output_root), "requested_count": len(targets), "fetched_count": len(rows), "page_manifest": page_manifest, "parquet_sha256": parquet_checksums(output_root), "retrieved_at": utc_now(), "limitations": ["This adapter captures official PPIP JSON metadata and attachment metadata. It does not download attachment binaries."]}
    run, manifest_path = write_run_manifest("source-enrich", source_sha, manifest, run=run, working_root=roots.working)
    manifest["run_manifest"] = str(manifest_path)
    (output_root / "source_enrichment_manifest.json").write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    (roots.working / "source_enrichment_manifest.json").write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    return manifest
