import json

from pursuitmap.watch import find_latest_run, format_status, read_progress


def test_watch_reads_and_formats_named_progress_fields(tmp_path):
    run_root = tmp_path / "run"
    run_root.mkdir()
    (run_root / "progress.json").write_text(
        json.dumps(
            {
                "updated_at": "2026-08-27T12:00:00Z",
                "stage": "exact_ocid",
                "job_counts": {"succeeded": 4, "pending": 6, "permanent_failed": 1},
                "canonical_matches": 4,
                "canonical_total": 10,
                "coverage": 0.4,
                "request_count": 12,
                "effective_rpm": 3.5,
                "cache_hits": 2,
                "selected_concurrency": 4,
            }
        ),
        encoding="utf-8",
    )

    progress = read_progress(run_root)
    output = format_status(run_root, progress)

    assert "Stage:               exact_ocid" in output
    assert "Completed:           4" in output
    assert "Coverage:            40.00%" in output
    assert "Effective RPM:       3.50" in output
    assert "Final report:        no" in output


def test_watch_selects_newest_sidecar(tmp_path):
    older = tmp_path / "older"
    newer = tmp_path / "newer"
    older.mkdir()
    newer.mkdir()
    for root in (older, newer):
        (root / "progress.json").write_text("{}", encoding="utf-8")
    (newer / "progress.json").touch()

    assert find_latest_run(tmp_path) == newer
