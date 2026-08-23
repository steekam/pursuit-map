from pursuitmap.enrichment import QUALITY_FLAG_COLUMNS, RULE_VERSION


def test_quality_flag_schema_is_provenance_complete():
    assert QUALITY_FLAG_COLUMNS == [
        "source_snapshot_sha256", "country", "ocid", "release_id", "table_name",
        "source_record_key", "source_field_path", "flag_code", "flag_status",
        "observed_value_raw", "rule_version", "enrichment_run_id", "generated_at",
    ]
    assert RULE_VERSION == "kenya-quality-1"
