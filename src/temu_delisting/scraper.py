"""违规处理页面：导航、按时间区间查询、解析表格。

URL 是实测确认过的真实地址（2026-08 联调时用 explore 命令走出来的）：
- 合规中心首页: https://agentseller.temu.com/govern/dashboard
- 违规处理页面: https://agentseller.temu.com/govern/offending-appeal-quick

日期筛选是"rocket-calendar"这个自研日历组件，触发输入框是只读的
（id="punishCreateTime"），不支持直接打字，必须点日历格子选日期。
选择器是照着联调时导出的真实 DOM 写的：

- 触发器：#punishCreateTime
- 弹窗容器：.rocket-calendar-picker-container
- 左/右两个月份面板：.rocket-calendar-range-left / .rocket-calendar-range-right
- 每个面板的年/月文字：.rocket-calendar-year-select / .rocket-calendar-month-select
- 翻页按钮（全局唯一，点一下左右两个面板会一起挪一个月）：
  .rocket-calendar-prev-month-btn / .rocket-calendar-next-month-btn
- 日期格子：td[title="2026年8月9日"] 这种格式，属性里年月日都是完整中文，
  同一个面板内不会重复；但左右两个面板在月末/月初交界处可能各自出现一次
  同一天（比如8月31日会同时出现在左边8月面板末尾和右边9月面板开头），
  所以点击时必须限定在具体某个面板里，不能整页搜。
- 确认按钮：.rocket-calendar-ok-btn（按钮文字是"确 定"，中间有个空格，
  不能用文字精确匹配，要用 class）
"""
from __future__ import annotations

import re
from dataclasses import dataclass

from playwright.sync_api import Page, TimeoutError as PlaywrightTimeoutError

from .browser import wait_settle
from .config import Settings
from .text_match import loose_text

VIOLATION_LIST_URL = "https://agentseller.temu.com/govern/offending-appeal-quick"

_DATE_TRIGGER = "#punishCreateTime"
_POPUP = ".rocket-calendar-picker-container"
_LEFT_PANEL = ".rocket-calendar-range-left"
_RIGHT_PANEL = ".rocket-calendar-range-right"
_PREV_MONTH_BTN = ".rocket-calendar-prev-month-btn"
_NEXT_MONTH_BTN = ".rocket-calendar-next-month-btn"
_OK_BTN = ".rocket-calendar-ok-btn"


@dataclass
class ViolationRow:
    spu_id: str
    violation_type: str
    violation_detail: str
    violation_status: str


def goto_violation_list(page: Page, settings: Settings) -> None:
    """直接跳转到 违规处理 页面。"""
    page.goto(VIOLATION_LIST_URL, wait_until="domcontentloaded")

    # 跨域名跳转首次可能弹出"确认授权并前往"这类一次性同意弹窗
    _dismiss_auth_dialog_if_present(page)
    wait_settle(page)


def _dismiss_auth_dialog_if_present(page: Page, timeout_ms: int = 3000) -> None:
    try:
        agree_button = (
            page.get_by_role("button", name=loose_text("确认授权并前往"))
            .or_(page.get_by_role("button", name=loose_text("同意")))
            .or_(page.get_by_role("button", name=loose_text("确认")))
        )
        agree_button.first.wait_for(timeout=timeout_ms)
        agree_button.first.click()
    except Exception:
        pass


def query_violations(page: Page, start_date: str, end_date: str) -> None:
    """在违规列表筛选区设置违规开始时间区间，点击查询。

    start_date / end_date 格式："YYYY-MM-DD"（只按天筛选，不需要具体时分秒）。
    违规对象类型、申诉状态等其他筛选项保持页面默认值不动。
    """
    start_year, start_month, start_day = (int(p) for p in start_date.split("-"))
    end_year, end_month, end_day = (int(p) for p in end_date.split("-"))

    page.locator(_DATE_TRIGGER).click()
    page.locator(_POPUP).wait_for(state="visible")

    _navigate_to_left_month(page, start_year, start_month)
    _click_day(page, _LEFT_PANEL, start_year, start_month, start_day)

    left_year, left_month = _panel_month(page, _LEFT_PANEL)
    if (end_year, end_month) == (left_year, left_month):
        _click_day(page, _LEFT_PANEL, end_year, end_month, end_day)
    else:
        # 右面板恒等于左面板+1个月，所以把左面板翻到"结束月份的上一个月"即可
        prev_month_year, prev_month = month_before(end_year, end_month)
        _navigate_to_left_month(page, prev_month_year, prev_month)
        _click_day(page, _RIGHT_PANEL, end_year, end_month, end_day)

    confirm_button = page.locator(_OK_BTN)
    if confirm_button.count():
        confirm_button.first.click()

    # 日历弹窗关闭有动画，点完"确定"不能立刻点"查询"——源码跑测试时靠
    # SLOW_MO_MS 的操作间隔意外掩盖了这个时序问题；打包成 exe 后没有
    # SLOW_MO_MS（没有 .env、默认是 0，全速跑），"查询"点得太早，日历弹窗
    # 还没真正关掉/筛选条件还没生效，结果查出来的是没按时间筛选的默认列表。
    # 这里显式等弹窗真正消失了再继续。超时时间给宽松点（网络代理/VPN 环境下
    # 可能会更慢），而且哪怕真等不到"确认关闭"的信号，也不整个报错崩掉——
    # 大概率弹窗其实已经视觉上关了，只是某个状态标记没按预期更新，继续往下
    # 走总比直接失败强。
    try:
        page.locator(_POPUP).wait_for(state="hidden", timeout=15000)
    except PlaywrightTimeoutError:
        try:
            page.keyboard.press("Escape")
            page.locator(_POPUP).wait_for(state="hidden", timeout=15000)
        except PlaywrightTimeoutError:
            pass

    page.get_by_role("button", name=loose_text("查询")).first.click()
    wait_settle(page)


