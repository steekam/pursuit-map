import json
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[3]
DATA_ROOT = PROJECT_ROOT / "data"
RAW_ROOT = DATA_ROOT / "raw" / "south_africa"
WORKING_ROOT = DATA_ROOT / "working" / "south_africa"
PARQUET_ROOT = DATA_ROOT / "parquet" / "south_africa"
MATERIALIZED_ROOT = DATA_ROOT / "materialized" / "south_africa"


def ensure_data_dirs() -> None:
    for path in (RAW_ROOT, WORKING_ROOT, PARQUET_ROOT, MATERIALIZED_ROOT):
        path.mkdir(parents=True, exist_ok=True)


def canonical_root(run_id: str | None = None) -> Path:
    """Resolve an immutable canonical snapshot, defaulting to the latest run."""
    if run_id:
        root = PARQUET_ROOT / run_id
    else:
        manifest_path = WORKING_ROOT / "normalization_manifest.json"
        if not manifest_path.exists():
            raise FileNotFoundError("Run `pursuitmap normalize za` before reading canonical tables.")
        root = Path(json.loads(manifest_path.read_text(encoding="utf-8"))["parquet_root"])
    if not root.is_dir():
        raise FileNotFoundError(f"Canonical output directory not found: {root}")
    return root
