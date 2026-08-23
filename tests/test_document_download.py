import json

import duckdb

from pursuitmap import document_download as downloader


def test_plan_deduplicates_urls_and_run_preserves_binary(monkeypatch, tmp_path):
    source = tmp_path / "source_enrichment.parquet"
    connection = duckdb.connect()
    connection.execute("CREATE TABLE enrichment (ocid VARCHAR, release_id VARCHAR, attachments_json VARCHAR)")
    attachments = json.dumps([{"id": "doc-1", "url": "https://example.test/file.pdf"}])
    connection.execute("INSERT INTO enrichment VALUES ('ocid-1', 'release-1', ?), ('ocid-2', 'release-2', ?)", [attachments, attachments])
    connection.execute("COPY enrichment TO ? (FORMAT PARQUET)", [str(source)])
    connection.close()
    run_root = tmp_path / "document-run"
    planned = downloader.plan(source, run_root, source_run_id="source-run", source_snapshot_sha256="snapshot")
    assert planned["jobs"] == 1

    payload = b"%PDF-1.7 fixture"
    monkeypatch.setattr(downloader, "_fetch", lambda url, timeout: (200, {"Content-Type": "application/pdf"}, payload))
    report = downloader.run(run_root, sleep=lambda _: None, randomizer=lambda: 0.0)
    assert report["downloaded_files"] == 1
    assert report["duplicate_url_jobs"] == 0
    job = duckdb.connect(str(run_root / "ledger.duckdb")).execute("SELECT status, response_hash, response_path FROM download_jobs").fetchone()
    assert job[0] == "succeeded"
    assert open(job[2], "rb").read() == payload
    assert (run_root / "files" / f"{job[1]}.input.json").exists()


def test_html_response_for_pdf_is_rejected(monkeypatch, tmp_path):
    source = tmp_path / "source_enrichment.parquet"
    connection = duckdb.connect()
    connection.execute("COPY (SELECT 'ocid' AS ocid, 'release' AS release_id, '[{\"url\": \"https://example.test/file.pdf\"}]' AS attachments_json) TO ? (FORMAT PARQUET)", [str(source)])
    connection.close()
    run_root = tmp_path / "document-run"
    downloader.plan(source, run_root, source_run_id="source-run", source_snapshot_sha256="snapshot")
    monkeypatch.setattr(downloader, "_fetch", lambda url, timeout: (200, {"Content-Type": "text/html"}, b"<html>login</html>"))
    report = downloader.run(run_root, max_attempts=1, sleep=lambda _: None, randomizer=lambda: 0.0)
    assert report["job_counts"]["permanent_failed"] == 1
