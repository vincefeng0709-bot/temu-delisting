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
    created_at TEXT NOT NULL,
    total_from_page INTEGER,
    raw_row_count INTEGER
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
class BatchInfo:
    batch_id: str
    start_time: str
    end_time: str
    created_at: str
    # 网页自己显示的"共X条数据"，和这次实际抓到的行数（没做任何去重，
    # 同一个 SPU 在不同地区各算一条也都留着）——扫描一开始建批次的时候
    # 还没抓完，不知道这两个数，抓完之后再用 set_batch_stats 补上去。
    total_from_page: Optional[int]
    raw_row_count: Optional[int]


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
        self._migrate_schema()

    def _migrate_schema(self) -> None:
        """老数据库是在加 total_from_page/raw_row_count 这两列之前建的，
        CREATE TABLE IF NOT EXISTS 不会给已经存在的表补列，这里手动补上，
        不会丢现有数据。"""
        existing_columns = {row["name"] for row in self._conn.execute("PRAGMA table_info(batches)")}
        if "total_from_page" not in existing_columns:
            self._conn.execute("ALTER TABLE batches ADD COLUMN total_from_page INTEGER")
        if "raw_row_count" not in existing_columns:
            self._conn.execute("ALTER TABLE batches ADD COLUMN raw_row_count INTEGER")
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

    def set_batch_stats(self, batch_id: str, total_from_page: Optional[int], raw_row_count: int) -> None:
        self._conn.execute(
            "UPDATE batches SET total_from_page = ?, raw_row_count = ? WHERE batch_id = ?",
            (total_from_page, raw_row_count, batch_id),
        )
        self._conn.commit()

    def get_batch(self, batch_id: str) -> Optional[BatchInfo]:
        row = self._conn.execute("SELECT * FROM batches WHERE batch_id = ?", (batch_id,)).fetchone()
        if row is None:
            return None
        return BatchInfo(
            batch_id=row["batch_id"],
            start_time=row["start_time"],
            end_time=row["end_time"],
            created_at=row["created_at"],
            total_from_page=row["total_from_page"],
            raw_row_count=row["raw_row_count"],
        )

    def count_unique_spu(self, batch_id: str) -> int:
        row = self._conn.execute(
            "SELECT COUNT(DISTINCT spu_id) AS c FROM suggestions WHERE batch_id = ?", (batch_id,)
        ).fetchone()
        return row["c"] if row else 0

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

    def confirm_all_suggested(self, batch_id: str) -> int:
        """接口程序用：分机远程触发「扫描并自动下架」时，把这批扫描到的
        条目（不分 delist_suggested / needs_human_review）全部自动标成
        confirmed——分机那边已经明确要求主机这边不需要人工复核，直接按
        用户的决定全部确认。返回确认了多少条。"""
        cur = self._conn.execute(
            "UPDATE suggestions SET review_status = 'confirmed' WHERE batch_id = ?",
            (batch_id,),
        )
        self._conn.commit()
        return cur.rowcount

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
