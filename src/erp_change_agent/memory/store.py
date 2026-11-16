"""Append-only project facts with explicit human promotion.

Raw source Markdown remains authoritative. This store records candidate and
human-approved interpretations without overwriting earlier entries.
"""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path


class ProjectMemory:
    def __init__(self, db_path: Path):
        db_path.parent.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(db_path)
        self.conn.row_factory = sqlite3.Row
        self.conn.execute("PRAGMA foreign_keys = ON")
        self.conn.execute("""
            CREATE TABLE IF NOT EXISTS facts (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                tenant_id TEXT NOT NULL,
                claim TEXT NOT NULL,
                citations TEXT NOT NULL,
                status TEXT NOT NULL CHECK(status IN ('candidate','approved','rejected')),
                supersedes_id INTEGER REFERENCES facts(id),
                proposed_at TEXT NOT NULL DEFAULT (datetime('now')),
                reviewer TEXT,
                reviewed_at TEXT,
                review_note TEXT
            )
        """)
        self.conn.commit()

    def close(self) -> None:
        self.conn.close()

    def propose(self, tenant_id: str, claim: str, citations: list[str], supersedes_id: int | None = None) -> int:
        if not claim.strip() or not citations:
            raise ValueError("A memory candidate needs a claim and citations")
        if supersedes_id is not None:
            previous = self.conn.execute("SELECT tenant_id, status FROM facts WHERE id=?", (supersedes_id,)).fetchone()
            if previous is None or previous["tenant_id"] != tenant_id or previous["status"] != "approved":
                raise ValueError("Superseded fact must be an approved fact of the same tenant")
        cursor = self.conn.execute(
            "INSERT INTO facts (tenant_id,claim,citations,status,supersedes_id) VALUES (?,?,?,?,?)",
            (tenant_id, claim.strip(), json.dumps(citations, ensure_ascii=False), "candidate", supersedes_id),
        )
        self.conn.commit()
        return cursor.lastrowid

    def review(self, fact_id: int, tenant_id: str, decision: str, reviewer: str, note: str) -> None:
        if decision not in ("approved", "rejected") or not reviewer.strip():
            raise ValueError("Decision and reviewer are required")
        cursor = self.conn.execute(
            "UPDATE facts SET status=?, reviewer=?, reviewed_at=datetime('now'), review_note=? "
            "WHERE id=? AND tenant_id=? AND status='candidate'",
            (decision, reviewer.strip(), note, fact_id, tenant_id),
        )
        if cursor.rowcount != 1:
            raise ValueError("Candidate not found or already reviewed")
        self.conn.commit()

    def list(self, tenant_id: str) -> list[dict]:
        rows = self.conn.execute("SELECT * FROM facts WHERE tenant_id=? ORDER BY id", (tenant_id,)).fetchall()
        return [{**dict(row), "citations": json.loads(row["citations"])} for row in rows]

    def current_approved(self, tenant_id: str) -> list[dict]:
        """Return approved facts not superseded by another approved fact."""
        approved = [item for item in self.list(tenant_id) if item["status"] == "approved"]
        superseded = {item["supersedes_id"] for item in approved if item["supersedes_id"] is not None}
        return [item for item in approved if item["id"] not in superseded]
