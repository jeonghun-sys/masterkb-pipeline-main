from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import Any


class PipelineStateStore:
    def __init__(self, db_path: str) -> None:
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_db()

    def _connect(self) -> sqlite3.Connection:
        return sqlite3.connect(self.db_path)

    def _init_db(self) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS source_state (
                    source_id TEXT PRIMARY KEY,
                    source TEXT NOT NULL,
                    source_hash TEXT NOT NULL,
                    payload_json TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                )
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS run_log (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    mode TEXT NOT NULL,
                    write_mode TEXT NOT NULL,
                    summary_json TEXT NOT NULL,
                    created_at TEXT NOT NULL
                )
                """
            )

    def get_source_hash(self, source_id: str) -> str | None:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT source_hash FROM source_state WHERE source_id = ?",
                (source_id,),
            ).fetchone()
        return row[0] if row else None

    def get_source_payload(self, source_id: str) -> dict[str, Any] | None:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT payload_json FROM source_state WHERE source_id = ?",
                (source_id,),
            ).fetchone()
        if not row:
            return None
        try:
            payload = json.loads(row[0])
        except json.JSONDecodeError:
            return None
        return payload if isinstance(payload, dict) else None

    def upsert_source_state(
        self,
        *,
        source_id: str,
        source: str,
        source_hash: str,
        payload: dict[str, Any],
        updated_at: str,
    ) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO source_state (source_id, source, source_hash, payload_json, updated_at)
                VALUES (?, ?, ?, ?, ?)
                ON CONFLICT(source_id) DO UPDATE SET
                    source_hash = excluded.source_hash,
                    payload_json = excluded.payload_json,
                    updated_at = excluded.updated_at
                """,
                (
                    source_id,
                    source,
                    source_hash,
                    json.dumps(payload, ensure_ascii=False),
                    updated_at,
                ),
            )

    def insert_run_log(
        self,
        *,
        mode: str,
        write_mode: str,
        summary: dict[str, Any],
        created_at: str,
    ) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO run_log (mode, write_mode, summary_json, created_at)
                VALUES (?, ?, ?, ?)
                """,
                (mode, write_mode, json.dumps(summary, ensure_ascii=False), created_at),
            )
