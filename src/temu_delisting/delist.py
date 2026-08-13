"""单个 SPU 下所有 SKC 的下架处理流程。"""
from __future__ import annotations

import random
from dataclasses import dataclass
from typing import Callable

from playwright.sync_api import Page

from . import chat
from .browser import wait_settle
from .config import Settings
from .logging_setup import get_logger
from .popups import dismiss_known_popups
from .store import Store
from .text_match import loose_text

LIFECYCLE_MANAGEMENT_URL = "https://agentseller.temu.com/newon/product-select"


@dataclass
class SkcOutcome:
    skc_id: str
    status: str
    detail: str = ""


def goto_lifecycle_management(page: Page, settings: Settings) -> None:
    page.goto(LIFECYCLE_MANAGEMENT_URL, wait_until="domcontentloaded")
    wait_settle(page)
    dismiss_known_popups(page)


def _field_row(page: Page, label: str):
    """按字段标签文字定位到它所在的整行（CSS class 带哈希后缀，容易随构建变化，
    用标签文字 + 结构关系定位比直接写 class 名稳）。"""
    label_el = page.get_by_text(loose_text(label)).first
    return label_el.locator("xpath=..")


def query_spu(page: Page, spu_id: str) -> None:
    row = _field_row(page, "商品ID查询")

    # 下拉框默认是 SKC，需要切到 SPU
    row.locator('[data-testid="beast-core-select-header"]').click()
    page.get_by_text(loose_text("SPU")).first.click()

    text_input = row.locator('[data-testid="beast-core-input-htmlInput"]')
    text_input.fill(spu_id)

    page.get_by_role("button", name=loose_text("查询")).first.click()
    wait_settle(page)
    dismiss_known_popups(page)


def collect_skc_ids(page: Page) -> list[str]:
    """从"SKC属性"列里抓取所有 SKC ID 数字串。

    用 class 前缀（哈希后缀会变，但 "skc-property-render_skcId" 这个前缀是
    组件名派生的，比较稳）精确定位，不再用"全页面搜6位以上数字"这种会把
    价格/日期/其他行数据也搜进来的粗糙正则。
    """
    skc_ids: list[str] = []
    candidates = page.locator('[class*="skc-property-render_skcId"]')
    for i in range(candidates.count()):
        text = candidates.nth(i).inner_text().strip()
        if text.isdigit() and text not in skc_ids:
            skc_ids.append(text)
    return skc_ids


def delist_one_skc(
    page: Page,
    settings: Settings,
    spu_id: str,
    skc_id: str,
    store: Store,
    batch_id: str,
    dry_run: bool = False,
    pause_before_chat: bool = False,
    pause_on_error: bool = False,
) -> SkcOutcome:
    """处理单个 SKC 的下架申请。调用前客服面板必须已经处于打开状态
    （见 delist_spu 里的 chat.open_chat_session 调用），这里只负责
    "自助工具 -> 商品下架"这一段，不会重新打开/关闭客服面板。"""
    delist_reason = random.choice(settings.delist_reasons)
    baseline_reply_count = chat.count_delist_replies(page, skc_id)

    if pause_before_chat:
        page.pause()
    chat.trigger_delist_flow(page, pause_on_error=pause_on_error)
    chat.wait_for_send_product_prompt(page, timeout_ms=settings.chat_timeout_seconds * 1000)
    chat.submit_delist_request(page, skc_id, delist_reason, dry_run=dry_run)

    if dry_run:
        outcome = SkcOutcome(skc_id=skc_id, status="timeout_needs_human", detail="dry-run，未真正提交")
        store.record_skc_result(skc_id, spu_id, batch_id, "timeout_needs_human", delist_reason, outcome.detail)
        return outcome

    result = chat.wait_for_delist_confirmation(
        page, skc_id, timeout_ms=settings.chat_timeout_seconds * 1000,
        baseline_reply_count=baseline_reply_count,
    )
    outcome = SkcOutcome(skc_id=skc_id, status=result.status, detail=result.detail)
    store.record_skc_result(skc_id, spu_id, batch_id, result.status, delist_reason, result.detail)
    return outcome


def delist_spu(
    page: Page,
    settings: Settings,
    spu_id: str,
    store: Store,
    batch_id: str,
    dry_run: bool = False,
    pause_before_chat: bool = False,
    pause_on_error: bool = False,
    should_stop: Callable[[], bool] | None = None,
) -> list[SkcOutcome]:
    """should_stop：GUI"停止"按钮用的钩子，每处理完一个 SKC 后检查一次，
    返回 True 就不再处理这个 SPU 剩下的 SKC（不会中途打断正在填的表单，
    避免留下半提交的脏状态，最多是"等这个 SKC 处理完再停"）。"""
    goto_lifecycle_management(page, settings)
    query_spu(page, spu_id)
    skc_ids = collect_skc_ids(page)

    outcomes: list[SkcOutcome] = []
    session_opened = False

    for skc_id in skc_ids:
        if should_stop is not None and should_stop():
            break

        if store.is_already_delisted(skc_id):
            outcomes.append(
                SkcOutcome(skc_id=skc_id, status="success", detail="已在此前批次处理过，跳过")
            )
            continue

        if not session_opened:
            # 客服面板每个 SPU 页面只打开一次，同一个 SPU 下后续的 SKC 都
            # 复用这个已经打开的面板，不重复点客服图标（它是个开关，重复点
            # 会把面板关掉）
            dismiss_known_popups(page, timeout_ms=1500)
            chat.open_chat_session(page)
            session_opened = True
        else:
            # 连续处理下一个 SKC 前稍微停顿一下，避免过快连续触发
            page.wait_for_timeout(settings.chat_cooldown_seconds * 1000)

        try:
            outcome = delist_one_skc(
                page,
                settings,
                spu_id,
                skc_id,
                store,
                batch_id,
                dry_run=dry_run,
                pause_before_chat=pause_before_chat,
                pause_on_error=pause_on_error,
            )
        except Exception as exc:  # noqa: BLE001
            # 单个 SKC 出错（比如客服面板上卡了个没清理掉的"已处理成功"残留
            # 弹窗，把后面的点击一直堵到超时）之前会直接把异常甩到 delist_spu
            # 外面，导致这个 SPU 剩下的 SKC 全部没机会处理——一个 SKC 卡住不该
            # 连累同一个 SPU 下别的、本来能正常处理的 SKC。这里接住，记一条
            # 清楚说明原因的失败记录，继续处理下一个 SKC。
            get_logger().exception(f"[delist] SKC {skc_id} 处理时出错，跳过，继续下一个")
            outcome = SkcOutcome(skc_id=skc_id, status="failed", detail=f"处理出错，已跳过：{exc}")
            store.record_skc_result(skc_id, spu_id, batch_id, "failed", detail=outcome.detail)
        outcomes.append(outcome)
    return outcomes
