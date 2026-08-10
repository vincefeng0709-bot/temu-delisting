"""生成"待下架建议清单"导出文件 + 逐条 CLI 人工确认。"""
from __future__ import annotations

import csv
from pathlib import Path

from .classifier import DELIST_SUGGESTED, NEEDS_HUMAN_REVIEW
from .store import Store, Suggestion


def export_suggestions_csv(exports_dir: Path, batch_id: str, suggestions: list[Suggestion]) -> Path:
    out_path = exports_dir / f"{batch_id}.csv"
    with open(out_path, "w", newline="", encoding="utf-8-sig") as f:
        writer = csv.writer(f)
        writer.writerow(["id", "spu_id", "violation_type", "violation_detail", "classification", "review_status"])
        for s in suggestions:
            writer.writerow([s.id, s.spu_id, s.violation_type, s.violation_detail, s.classification, s.review_status])
    return out_path


def interactive_review(store: Store, batch_id: str) -> None:
    """逐条在终端询问 y/n，把结果写回 review_status。"""
    suggestions = store.list_suggestions(batch_id, review_status="pending_review")
    if not suggestions:
        print("[review] 没有待审核的条目。")
        return

    print(f"[review] 共 {len(suggestions)} 条待审核，逐条确认（y=确认下架 / n=跳过 / q=剩余全部跳过）：\n")
    for s in suggestions:
        label = "建议下架" if s.classification == DELIST_SUGGESTED else "未知类型-待人工判断"
        print(f"SPU {s.spu_id} | 违规类型: {s.violation_type} | {label}")
        print(f"  详情: {s.violation_detail[:120]}")
        answer = input("  是否确认下架该商品？[y/n/q]: ").strip().lower()
        if answer == "q":
            print("[review] 已停止，剩余条目保持 pending_review，可下次继续审核。")
            break
        elif answer == "y":
            store.set_review_status(s.id, "confirmed")
        else:
            store.set_review_status(s.id, "rejected")

    confirmed = len(store.list_suggestions(batch_id, review_status="confirmed"))
    print(f"\n[review] 本次确认 {confirmed} 条待执行下架。")
