"""scan / apply 的核心业务逻辑，抽成纯函数，CLI 和 GUI 共用，不重复实现。

CLI 用 `echo()`（打印到终端+写日志）当 log 回调；GUI 会传一个把每行文字
转发成 Qt 信号的回调，两边共用同一套业务逻辑，不会出现"命令行一套、
界面一套"渐渐跑偏的问题。
"""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Optional

from . import scraper
from .auth import ensure_logged_in
from .browser import open_page
from .classifier import classify
from .config import Settings
from .delist import SkcOutcome, delist_spu
from .review import export_suggestions_csv
from .store import Store, Suggestion

LogFn = Callable[[str], None]
ProgressFn = Callable[[int, int, str], None]  # (当前第几个, 总数, 当前 SPU ID)


def _noop_log(_message: str) -> None:
    pass


@dataclass
class ScanResult:
    batch_id: str
    row_count: int
    export_path: Path
    suggestions: list[Suggestion]


def run_scan(
    settings: Settings,
    store: Store,
    start: str,
    end: str,
    log: LogFn = _noop_log,
) -> ScanResult:
    """按日期区间抓取违规商品，打标分类，导出建议清单。不做人工审核 ——
    审核是调用方（CLI 的 review 命令 / GUI 的审核表格）自己的事。"""
    batch_id = store.create_batch(start, end)
    log(f"[scan] 批次 ID: {batch_id}")

    with open_page(settings) as page:
        ensure_logged_in(page, settings)
        scraper.goto_violation_list(page, settings)
        scraper.query_violations(page, start, end)
        rows = scraper.parse_violation_rows(page)

    log(f"[scan] 抓取到 {len(rows)} 条违规记录。")

    for row in rows:
        classification = classify(row.violation_type, settings.known_delist_types)
        store.add_suggestion(
            batch_id, row.spu_id, row.violation_type, row.violation_detail, classification
        )

    suggestions = store.list_suggestions(batch_id)
    export_path = export_suggestions_csv(settings.exports_dir, batch_id, suggestions)
    log(f"[scan] 建议清单已导出: {export_path}")

    return ScanResult(
        batch_id=batch_id, row_count=len(rows), export_path=export_path, suggestions=suggestions
    )


@dataclass
class SpuApplyResult:
    spu_id: str
    outcomes: list[SkcOutcome] = field(default_factory=list)
    error: Optional[str] = None


@dataclass
class ApplyResult:
    spu_results: list[SpuApplyResult] = field(default_factory=list)
    stopped_early: bool = False

    @property
    def failed_spus(self) -> list[SpuApplyResult]:
        return [r for r in self.spu_results if r.error is not None]

    @property
    def all_skc_outcomes(self) -> list[SkcOutcome]:
        return [o for r in self.spu_results for o in r.outcomes]


def run_apply(
    settings: Settings,
    store: Store,
    batch_id: str,
    dry_run: bool = False,
    pause_before_chat: bool = False,
    pause_on_error: bool = False,
    log: LogFn = _noop_log,
    progress: Optional[ProgressFn] = None,
    should_stop: Optional[Callable[[], bool]] = None,
) -> ApplyResult:
    """执行某批次里已人工确认（confirmed）的 SPU。单个 SPU 出错不拖垮整批，
    记下来跳到下一个继续。should_stop 每个 SPU 开始前检查一次，也会往下传
    给 delist_spu 在每个 SKC 之间再检查一次（GUI"停止"按钮用）。"""
    confirmed = store.list_suggestions(batch_id, review_status="confirmed")
    if not confirmed:
        log("[apply] 没有已确认待执行的条目，先跑 scan / review。")
        return ApplyResult()

    total = len(confirmed)
    log(f"[apply] 共 {total} 个 SPU 待处理{'（dry-run，不会真正提交）' if dry_run else ''}。")

    spu_results: list[SpuApplyResult] = []
    stopped_early = False

    with open_page(settings) as page:
        ensure_logged_in(page, settings)
        for index, suggestion in enumerate(confirmed, start=1):
            if should_stop is not None and should_stop():
                stopped_early = True
                break

            if progress is not None:
                progress(index, total, suggestion.spu_id)
            log(f"[apply] 处理 SPU {suggestion.spu_id} ...")

            try:
                outcomes = delist_spu(
                    page,
                    settings,
                    suggestion.spu_id,
                    store,
                    batch_id,
                    dry_run=dry_run,
                    pause_before_chat=pause_before_chat,
                    pause_on_error=pause_on_error,
                    should_stop=should_stop,
                )
            except Exception as exc:  # noqa: BLE001 — 单个 SPU 出错不能拖垮整批
                log(f"  [error] SPU {suggestion.spu_id} 处理失败，跳过，继续下一个: {exc}")
                spu_results.append(SpuApplyResult(spu_id=suggestion.spu_id, error=str(exc)))
                continue

            for outcome in outcomes:
                log(f"  SKC {outcome.skc_id}: {outcome.status} ({outcome.detail})")
            spu_results.append(SpuApplyResult(spu_id=suggestion.spu_id, outcomes=outcomes))

    return ApplyResult(spu_results=spu_results, stopped_early=stopped_early)
