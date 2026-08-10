from pathlib import Path

import pytest

from temu_delisting.store import Store


@pytest.fixture
def store(tmp_path: Path) -> Store:
    s = Store(tmp_path / "test.db")
    yield s
    s.close()


def test_create_batch_returns_id(store: Store):
    batch_id = store.create_batch("2026-08-06 00:00:00", "2026-08-07 00:00:00")
    assert batch_id


def test_add_and_list_suggestions(store: Store):
    batch_id = store.create_batch("2026-08-06", "2026-08-07")
    store.add_suggestion(batch_id, "SPU1", "知识产权违规", "详情", "delist_suggested")
    suggestions = store.list_suggestions(batch_id)
    assert len(suggestions) == 1
    assert suggestions[0].spu_id == "SPU1"
    assert suggestions[0].review_status == "pending_review"


def test_review_status_filter(store: Store):
    batch_id = store.create_batch("2026-08-06", "2026-08-07")
    sid = store.add_suggestion(batch_id, "SPU1", "知识产权违规", "", "delist_suggested")
    store.set_review_status(sid, "confirmed")
    confirmed = store.list_suggestions(batch_id, review_status="confirmed")
    pending = store.list_suggestions(batch_id, review_status="pending_review")
    assert len(confirmed) == 1
    assert len(pending) == 0


def test_skc_idempotency(store: Store):
    batch_id = store.create_batch("2026-08-06", "2026-08-07")
    assert store.is_already_delisted("SKC1") is False

    store.record_skc_result("SKC1", "SPU1", batch_id, "success", "业务调整下架")
    assert store.is_already_delisted("SKC1") is True

    # 重新记录（比如批次重跑）应更新而不是报错
    store.record_skc_result("SKC1", "SPU1", batch_id, "failed", "业务调整下架", "重试失败")
    assert store.get_skc_status("SKC1") == "failed"


def test_list_failures_excludes_success(store: Store):
    batch_id = store.create_batch("2026-08-06", "2026-08-07")
    store.record_skc_result("SKC1", "SPU1", batch_id, "success")
    store.record_skc_result("SKC2", "SPU1", batch_id, "timeout_needs_human")
    failures = store.list_failures(batch_id)
    assert len(failures) == 1
    assert failures[0]["skc_id"] == "SKC2"
