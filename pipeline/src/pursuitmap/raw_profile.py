from __future__ import annotations

from collections import Counter
from datetime import datetime
from pathlib import Path

from .normalize import date_info, identifier_status, iter_releases, value_info


def _count_documents(release: dict) -> int:
    total = len(release.get("documents") or [])
    total += len((release.get("planning") or {}).get("documents") or [])
    total += len((release.get("tender") or {}).get("documents") or [])
    total += sum(len(award.get("documents") or []) for award in release.get("awards") or [])
    total += sum(len(contract.get("documents") or []) for contract in release.get("contracts") or [])
    return total


def _date_range(values: list[str]) -> dict[str, str | None]:
    parsed = [datetime.fromisoformat(value.replace("Z", "+00:00")) for value in values]
    return {"min": min(parsed).isoformat() if parsed else None, "max": max(parsed).isoformat() if parsed else None}


def profile_raw(source_path: Path) -> dict:
    counts = Counter()
    missingness = Counter()
    value_status = Counter()
    date_status = Counter()
    tender_starts: list[str] = []
    tender_ends: list[str] = []
    category_counts = Counter()

    for release in iter_releases(source_path):
        counts["releases"] += 1
        counts["tenders"] += int(isinstance(release.get("tender"), dict))
        counts["awards"] += len(release.get("awards") or [])
        counts["contracts"] += len(release.get("contracts") or [])
        counts["planning"] += int(isinstance(release.get("planning"), dict))
        counts["planning_items"] += len((release.get("planning") or {}).get("items") or [])
        counts["documents"] += _count_documents(release)
        counts["tender_items"] += len((release.get("tender") or {}).get("items") or [])
        counts["award_items"] += sum(len(award.get("items") or []) for award in release.get("awards") or [])
        counts["contract_items"] += sum(len(contract.get("items") or []) for contract in release.get("contracts") or [])
        counts["award_suppliers"] += sum(len(award.get("suppliers") or []) for award in release.get("awards") or [])

        missingness["ocid"] += int(not release.get("ocid"))
        missingness["release_id"] += int(not release.get("id"))
        missingness["release_date"] += int(not release.get("date"))
        buyer = release.get("buyer") or {}
        missingness["buyer_id"] += int(not buyer.get("id"))
        missingness["buyer_name"] += int(not buyer.get("name"))

        tender = release.get("tender") or {}
        raw_start, start, start_status, raw_end, end, end_status = (
            *date_info((tender.get("tenderPeriod") or {}).get("startDate")),
            *date_info((tender.get("tenderPeriod") or {}).get("endDate")),
        )
        date_status[f"tender_period_start_{start_status}"] += 1
        date_status[f"tender_period_end_{end_status}"] += 1
        if start_status == "valid" and start and 2000 <= datetime.fromisoformat(start).year <= 2100:
            tender_starts.append(start)
        if end_status == "valid" and end and 2000 <= datetime.fromisoformat(end).year <= 2100:
            tender_ends.append(end)
        missingness["tender_period_start"] += int(start_status != "valid" or (bool(start) and not 2000 <= datetime.fromisoformat(start).year <= 2100))
        missingness["tender_period_end"] += int(end_status != "valid" or (bool(end) and not 2000 <= datetime.fromisoformat(end).year <= 2100))
        category = tender.get("mainProcurementCategory")
        if category:
            category_counts[str(category)] += 1

        for value in [tender.get("value"), *(award.get("value") for award in release.get("awards") or []), *(contract.get("value") for contract in release.get("contracts") or [])]:
            value_status[value_info(value)[3]] += 1
        for award in release.get("awards") or []:
            for supplier in award.get("suppliers") or []:
                status = identifier_status(supplier.get("id"))
                missingness["supplier_id"] += int(status == "missing")
                missingness["supplier_id_placeholder"] += int(status == "placeholder")

    release_count = counts["releases"]
    return {
        "counts": {
            "releases": release_count,
            "buyers": release_count - missingness["buyer_id"],
            "suppliers": counts["award_suppliers"] - missingness["supplier_id"],
            "procurement_plans": counts["planning"],
            "procurement_plan_items": counts["planning_items"],
            "tenders": counts["tenders"],
            "awards": counts["awards"],
            "award_suppliers": counts["award_suppliers"],
            "contracts": counts["contracts"],
            "documents": counts["documents"],
            "identity_audit": 0,
        },
        "release_date_ranges": {},
        "stage_date_ranges": {
            "tenders": _date_range(tender_starts),
            "tender_period_end": _date_range(tender_ends),
        },
        "missingness_null_or_blank_counts": {"source_fields": dict(missingness)},
        "category_and_document_coverage": {
            "tender_main_procurement_category_non_null": sum(category_counts.values()),
            "tender_main_procurement_category_distinct": len(category_counts),
            "document_url_non_null": None,
        },
        "top_tender_categories": [
            {"category": category, "tender_count": count}
            for category, count in category_counts.most_common(10)
        ],
        "top_buyers_by_tender_count": [],
        "top_suppliers_by_award_count": [],
        "anomalies": {
            "value_status_counts": dict(value_status),
            "date_status_counts": dict(date_status),
            "tender_items": counts["tender_items"],
            "award_items": counts["award_items"],
            "contract_items": counts["contract_items"],
        },
        "verification": {
            "status": "warn",
            "checks": [{"name": "raw_profile_only", "value": True, "status": "warn"}],
        },
        "measured_from": "raw OCDS JSONL",
        "assumptions": [
            "The raw profile counts source objects without canonical deduplication.",
            "Buyer and supplier counts are presence counts, not distinct entity counts.",
        ],
        "limitations": [
            "This source has no canonical Parquet tables yet.",
            "Raw profiling cannot verify relational integrity or normalized identity collisions.",
        ],
    }