def month_before(year: int, month: int) -> tuple[int, int]:
    """返回给定年月的上一个月，处理跨年（1月的上一个月是去年12月）。"""
    if month == 1:
        return year - 1, 12
    return year, month - 1


def _panel_month(page: Page, panel_selector: str) -> tuple[int, int]:
    panel = page.locator(panel_selector)
    year_text = panel.locator(".rocket-calendar-year-select").first.inner_text()
    month_text = panel.locator(".rocket-calendar-month-select").first.inner_text()
    year = int(re.sub(r"\D", "", year_text))
    month = int(re.sub(r"\D", "", month_text))
    return year, month


def _navigate_to_left_month(page: Page, target_year: int, target_month: int) -> None:
    for _ in range(36):
        year, month = _panel_month(page, _LEFT_PANEL)
        delta = (target_year - year) * 12 + (target_month - month)
        if delta == 0:
            return
        button = page.locator(_PREV_MONTH_BTN if delta < 0 else _NEXT_MONTH_BTN)
        button.first.click()
        page.wait_for_timeout(150)
    raise RuntimeError(f"日历翻页超过36次仍未到达目标月份 {target_year}-{target_month}，选择器可能已失效")


def _click_day(page: Page, panel_selector: str, year: int, month: int, day: int) -> None:
    title = f"{year}年{month}月{day}日"
    cell = page.locator(panel_selector).locator(f'td[title="{title}"] .rocket-calendar-date')
    cell.first.click()


_NEXT_PAGE_ITEM = 'li[title="下一页"]'


def parse_violation_rows(page: Page) -> list[ViolationRow]:
    """解析违规列表表格，逐页翻页直到没有下一页。

    分页是自研的 rocket-pagination 组件，"下一页"是个 <li> 不是按钮，可见
    内容只有一个箭头图标、没有文字——文字只在 title 属性里，get_by_role
    ("button", ...) 或者文字匹配天生找不到，之前一直只抓了第一页，是个真实
    bug。是否还有下一页看 aria-disabled 属性，不是靠 is_enabled()。
    """
    rows: list[ViolationRow] = []

    while True:
        rows.extend(_parse_current_page_rows(page))

        next_item = page.locator(_NEXT_PAGE_ITEM)
        if next_item.count() == 0:
            break
        if next_item.first.get_attribute("aria-disabled") == "true":
            break

        next_item.first.locator("a").click()
        wait_settle(page)

    return rows


def _parse_current_page_rows(page: Page) -> list[ViolationRow]:
    result: list[ViolationRow] = []
    table_rows = page.locator("table tbody tr")
    count = table_rows.count()
    for i in range(count):
        row = table_rows.nth(i)
        cells = row.locator("td")
        if cells.count() < 5:
            continue
        spu_text = cells.nth(1).inner_text()
        spu_id = _extract_spu_id(spu_text)
        violation_type = cells.nth(3).inner_text().strip()
        violation_detail = cells.nth(4).inner_text().strip()
        violation_status = cells.nth(5).inner_text().strip() if cells.count() > 5 else ""
        if spu_id:
            result.append(
                ViolationRow(
                    spu_id=spu_id,
                    violation_type=violation_type,
                    violation_detail=violation_detail,
                    violation_status=violation_status,
                )
            )
    return result


def _extract_spu_id(cell_text: str) -> str:
    for line in cell_text.splitlines():
        line = line.strip()
        if line.upper().startswith("SPU ID"):
            return line.split("：")[-1].split(":")[-1].strip()
    return ""
