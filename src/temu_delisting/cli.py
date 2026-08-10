"""命令行入口：scan（生成建议清单）/ apply（执行已确认清单）。"""
from __future__ import annotations

from pathlib import Path

import click

from . import scraper
from .auth import ensure_logged_in
from .browser import open_page
from .classifier import classify
from .config import load_settings
from .delist import delist_spu
from .logging_setup import get_logger, setup_logging
from .review import export_suggestions_csv, interactive_review
from .session_import import import_cookies
from .store import open_store


def echo(message: str) -> None:
    """同时打印到终端和日志文件，方便事后审计"跑没跑、跑了哪些、出过什么错"。"""
    click.echo(message)
    get_logger().info(message)


@click.group()
def main() -> None:
    """Temu 卖家中心违规商品自动化下架工具。"""
    setup_logging(load_settings().log_dir)


@main.command("import-cookies")
@click.argument("cookie_json_path", type=click.Path(exists=True, dir_okay=False, path_type=Path))
def import_cookies_cmd(cookie_json_path: Path) -> None:
    """把从正常浏览器导出的 Cookie JSON 转成登录态，供 Playwright 复用。

    使用方法：
    1. 在你平时正常登录的 Chrome 里登录卖家中心
    2. 用 Cookie-Editor 之类的扩展导出该站点 Cookie 为 JSON 文件
    3. temu-delisting import-cookies <该json文件路径>
    """
    settings = load_settings()
    count = import_cookies(cookie_json_path, settings.storage_state_path)
    echo(f"[import-cookies] 已导入 {count} 条 Cookie，写入 {settings.storage_state_path}")
    echo("[import-cookies] 现在可以直接跑 scan / apply 了。")


@main.command()
def explore() -> None:
    """调试用：登录后打开浏览器并暂停，方便手动点击核对页面结构/URL。

    浏览器窗口会一直开着，同时终端会打印一个 Playwright Inspector 提示。
    你可以在浏览器里随便点，点到想看的页面后回到终端，按 Ctrl+C 结束
    （退出前会把当前登录态重新保存一次）。
    """
    settings = load_settings()
    with open_page(settings) as page:
        ensure_logged_in(page, settings)
        echo(f"[explore] 当前 URL: {page.url}")
        echo("[explore] 浏览器已打开，随便点击导航。按 Ctrl+C 结束并保存登录态...")
        page.pause()


@main.command()
@click.option("--start", required=True, help='违规开始日期，如 "2026-08-06"')
@click.option("--end", required=True, help='违规结束日期，如 "2026-08-07"')
@click.option("--review/--no-review", default=True, help="扫描完是否立即进入逐条人工审核（默认是）")
def scan(start: str, end: str, review: bool) -> None:
    """按时间区间抓取违规商品，生成待下架建议清单。"""
    settings = load_settings()

    with open_store(settings.db_path) as store:
        batch_id = store.create_batch(start, end)
        echo(f"[scan] 批次 ID: {batch_id}")

        with open_page(settings) as page:
            ensure_logged_in(page, settings)
            scraper.goto_violation_list(page, settings)
            scraper.query_violations(page, start, end)
            rows = scraper.parse_violation_rows(page)

        echo(f"[scan] 抓取到 {len(rows)} 条违规记录。")

        for row in rows:
            classification = classify(row.violation_type, settings.known_delist_types)
            store.add_suggestion(
                batch_id, row.spu_id, row.violation_type, row.violation_detail, classification
            )

        suggestions = store.list_suggestions(batch_id)
        out_path = export_suggestions_csv(settings.exports_dir, batch_id, suggestions)
        echo(f"[scan] 建议清单已导出: {out_path}")

        if review:
            interactive_review(store, batch_id)
        else:
            echo(
                f"[scan] 请审核后再执行: temu-delisting review --batch {batch_id}，"
                f"或直接 temu-delisting apply --batch {batch_id}"
            )


@main.command()
@click.option("--batch", "batch_id", required=True, help="scan 命令输出的批次 ID")
def review(batch_id: str) -> None:
    """对某个批次做逐条人工审核（如果 scan 时跳过了审核）。"""
    settings = load_settings()
    with open_store(settings.db_path) as store:
        interactive_review(store, batch_id)


@main.command()
@click.option("--batch", "batch_id", required=True, help="scan 命令输出的批次 ID")
@click.option("--dry-run", is_flag=True, default=False, help="只走到申请下架前一步，不真正提交")
@click.option(
    "--pause-before-chat",
    is_flag=True,
    default=False,
    help="调试用：每次打开客服对话前先暂停（弹出 Playwright Inspector），方便现场看 DOM",
)
@click.option(
    "--pause-on-error",
    is_flag=True,
    default=False,
    help="调试用：等不到\"自助工具\"时不直接报错退出，而是冻结在卡住的现场，方便检查真实状态",
)
def apply(batch_id: str, dry_run: bool, pause_before_chat: bool, pause_on_error: bool) -> None:
    """执行已人工确认（confirmed）的下架建议。"""
    settings = load_settings()

    with open_store(settings.db_path) as store:
        confirmed = store.list_suggestions(batch_id, review_status="confirmed")
        if not confirmed:
            echo("[apply] 没有已确认待执行的条目，先跑 scan / review。")
            return

        echo(f"[apply] 共 {len(confirmed)} 个 SPU 待处理{'（dry-run，不会真正提交）' if dry_run else ''}。")

        failed_spus: list[tuple[str, str]] = []

        with open_page(settings) as page:
            ensure_logged_in(page, settings)
            for suggestion in confirmed:
                echo(f"[apply] 处理 SPU {suggestion.spu_id} ...")
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
                    )
                except Exception as exc:  # noqa: BLE001 — 单个 SPU 出错不能拖垮整批
                    echo(f"  [error] SPU {suggestion.spu_id} 处理失败，跳过，继续下一个: {exc}")
                    failed_spus.append((suggestion.spu_id, str(exc)))
                    continue

                for outcome in outcomes:
                    echo(f"  SKC {outcome.skc_id}: {outcome.status} ({outcome.detail})")

        failures = store.list_failures(batch_id)
        if failed_spus:
            echo(f"[apply] 有 {len(failed_spus)} 个 SPU 整体处理失败（脚本报错，可能没走完）：")
            for spu_id, error in failed_spus:
                echo(f"  SPU {spu_id}: {error}")
        if failures:
            echo(
                f"[apply] 有 {len(failures)} 个 SKC 未成功下架，需要人工确认，"
                f"用 `temu-delisting failures --batch {batch_id}` 查看详情。"
            )
        if not failed_spus and not failures:
            echo("[apply] 全部处理完成。")


@main.command()
@click.option("--batch", "batch_id", required=True, help="scan 命令输出的批次 ID")
def failures(batch_id: str) -> None:
    """查看某个批次里未成功下架（失败/超时）的 SKC，方便人工跟进。"""
    settings = load_settings()
    with open_store(settings.db_path) as store:
        rows = store.list_failures(batch_id)
        if not rows:
            echo(f"[failures] 批次 {batch_id} 没有失败/超时的记录。")
            return

        echo(f"[failures] 批次 {batch_id} 共 {len(rows)} 条需要人工跟进：\n")
        for row in rows:
            echo(
                f"SPU {row['spu_id']} | SKC {row['skc_id']} | 状态: {row['status']} | "
                f"下架原因: {row['delist_reason']} | 更新时间: {row['updated_at']}"
            )
            echo(f"  详情: {row['detail']}\n")


if __name__ == "__main__":
    main()
