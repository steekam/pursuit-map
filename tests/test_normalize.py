import gzip
import json

from pursuitmap import paths
from pursuitmap.normalize import build_rows, iter_releases, normalize_name, number
from pursuitmap.raw_profile import profile_raw


def test_normalize_name_collapses_case_and_whitespace():
    assert normalize_name("  City   of Cape Town ") == "city of cape town"
    assert normalize_name(" ") is None


def test_number_returns_none_for_invalid_values():
    assert number("12.50") == 12.5
    assert number("-") is None


def test_build_rows_preserves_lifecycle_relationships():
    release = {
        "ocid": "ocds-9t57fa-test",
        "id": "release-1",
        "buyer": {"id": "BUYER-1", "name": "Buyer One"},
        "planning": {"items": [{"id": "plan-1", "description": "Network services"}]},
        "tender": {"id": "tender-1", "title": "Network services"},
        "awards": [{"id": "award-1", "suppliers": [{"id": "SUP-1", "name": "Supplier One"}]}],
        "contracts": [{"id": "contract-1", "awardID": "award-1"}],
    }
    rows = build_rows(release)
    assert rows["procurement_plan_items"][0][5] == "plan-1"
    assert rows["award_suppliers"] == [("ocds-9t57fa-test", "release-1", None, "award-1", "SUP-1", "Supplier One", "present")]
    assert rows["contracts"][0][6] == "award-1"


def test_ocds_dates_and_zero_values_preserve_semantics():
    release = {
        "ocid": "ocds-9t57fa-date",
        "id": "release-1",
        "date": "2024-01-01T00:00:00Z",
        "tender": {
            "id": "t1",
            "tenderPeriod": {"startDate": "2024-02-01T00:00:00Z", "endDate": "2024-03-01T00:00:00Z"},
            "value": {"amount": 0, "currency": "ZAR"},
        },
        "contracts": [{
            "id": "c1",
            "period": {"startDate": "0001-01-01T00:00:00Z", "endDate": "2025-01-01T00:00:00Z"},
        }],
    }
    rows = build_rows(release)
    tender = rows["tenders"][0]
    contract = rows["contracts"][0]
    assert tender[22:28] == ("2024-02-01T00:00:00Z", "2024-02-01T00:00:00+00:00", "valid", "2024-03-01T00:00:00Z", "2024-03-01T00:00:00+00:00", "valid")
    assert tender[28:32] == ("0", 0.0, "ZAR", "zero")
    assert contract[13:19] == ("0001-01-01T00:00:00Z", None, "sentinel", "2025-01-01T00:00:00Z", "2025-01-01T00:00:00+00:00", "valid")


def test_iter_releases_accepts_jsonl_and_release_packages(tmp_path):
    path = tmp_path / "fixture.jsonl.gz"
    with gzip.open(path, "wt", encoding="utf-8") as handle:
        handle.write(json.dumps({"ocid": "one"}) + "\n")
        handle.write(json.dumps({"releases": [{"ocid": "two"}, {"ocid": "three"}]}) + "\n")
    assert [release["ocid"] for release in iter_releases(path)] == ["one", "two", "three"]


def test_canonical_root_resolves_latest_run_from_manifest(tmp_path, monkeypatch):
    data_root = tmp_path / "data"
    parquet_root = data_root / "parquet" / "south_africa"
    working_root = data_root / "working" / "south_africa"
    run_root = parquet_root / "normalize-test"
    run_root.mkdir(parents=True)
    working_root.mkdir(parents=True)
    (working_root / "normalization_manifest.json").write_text(json.dumps({"parquet_root": str(run_root)}), encoding="utf-8")
    monkeypatch.setattr(paths, "DATA_ROOT", data_root)

    assert paths.canonical_root() == run_root
    assert paths.canonical_root(run_id="normalize-test") == run_root


def test_raw_profile_flags_outlier_tender_dates(tmp_path):
    path = tmp_path / "kenya.jsonl"
    path.write_text(json.dumps({"ocid": "ocds-test", "id": "r1", "date": "2024-01-01T00:00:00Z", "buyer": {"id": "b1", "name": "Buyer"}, "tender": {"tenderPeriod": {"startDate": "0001-03-17T21:33:00Z", "endDate": "2025-01-01T00:00:00Z"}}}) + "\n", encoding="utf-8")

    report = profile_raw(path)

    assert report["missingness_null_or_blank_counts"]["source_fields"]["tender_period_start"] == 1
    assert report["missingness_null_or_blank_counts"]["source_fields"]["tender_period_end"] == 0
    assert report["stage_date_ranges"]["tenders"]["min"] is None
