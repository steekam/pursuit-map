import json

import duckdb

from pursuitmap import enrichment_profile, paths
from pursuitmap.source_enrichment import SCHEMA


def test_interim_profile_reuses_same_materialization(monkeypatch, tmp_path):
    monkeypatch.setattr(paths, "DATA_ROOT", tmp_path / "data")
    roots = paths.country_paths("ke")
    run_root = roots.enriched / "run"
    run_root.mkdir(parents=True)
    canonical_root = roots.parquet / "canonical"
    canonical_root.mkdir(parents=True)
    (roots.working).mkdir(parents=True)
    (roots.working / "normalization_manifest.json").write_text(json.dumps({"parquet_root": str(canonical_root)}))
    connection = duckdb.connect()
    connection.execute("COPY (SELECT 'ocid-1' AS ocid UNION ALL SELECT 'ocid-2') TO ? (FORMAT PARQUET)", [str(canonical_root / "releases.parquet")])
    values = {column: "NULL::VARCHAR" for column in SCHEMA}
    values.update({"source_snapshot_sha256": "'sha'", "ocid": "'ocid-1'", "title": "'Title'", "attachments_json": "'[]'"})
    connection.execute(f"COPY (SELECT {','.join(f'{expression} AS {column}' for column, expression in values.items())}) TO ? (FORMAT PARQUET)", [str(run_root / "source_enrichment.parquet")])
    connection.execute("COPY (SELECT 'validated_detail' AS state UNION ALL SELECT 'eligible') TO ? (FORMAT PARQUET)", [str(run_root / "enrichment_eligibility.parquet")])
    connection.close()

    first = enrichment_profile.profile("run", country="ke")
    second = enrichment_profile.profile("run", country="ke")

    assert first == second
    assert first["enriched_rows"] == 1
    assert first["canonical_ocids"] == 2
    assert first["eligibility_states"] == {"eligible": 1, "validated_detail": 1}
    assert first["field_coverage"]["title"]["present"] == 1
    assert (run_root / "source_enrichment_interim_profile.md").exists()
