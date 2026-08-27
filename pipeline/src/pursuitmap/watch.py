from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any


def find_latest_run(search_root: Path) -> Path:
    candidates = [path.parent for path in search_root.rglob("progress.json")]
    if not candidates:
        raise FileNotFoundError(f"no progress.json found under {search_root}")
    return max(candidates, key=lambda path: (path / "progress.json").stat().st_mtime)


def read_progress(run_root: Path) -> dict[str, Any]:
    progress_path = run_root / "progress.json"
    with progress_path.open(encoding="utf-8") as handle:
        return json.load(handle)


def _number(value: Any, digits: int = 0) -> str:
    if value is None:
        return "-"
    if isinstance(value, float):
        return f"{value:.{digits}f}"
    return f"{value:,}" if isinstance(value, int) else str(value)


def format_status(run_root: Path, progress: dict[str, Any]) -> str:
    counts = progress.get("job_counts", {})
    coverage = progress.get("coverage")
    coverage_text = "-" if coverage is None else f"{coverage * 100:.2f}%"
    report = any(run_root.glob("*_report.json"))
    return "\n".join(
        [
            f"PursuitMap watcher | {run_root.name}",
            f"Updated:             {progress.get('updated_at', '-')}",
            f"Stage:               {progress.get('stage', progress.get('phase', '-'))}",
            f"Completed:           {_number(counts.get('succeeded', progress.get('completed')))}",
            f"Pending:             {_number(counts.get('pending', progress.get('pending')))}",
            f"Retryable failures:  {_number(counts.get('retryable_failed', progress.get('retryable')))}",
            f"Permanent failures:  {_number(counts.get('permanent_failed', progress.get('permanent_failed')))}",
            f"Canonical matches:   {_number(progress.get('canonical_matches'))} / {_number(progress.get('canonical_total'))}",
            f"Coverage:            {coverage_text}",
            f"Requests:            {_number(progress.get('request_count', progress.get('requests')))}",
            f"Effective RPM:       {_number(progress.get('effective_rpm'), 2)}",
            f"Cache hits:          {_number(progress.get('cache_hits'))}",
            f"Selected concurrency: {_number(progress.get('selected_concurrency'))}",
            f"Final report:        {'yes' if report else 'no'}",
        ]
    )


def watch(run_root: Path | None = None, search_root: Path = Path("data/enriched"), interval: int = 10, once: bool = False) -> None:
    selected_root = run_root or find_latest_run(search_root)
    while True:
        progress = read_progress(selected_root)
        print("\033[2J\033[H", end="")
        print(format_status(selected_root, progress))
        if once or any(selected_root.glob("*_report.json")):
            return
        time.sleep(interval)
