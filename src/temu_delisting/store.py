"""SQLite 数据层：批次、违规商品建议清单、SKC 处理记录（幂等去重用）。"""
from __future__ import annotations

import sqlite3
import uuid
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterator, Optional

SCHEMA = """
CREATE TABLE IF NOT EXISTS batches (
    batch_id TEXT PRIMARY KEY,
    start_time TEXT NOT NULL,
    end_time TEXT NOT NULL,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS suggestions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    batch_id TEXT NOT NULL,
    spu_id TEXT NOT NULL,
    violation_type TEXT NOT NULL,
    violation_detail TEXT,
    classification TEXT NOT NULL,      -- delist_suggested | needs_human_review
    review_status TEXT NOT NULL DEFAULT 'pending_review',  -- pending_review | confirmed | rejected
    created_at TEXT NOT NULL,
    FOREIGN KEY (batch_id) REFERENCES batches(batch_id)
);

CREATE TABLE IF NOT EXISTS skc_records (
    skc_id TEXT PRIMARY KEY,
    spu_id TEXT NOT NULL,
    batch_id TEXT NOT NULL,
    status TEXT NOT NULL,              -- success | failed | timeout_needs_human
    delist_reason TEXT,
    detail TEXT,
    updated_at TEXT NOT NULL
);
"""


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


@dataclass
class Suggestion:
    id: int
    batch_id: str
    spu_id: str
    violation_type: str
    violation_detail: str
    classification: str
    review_status: str


class Store:
    def __init__(self, db_path: Path):
        db_path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(db_path)
        self._conn.row_factory = sqlite3.Row
        self._conn.executescript(SCHEMA)
        self._conn.commit()

    def close(self) -> None:
        self._conn.close()

    def __enter__(self) -> "Store":
        return self

    def __exit__(self, *exc) -> None:
        self.close()

    # -- batches --------------------------------------------------------

    def create_batch(self, start_time: str, end_time: str) -> str:
        batch_id = uuid.uuid4().hex[:12]
        self._conn.execute(
            "INSERT INTO batches (batch_id, start_time, end_time, created_at) VALUES (?, ?, ?, ?)",
            (batch_id, start_time, end_time, _now()),
        )
        self._conn.commit()
        return batch_id

    # -- suggestions ------------------------------------------------------

    def add_suggestion(
        self,
        batch_id: str,
        spu_id: str,
        violation_type: str,
        violation_detail: str,
        classification: str,
    ) -> int:
        cur = self._conn.execute(
            """INSERT INTO suggestions
               (batch_id, spu_id, violation_type, violation_detail, classification, review_status, created_at)
               VALUES (?, ?, ?, ?, ?, 'pending_review', ?)""",
            (batch_id, spu_id, violation_type, violation_detail, classification, _now()),
        )
        self._conn.commit()
        return cur.lastrowid

    def set_review_status(self, suggestion_id: int, status: str) -> None:
        assert status in {"pending_review", "confirmed", "rejected"}
        self._conn.execute(
            "UPDATE suggestions SET review_status = ? WHERE id = ?", (status, suggestion_id)
        )
        self._conn.commit()

    def list_suggestions(self, batch_id: str, review_status: Optional[str] = None) -> list[Suggestion]:
        query = "SELECT * FROM suggestions WHERE batch_id = ?"
        params: list = [batch_id]
        if review_status:
            query += " AND review_status = ?"
            params.append(review_status)
        rows = self._conn.execute(query, params).fetchall()
        return [
            Suggestion(
                id=r["id"],
                batch_id=r["batch_id"],
                spu_id=r["spu_id"],
                violation_type=r["violation_type"],
                violation_detail=r["violation_detail"] or "",
                classification=r["classification"],
                review_status=r["review_status"],
            )
            for r in rows
        ]

    # -- skc processing records (idempotency) ------------------------------

    def get_skc_status(self, skc_id: str) -> Optional[str]:
        row = self._conn.execute(
            "SELECT status FROM skc_records WHERE skc_id = ?", (skc_id,)
        ).fetchone()
        return row["status"] if row else None

    def is_already_delisted(self, skc_id: str) -> bool:
        return self.get_skc_status(skc_id) == "success"

    def record_skc_result(
        self,
        skc_id: str,
        spu_id: str,
        batch_id: str,
        status: str,
        delist_reason: str = "",
        detail: str = "",
    ) -> None:
        assert status in {"success", "failed", "timeout_needs_human"}
        self._conn.execute(
            """INSERT INTO skc_records (skc_id, spu_id, batch_id, status, delist_reason, detail, updated_at)
               VALUES (?, ?, ?, ?, ?, ?, ?)
               ON CONFLICT(skc_id) DO UPDATE SET
                   spu_id=excluded.spu_id, batch_id=excluded.batch_id, status=excluded.status,
                   delist_reason=excluded.delist_reason, detail=excluded.detail, updated_at=excluded.updated_at""",
            (skc_id, spu_id, batch_id, status, delist_reason, detail, _now()),
        )
        self._conn.commit()

    def list_failures(self, batch_id: str) -> list[sqlite3.Row]:
        return self._conn.execute(
            "SELECT * FROM skc_records WHERE batch_id = ? AND status != 'success'", (batch_id,)
        ).fetchall()


@contextmanager
def open_store(db_path: Path) -> Iterator[Store]:
    store = Store(db_path)
    try:
        yield store
    finally:
        store.close()
