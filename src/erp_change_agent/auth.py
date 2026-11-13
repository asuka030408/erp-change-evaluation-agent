"""Local API identities. Only hashes of high-entropy bearer tokens are stored."""

import hashlib
import secrets
import sqlite3
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from .ingest import TENANT_PATTERN


ROLES = {"analyst", "reviewer", "admin"}


@dataclass(frozen=True)
class Identity:
    tenant_id: str
    role: str
    name: str


class TokenStore:
    def __init__(self, path: Path):
        path.parent.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(path)
        self.conn.row_factory = sqlite3.Row
        self.conn.execute("""
            CREATE TABLE IF NOT EXISTS api_tokens (
                token_hash TEXT PRIMARY KEY,
                tenant_id TEXT NOT NULL,
                role TEXT NOT NULL,
                name TEXT NOT NULL,
                created_at TEXT NOT NULL,
                revoked_at TEXT
            )
        """)
        self.conn.commit()

    def close(self) -> None:
        self.conn.close()

    @staticmethod
    def _digest(token: str) -> str:
        return hashlib.sha256(token.encode("utf-8")).hexdigest()

    def issue(self, tenant_id: str, role: str, name: str) -> str:
        if not TENANT_PATTERN.fullmatch(tenant_id):
            raise ValueError("Invalid tenant ID")
        if role not in ROLES or not name.strip():
            raise ValueError("Valid role and name are required")
        token = "erp_" + secrets.token_urlsafe(32)
        self.conn.execute(
            "INSERT INTO api_tokens (token_hash, tenant_id, role, name, created_at) VALUES (?,?,?,?,?)",
            (self._digest(token), tenant_id, role, name.strip(), datetime.now(timezone.utc).isoformat()),
        )
        self.conn.commit()
        return token

    def authenticate(self, token: str) -> Identity | None:
        if not token or not token.startswith("erp_"):
            return None
        row = self.conn.execute(
            "SELECT tenant_id, role, name FROM api_tokens WHERE token_hash=? AND revoked_at IS NULL",
            (self._digest(token),),
        ).fetchone()
        return Identity(**dict(row)) if row else None

    def revoke(self, token: str) -> bool:
        cursor = self.conn.execute(
            "UPDATE api_tokens SET revoked_at=? WHERE token_hash=? AND revoked_at IS NULL",
            (datetime.now(timezone.utc).isoformat(), self._digest(token)),
        )
        self.conn.commit()
        return cursor.rowcount == 1
