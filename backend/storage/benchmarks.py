"""Saved benchmark suites and their run history.

A suite is a definition, not a script: which models to test, and what to
ask them. Keeping it as data rather than a Python file is what makes it
editable from the dashboard, and what lets the same suite be re-run
against a different model months later without touching code.

Run history is stored alongside deliberately. A benchmark you cannot
compare against last week's numbers is a demo, not a measurement.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from typing import Any
from uuid import uuid4

from .database import Database

KINDS = ("perf", "eval")


def now() -> str:
    return datetime.now(UTC).isoformat()


class BenchmarkStore:
    def __init__(self, database: Database) -> None:
        self.database = database

    # --- suites ------------------------------------------------------

    def list(self) -> list[dict[str, Any]]:
        with self.database.connect() as connection:
            rows = connection.execute(
                "SELECT id, name, kind, description, definition_json, created_at, updated_at "
                "FROM benchmarks ORDER BY name"
            ).fetchall()
            latest = {
                row["benchmark_id"]: dict(row)
                for row in connection.execute(
                    "SELECT run.benchmark_id, run.started_at, run.status, run.summary "
                    "FROM benchmark_runs AS run "
                    "WHERE run.id = ("
                    "  SELECT candidate.id FROM benchmark_runs AS candidate "
                    "  WHERE candidate.benchmark_id = run.benchmark_id "
                    "  ORDER BY candidate.started_at DESC, candidate.id DESC LIMIT 1"
                    ")"
                ).fetchall()
            }
        suites = []
        for row in rows:
            suite = self._hydrate(row)
            suite["last_run"] = latest.get(suite["id"])
            suites.append(suite)
        return suites

    def get(self, benchmark_id: str) -> dict[str, Any] | None:
        with self.database.connect() as connection:
            row = connection.execute("SELECT * FROM benchmarks WHERE id = ?", (benchmark_id,)).fetchone()
            if not row:
                return None
            suite = self._hydrate(row)
            suite["runs"] = [self._hydrate_run(item) for item in connection.execute(
                "SELECT * FROM benchmark_runs WHERE benchmark_id = ? ORDER BY started_at DESC LIMIT 10",
                (benchmark_id,),
            ).fetchall()]
        return suite

    def create(self, name: str, kind: str, definition: dict, description: str = "") -> dict[str, Any]:
        if kind not in KINDS:
            raise ValueError(f"Unknown benchmark kind: {kind}")
        record = {
            "id": str(uuid4()),
            "name": name.strip() or "Untitled benchmark",
            "kind": kind,
            "description": description.strip(),
            "definition_json": json.dumps(definition),
            "created_at": now(),
            "updated_at": now(),
        }
        with self.database.connect() as connection:
            connection.execute(
                "INSERT INTO benchmarks (id, name, kind, description, definition_json, created_at, updated_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?)",
                tuple(record.values()),
            )
        return self._hydrate(record)

    def update(
        self,
        benchmark_id: str,
        name: str | None = None,
        definition: dict | None = None,
        description: str | None = None,
    ) -> dict[str, Any] | None:
        current = self.get(benchmark_id)
        if not current:
            return None
        with self.database.connect() as connection:
            connection.execute(
                "UPDATE benchmarks SET name = ?, description = ?, definition_json = ?, updated_at = ? WHERE id = ?",
                (
                    (name or current["name"]).strip() or current["name"],
                    current["description"] if description is None else description.strip(),
                    json.dumps(current["definition"] if definition is None else definition),
                    now(),
                    benchmark_id,
                ),
            )
        return self.get(benchmark_id)

    def delete(self, benchmark_id: str) -> bool:
        with self.database.connect() as connection:
            return connection.execute("DELETE FROM benchmarks WHERE id = ?", (benchmark_id,)).rowcount > 0

    def exists_named(self, name: str) -> bool:
        with self.database.connect() as connection:
            return connection.execute("SELECT 1 FROM benchmarks WHERE name = ?", (name,)).fetchone() is not None

    # --- runs --------------------------------------------------------

    def start_run(self, benchmark_id: str) -> str:
        run_id = str(uuid4())
        with self.database.connect() as connection:
            connection.execute(
                "INSERT INTO benchmark_runs (id, benchmark_id, started_at, status) VALUES (?, ?, ?, ?)",
                (run_id, benchmark_id, now(), "running"),
            )
        return run_id

    def finish_run(self, run_id: str, status: str, summary: str, results: Any) -> None:
        with self.database.connect() as connection:
            connection.execute(
                "UPDATE benchmark_runs SET finished_at = ?, status = ?, summary = ?, results_json = ? WHERE id = ?",
                (now(), status, summary[:400], json.dumps(results), run_id),
            )

    # --- shaping -----------------------------------------------------

    def _hydrate(self, row: Any) -> dict[str, Any]:
        item = dict(row)
        item["definition"] = json.loads(item.pop("definition_json") or "{}")
        return item

    def _hydrate_run(self, row: Any) -> dict[str, Any]:
        item = dict(row)
        item.pop("benchmark_id", None)
        item["results"] = json.loads(item.pop("results_json") or "null")
        return item
