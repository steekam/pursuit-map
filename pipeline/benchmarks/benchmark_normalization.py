from __future__ import annotations

import argparse
import json
import tempfile
import time
from pathlib import Path

import duckdb

from pursuitmap.normalize import build_rows, iter_releases


def benchmark_python(source: Path) -> dict:
    started = time.perf_counter()
    releases = 0
    rows = 0
    for release in iter_releases(source):
        releases += 1
        rows += sum(len(table_rows) for table_rows in build_rows(release).values())
    return {"releases": releases, "rows": rows, "seconds": round(time.perf_counter() - started, 3)}


def benchmark_duckdb(source: Path) -> dict:
    with tempfile.TemporaryDirectory(prefix="pursuitmap-benchmark-") as directory:
        output = Path(directory) / "releases.parquet"
        connection = duckdb.connect()
        started = time.perf_counter()
        connection.execute(
            f"""
            COPY (
                SELECT
                    json_extract_string(json, '$.ocid') AS ocid,
                    json_extract_string(json, '$.id') AS release_id,
                    try_cast(json_extract_string(json, '$.date') AS TIMESTAMP) AS release_date,
                    json_extract_string(json, '$.buyer.id') AS buyer_id,
                    json_extract_string(json, '$.buyer.name') AS buyer_name,
                    json AS raw_json
                FROM read_json_objects('{source}')
            ) TO '{output}' (FORMAT PARQUET, COMPRESSION ZSTD)
            """
        )
        releases = connection.execute(f"SELECT count(*) FROM read_parquet('{output}')").fetchone()[0]
        output_bytes = output.stat().st_size
        seconds = time.perf_counter() - started
        connection.close()
    return {"releases": releases, "output_bytes": output_bytes, "seconds": round(seconds, 3)}


def main() -> None:
    parser = argparse.ArgumentParser(description="Benchmark Python and DuckDB normalization paths.")
    parser.add_argument("--source", type=Path, required=True)
    args = parser.parse_args()
    result = {
        "source": str(args.source),
        "python_rows": benchmark_python(args.source),
        "duckdb_vectorized": benchmark_duckdb(args.source),
        "decision": "duckdb_vectorized_staging_and_sql_expansion",
    }
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
