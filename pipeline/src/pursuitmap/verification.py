from __future__ import annotations

from pathlib import Path

import duckdb

from .normalize import TABLE_COLUMNS
from .paths import canonical_root


def verify_outputs(parquet_root=None) -> dict:
    parquet_root = parquet_root or canonical_root()
    connection = duckdb.connect()
    checks: list[dict] = []

    def check(name: str, query: str, *, warning_only: bool = False) -> None:
        value = connection.execute(query).fetchone()[0]
        checks.append({"name": name, "value": value, "status": "warn" if warning_only and value else "pass" if not value else "fail"})

    for table, columns in TABLE_COLUMNS.items():
        path = parquet_root / f"{table}.parquet"
        exists = path.exists()
        checks.append({"name": f"table_exists:{table}", "value": exists, "status": "pass" if exists else "fail"})
        if not exists:
            continue
        actual = {row[0] for row in connection.execute(f"DESCRIBE SELECT * FROM read_parquet('{path}')").fetchall()}
        missing = sorted(set(columns) - actual)
        checks.append({"name": f"schema:{table}", "value": missing, "status": "pass" if not missing else "fail"})

    check("duplicate_release_keys", f"SELECT count(*) - count(DISTINCT ocid || '|' || release_id) FROM read_parquet('{parquet_root / 'releases'}.parquet')")
    check("duplicate_tender_keys", f"SELECT count(*) - count(DISTINCT ocid || '|' || release_id) FROM read_parquet('{parquet_root / 'tenders'}.parquet')")
    check("orphan_award_suppliers", f"""
        SELECT count(*) FROM read_parquet('{parquet_root / 'award_suppliers'}.parquet') s
        LEFT JOIN read_parquet('{parquet_root / 'awards'}.parquet') a
          ON s.ocid = a.ocid AND s.release_id = a.release_id AND s.award_id = a.award_id
        WHERE a.award_id IS NULL
    """)
    check("orphan_contract_awards", f"""
        SELECT count(*) FROM read_parquet('{parquet_root / 'contracts'}.parquet') c
        LEFT JOIN read_parquet('{parquet_root / 'awards'}.parquet') a
          ON c.ocid = a.ocid AND c.release_id = a.release_id AND c.award_id = a.award_id
        WHERE a.award_id IS NULL
    """)
    check("placeholder_supplier_rows", f"SELECT count(*) FILTER (WHERE identifier_status = 'placeholder') FROM read_parquet('{parquet_root / 'award_suppliers'}.parquet')", warning_only=True)
    check("sentinel_contract_periods", f"SELECT count(*) FILTER (WHERE period_start_status = 'sentinel' OR period_end_status = 'sentinel') FROM read_parquet('{parquet_root / 'contracts'}.parquet')", warning_only=True)
    hash_values = connection.execute(f"""
        SELECT count(DISTINCT source_snapshot_sha256)
        FROM (
            SELECT source_snapshot_sha256 FROM read_parquet('{parquet_root / 'releases'}.parquet')
            UNION ALL SELECT source_snapshot_sha256 FROM read_parquet('{parquet_root / 'tenders'}.parquet')
            UNION ALL SELECT source_snapshot_sha256 FROM read_parquet('{parquet_root / 'awards'}.parquet')
        )
    """).fetchone()[0]
    checks.append({"name": "single_source_snapshot_hash", "value": hash_values, "status": "pass" if hash_values == 1 else "fail"})
    connection.close()
    return {
        "status": "fail" if any(check["status"] == "fail" for check in checks) else "warn" if any(check["status"] == "warn" for check in checks) else "pass",
        "checks": checks,
    }
