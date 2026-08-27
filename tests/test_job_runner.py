import json

import duckdb

from pursuitmap.job_runner import DurableJobRunner, JobOutcome, RunnerPolicy


def test_runner_retries_handler_and_writes_progress(tmp_path):
    connection = duckdb.connect()
    now = [100.0]
    runner = DurableJobRunner(connection, "run-1", policy=RunnerPolicy(max_attempts=2, jitter_seconds=0), clock=lambda: now[0], sleeper=lambda delay: now.__setitem__(0, now[0] + delay), randomizer=lambda: 0)
    runner.add("job-1", {"value": 3})
    calls = []

    def handler(payload):
        calls.append(payload)
        return JobOutcome(status="failed", retryable=True, error_class="temporary") if len(calls) == 1 else JobOutcome(response_hash="abc")

    progress = tmp_path / "progress.json"
    result = runner.run(handler, progress_path=progress)

    assert result["job_counts"] == {"succeeded": 1}
    assert len(calls) == 2
    assert json.loads(progress.read_text())["stage"] == "complete"
    assert connection.execute("SELECT count(*) FROM job_events").fetchone()[0] == 2


def test_runner_recovers_expired_lease():
    connection = duckdb.connect()
    runner = DurableJobRunner(connection, "run-1", clock=lambda: 100.0)
    runner.add("job-1", {})
    connection.execute("UPDATE jobs SET status='running', lease_until=50 WHERE job_id='job-1'")

    assert runner.recover_stale() == 1
    assert connection.execute("SELECT status, error_class FROM jobs WHERE job_id='job-1'").fetchone() == ("retryable_failed", "LeaseRecovery")
