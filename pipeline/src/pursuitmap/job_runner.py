"""Reusable durable execution primitives for local background jobs."""

from __future__ import annotations

import json
import os
import random
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

import duckdb


@dataclass(frozen=True)
class RunnerPolicy:
    max_attempts: int = 6
    lease_seconds: float = 300.0
    max_backoff_seconds: float = 600.0
    jitter_seconds: float = 1.0


@dataclass(frozen=True)
class JobOutcome:
    status: str = "succeeded"
    retryable: bool = False
    error_class: str | None = None
    error_message: str | None = None
    response_hash: str | None = None
    retry_after_seconds: float | None = None


Handler = Callable[[dict[str, Any]], JobOutcome]


def _schema(connection: duckdb.DuckDBPyConnection) -> None:
    connection.execute("CREATE SEQUENCE IF NOT EXISTS job_event_seq START 1")
    connection.execute("CREATE TABLE IF NOT EXISTS jobs (job_id VARCHAR PRIMARY KEY, run_id VARCHAR, payload_json VARCHAR, status VARCHAR, attempts INTEGER, next_attempt_at DOUBLE, lease_owner VARCHAR, lease_until DOUBLE, error_class VARCHAR, error_message VARCHAR, response_hash VARCHAR, created_at DOUBLE, updated_at DOUBLE)")
    connection.execute("CREATE TABLE IF NOT EXISTS job_events (event_id BIGINT, job_id VARCHAR, attempt INTEGER, state VARCHAR, retryable BOOLEAN, error_class VARCHAR, error_message VARCHAR, response_hash VARCHAR, created_at DOUBLE)")


class DurableJobRunner:
    def __init__(self, connection: duckdb.DuckDBPyConnection, run_id: str, *, policy: RunnerPolicy | None = None, clock: Callable[[], float] = time.monotonic, sleeper: Callable[[float], None] = time.sleep, randomizer: Callable[[], float] = random.random, owner: str | None = None) -> None:
        _schema(connection)
        self.connection = connection
        self.run_id = run_id
        self.policy = policy or RunnerPolicy()
        self.clock = clock
        self.sleeper = sleeper
        self.randomizer = randomizer
        self.owner = owner or f"{os.getpid()}"

    def add(self, job_id: str, payload: dict[str, Any]) -> None:
        now = self.clock()
        self.connection.execute("INSERT INTO jobs VALUES (?, ?, ?, 'pending', 0, 0, NULL, NULL, NULL, NULL, NULL, ?, ?) ON CONFLICT (job_id) DO NOTHING", [job_id, self.run_id, json.dumps(payload, sort_keys=True), now, now])

    def recover_stale(self) -> int:
        now = self.clock()
        result = self.connection.execute("UPDATE jobs SET status='retryable_failed', lease_owner=NULL, lease_until=NULL, error_class='LeaseRecovery', error_message='lease expired', next_attempt_at=?, updated_at=? WHERE run_id=? AND status='running' AND lease_until < ?", [now, now, self.run_id, now])
        return result.fetchone()[0] if result.description else 0

    def _progress(self, path: Path | None, stage: str) -> None:
        if path is None:
            return
        counts = {row[0]: row[1] for row in self.connection.execute("SELECT status, count(*) FROM jobs WHERE run_id=? GROUP BY 1", [self.run_id]).fetchall()}
        value = {"run_id": self.run_id, "stage": stage, "updated_at": self.clock(), "job_counts": counts}
        temporary = path.with_suffix(path.suffix + ".tmp")
        temporary.write_text(json.dumps(value, indent=2) + "\n", encoding="utf-8")
        temporary.replace(path)

    def _claim(self) -> tuple[str, dict[str, Any], int] | None:
        now = self.clock()
        row = self.connection.execute("SELECT job_id, payload_json, attempts FROM jobs WHERE run_id=? AND status IN ('pending','retryable_failed') AND next_attempt_at <= ? ORDER BY job_id LIMIT 1", [self.run_id, now]).fetchone()
        if row is None:
            return None
        job_id, payload_json, attempts = row
        attempt = attempts + 1
        self.connection.execute("UPDATE jobs SET status='running', attempts=?, lease_owner=?, lease_until=?, updated_at=? WHERE job_id=? AND status IN ('pending','retryable_failed')", [attempt, self.owner, now + self.policy.lease_seconds, now, job_id])
        return job_id, json.loads(payload_json), attempt

    def _record(self, job_id: str, attempt: int, outcome: JobOutcome) -> None:
        now = self.clock()
        if outcome.status == "succeeded":
            state = "succeeded"
            next_at = now
        elif outcome.retryable and attempt < self.policy.max_attempts:
            state = "retryable_failed"
            backoff = min(self.policy.max_backoff_seconds, 2 ** attempt) + self.randomizer() * self.policy.jitter_seconds
            delay = max(backoff, outcome.retry_after_seconds or 0.0)
            next_at = now + delay
        else:
            state = "permanent_failed"
            next_at = now
        self.connection.execute("UPDATE jobs SET status=?, next_attempt_at=?, lease_owner=NULL, lease_until=NULL, error_class=?, error_message=?, response_hash=?, updated_at=? WHERE job_id=?", [state, next_at, outcome.error_class, outcome.error_message, outcome.response_hash, now, job_id])
        self.connection.execute("INSERT INTO job_events VALUES (nextval('job_event_seq'), ?, ?, ?, ?, ?, ?, ?, ?)", [job_id, attempt, state, outcome.retryable, outcome.error_class, outcome.error_message, outcome.response_hash, now])

    def run(self, handler: Handler, *, progress_path: Path | None = None, stop: Callable[[], bool] | None = None) -> dict[str, Any]:
        self.recover_stale()
        self._progress(progress_path, "running")
        while not stop or not stop():
            claim = self._claim()
            if claim is None:
                waiting = self.connection.execute("SELECT min(next_attempt_at) FROM jobs WHERE run_id=? AND status='retryable_failed'", [self.run_id]).fetchone()[0]
                if waiting is None:
                    break
                self.sleeper(max(0.0, waiting - self.clock()))
                continue
            job_id, payload, attempt = claim
            try:
                outcome = handler(payload)
            except Exception as error:
                outcome = JobOutcome(status="failed", retryable=attempt < self.policy.max_attempts, error_class=type(error).__name__, error_message=str(error))
            self._record(job_id, attempt, outcome)
            self._progress(progress_path, "running")
        self._progress(progress_path, "complete")
        counts = {row[0]: row[1] for row in self.connection.execute("SELECT status, count(*) FROM jobs WHERE run_id=? GROUP BY 1", [self.run_id]).fetchall()}
        return {"run_id": self.run_id, "job_counts": counts, "events": self.connection.execute("SELECT count(*) FROM job_events WHERE job_id IN (SELECT job_id FROM jobs WHERE run_id=?)", [self.run_id]).fetchone()[0]}
