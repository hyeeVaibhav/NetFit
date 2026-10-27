"""database.py - SQLite storage for prediction history.

Each prediction run is one row in `runs` (metadata + JSON summary). The per-flow result table is written to a CSV file
(data/results/run_<id>.csv) and referenced from the row, which keeps the database small and downloads instant.
"""
from __future__ import annotations

import json
import sqlite3
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path

SCHEMA = """
CREATE TABLE IF NOT EXISTS runs (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    created_at    TEXT    NOT NULL,
    filename      TEXT    NOT NULL,
    model_key     TEXT    NOT NULL,
    model_name    TEXT    NOT NULL,
    threshold     REAL    NOT NULL,
    n_rows        INTEGER NOT NULL,
    n_attack      INTEGER NOT NULL,
    n_normal      INTEGER NOT NULL,
    attack_rate   REAL    NOT NULL,
    has_labels    INTEGER NOT NULL DEFAULT 0,
    accuracy      REAL,
    precision_    REAL,
    recall        REAL,
    f1            REAL,
    duration_ms   INTEGER,
    result_file   TEXT,
    summary_json  TEXT    NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_runs_created ON runs (created_at DESC);
"""

LIST_COLUMNS = ("id, created_at, filename, model_key, model_name, threshold, n_rows, n_attack, n_normal, "
                "attack_rate, has_labels, accuracy, precision_ AS precision, recall, f1, duration_ms")


class Database:
    def __init__(self, path: Path, results_dir: Path):
        self.path = Path(path)
        self.results_dir = Path(results_dir)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.results_dir.mkdir(parents=True, exist_ok=True)
        with self.connect() as con:
            con.executescript(SCHEMA)

    @contextmanager
    def connect(self):
        con = sqlite3.connect(self.path, timeout=15)
        con.row_factory = sqlite3.Row
        try:
            yield con
            con.commit()
        finally:
            con.close()

    def ok(self) -> bool:
        try:
            with self.connect() as con:
                con.execute("SELECT 1 FROM runs LIMIT 1")
            return True
        except sqlite3.Error:
            return False

    # ---------------- write ----------------
    def add_run(self, *, filename, model_key, model_name, threshold, summary, duration_ms, result_df) -> int:
        labels = summary.get("labels") or {}
        with self.connect() as con:
            cur = con.execute(
                """INSERT INTO runs (created_at, filename, model_key, model_name, threshold, n_rows, n_attack, n_normal,
                                     attack_rate, has_labels, accuracy, precision_, recall, f1, duration_ms,
                                     result_file, summary_json)
                   VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (datetime.now().isoformat(timespec="seconds"), filename[:200], model_key, model_name, float(threshold),
                 summary["n_rows"], summary["n_attack"], summary["n_normal"], summary["attack_rate"],
                 1 if summary.get("has_labels") else 0,
                 labels.get("accuracy"), labels.get("precision"), labels.get("recall"), labels.get("f1"),
                 int(duration_ms), "", json.dumps(summary)))
            run_id = cur.lastrowid
            rel = f"run_{run_id}.csv"
            result_df.to_csv(self.results_dir / rel, index=False)
            con.execute("UPDATE runs SET result_file=? WHERE id=?", (rel, run_id))
        return run_id

    def delete_run(self, run_id: int) -> bool:
        with self.connect() as con:
            row = con.execute("SELECT result_file FROM runs WHERE id=?", (run_id,)).fetchone()
            if not row:
                return False
            con.execute("DELETE FROM runs WHERE id=?", (run_id,))
        self._remove_file(row["result_file"])
        return True

    def clear(self) -> int:
        with self.connect() as con:
            files = [r["result_file"] for r in con.execute("SELECT result_file FROM runs")]
            n = con.execute("DELETE FROM runs").rowcount
        for f in files:
            self._remove_file(f)
        return n

    def _remove_file(self, rel):
        if rel:
            try:
                (self.results_dir / rel).unlink(missing_ok=True)
            except OSError:
                pass

    # ---------------- read ----------------
    def list_runs(self, limit: int = 200):
        with self.connect() as con:
            rows = con.execute(f"SELECT {LIST_COLUMNS} FROM runs ORDER BY id DESC LIMIT ?", (limit,)).fetchall()
        return [dict(r) for r in rows]

    def get_run(self, run_id: int):
        with self.connect() as con:
            row = con.execute("SELECT * FROM runs WHERE id=?", (run_id,)).fetchone()
        if not row:
            return None
        d = dict(row)
        d["precision"] = d.pop("precision_")
        d["summary"] = json.loads(d.pop("summary_json"))
        return d

    def result_path(self, run_id: int):
        with self.connect() as con:
            row = con.execute("SELECT result_file FROM runs WHERE id=?", (run_id,)).fetchone()
        if not row or not row["result_file"]:
            return None
        p = self.results_dir / row["result_file"]
        return p if p.exists() else None

    def totals(self):
        with self.connect() as con:
            r = con.execute("SELECT COUNT(*) n, COALESCE(SUM(n_rows),0) flows, COALESCE(SUM(n_attack),0) attacks FROM runs").fetchone()
        return {"runs": r["n"], "flows": r["flows"], "attacks": r["attacks"]}
