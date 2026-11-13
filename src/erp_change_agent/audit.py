"""Immutable event log for assessments; never records API keys or raw documents."""

import hashlib
import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path


class AuditLog:
    def __init__(self, path: Path):
        path.parent.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(path)
        self.conn.row_factory = sqlite3.Row
        self.conn.execute("""
            CREATE TABLE IF NOT EXISTS events (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                run_id TEXT NOT NULL,
                tenant_id TEXT NOT NULL,
                event_type TEXT NOT NULL,
                occurred_at TEXT NOT NULL,
                details_json TEXT NOT NULL
            )
        """)
        self.conn.execute("CREATE INDEX IF NOT EXISTS idx_audit_run ON events(run_id, id)")
        self.conn.commit()

    def close(self) -> None:
        self.conn.close()

    def append(self, run_id: str, tenant_id: str, event_type: str, details: dict) -> None:
        if not run_id or not tenant_id:
            raise ValueError("Audit event requires run and tenant IDs")
        self.conn.execute(
            "INSERT INTO events (run_id,tenant_id,event_type,occurred_at,details_json) VALUES (?,?,?,?,?)",
            (run_id, tenant_id, event_type, datetime.now(timezone.utc).isoformat(), json.dumps(details, ensure_ascii=False)),
        )
        self.conn.commit()

    def events(self, run_id: str) -> list[dict]:
        rows = self.conn.execute("SELECT * FROM events WHERE run_id=? ORDER BY id", (run_id,)).fetchall()
        return [{**dict(row), "details": json.loads(row["details_json"])} for row in rows]


def report_hash(report: str) -> str:
    return hashlib.sha256(report.encode("utf-8")).hexdigest()
