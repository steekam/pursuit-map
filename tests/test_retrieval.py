from __future__ import annotations

from pursuitmap.retrieval import load_taxonomy, score_record, score_records


def test_positive_ict_record_scores_networking_and_exposes_breakdown():
    record = {
        "id": "ict-1",
        "title": "Network switch replacement",
        "description": "Upgrade core network routers, switches, and access points.",
        "evidence": {"ocid": "ocds-ict-1", "source_url": "https://example.test/ict-1"},
    }

    result = score_record(record)

    assert result["decision"] == "include"
    assert result["best_category"]["category_id"] == "networking"
    assert result["best_category"]["score_breakdown"]
    assert "network" in result["best_category"]["matched_terms"]
    assert "title" in result["best_category"]["matched_fields"]
    assert result["evidence"]["ocid"] == "ocds-ict-1"


def test_commodity_hardware_record_is_excluded():
    record = {
        "id": "hw-1",
        "title": "Laptop and printer procurement",
        "description": "Commodity hardware for office refresh.",
    }

    result = score_record(record)

    assert result["top_category"]["category_id"] == "commodity_hardware"
    assert result["top_category"]["raw_score"] > 0
    assert result["decision"] == "exclude"
    assert result["best_category"] is None


def test_scoring_order_is_deterministic_for_ties():
    records = [
        {
            "id": "b-record",
            "title": "ICT service review",
            "description": "Managed services advisory.",
        },
        {
            "id": "a-record",
            "title": "ICT service review",
            "description": "Managed services advisory.",
        },
    ]

    ranked = score_records(records)

    assert [item["record_id"] for item in ranked] == ["a-record", "b-record"]


def test_metadata_propagation_keeps_evidence_payload():
    record = {
        "id": "meta-1",
        "title": "Cloud services",
        "description": "Hosted backup platform.",
        "metadata": {
            "source": "cli",
            "evidence": {"ocid": "ocds-meta-1", "lineage": "normalized"},
        },
    }

    result = score_record(record)

    assert result["metadata"]["source"] == "cli"
    assert result["metadata"]["evidence"]["lineage"] == "normalized"


def test_taxonomy_version_is_available():
    taxonomy = load_taxonomy()

    assert taxonomy["version"] == "ict/2026-08-23"
    assert [category["id"] for category in taxonomy["categories"]] == [
        "ict",
        "networking",
        "cybersecurity",
        "software",
        "cloud_services",
        "commodity_hardware",
    ]
