"""违规类型 -> 下架建议 / 待人工判断。"""
from __future__ import annotations

DELIST_SUGGESTED = "delist_suggested"
NEEDS_HUMAN_REVIEW = "needs_human_review"


def classify(violation_type: str, known_delist_types: list[str]) -> str:
    """已知违规类型清单命中 -> delist_suggested；否则 -> needs_human_review。

    不会静默丢弃未知类型：调用方应当把 needs_human_review 的条目也放进
    导出清单里，提醒人工去判断要不要加入 known_delist_types。
    """
    normalized = violation_type.strip()
    known = {t.strip() for t in known_delist_types}
    return DELIST_SUGGESTED if normalized in known else NEEDS_HUMAN_REVIEW
