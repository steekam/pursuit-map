from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[2]
DATA_ROOT = PROJECT_ROOT / "data"
RAW_ROOT = DATA_ROOT / "raw" / "south_africa"
WORKING_ROOT = DATA_ROOT / "working" / "south_africa"
PARQUET_ROOT = DATA_ROOT / "parquet" / "south_africa"
MATERIALIZED_ROOT = DATA_ROOT / "materialized" / "south_africa"


def ensure_data_dirs() -> None:
    for path in (RAW_ROOT, WORKING_ROOT, PARQUET_ROOT, MATERIALIZED_ROOT):
        path.mkdir(parents=True, exist_ok=True)
