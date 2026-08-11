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
- 翻页按钮：.rocket-calendar-prev-month-btn / .rocket-calendar-next-month-btn
  ——左右面板各自有一份，互相独立、不联动，必须限定在对应面板内点击
  （实测跨月选日期时若共用一个全局按钮会导致翻错面板）
- 日期格子：td[title="2026年8月9日"] 这种格式，属性里年月日都是完整中文，
  同一个面板内不会重复；但左右两个面板在月末/月初交界处可能各自出现一次
  同一天（比如8月31日会同时出现在左边8月面板末尾和右边9月面板开头），
  所以点击时必须限定在具体某个面板里，不能整页搜。
- 确认按钮：.rocket-calendar-ok-btn（按钮文字是"确 定"，中间有个空格，
  不能用文字精确匹配，要用 class）
"""
from __future__ import annotations

import random
import re
from dataclasses import dataclass

from playwright.sync_api import Page, TimeoutError as PlaywrightTimeoutError

from .browser import wait_settle
from .config import Settings
from .logging_setup import get_logger
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
    logger = get_logger()
    start_year, start_month, start_day = (int(p) for p in start_date.split("-"))
    end_year, end_month, end_day = (int(p) for p in end_date.split("-"))
    logger.info(f"[scraper] 开始设置日期筛选：{start_date} ~ {end_date}")

    page.locator(_DATE_TRIGGER).click()
    page.locator(_POPUP).wait_for(state="visible")
    logger.info("[scraper] 日历弹窗已打开")

    _navigate_panel_to_month(page, _LEFT_PANEL, start_year, start_month, "左")
    _click_day(page, _LEFT_PANEL, start_year, start_month, start_day)
    logger.info(f"[scraper] 已点击左面板起始日 {start_year}-{start_month}-{start_day}")

    if (end_year, end_month) == (start_year, start_month):
        # 起止同一个月，两次点击都在左面板里完成，不用碰右面板
        _click_day(page, _LEFT_PANEL, end_year, end_month, end_day)
        logger.info(f"[scraper] 起止同月，已在左面板点击结束日 {end_year}-{end_month}-{end_day}")
    else:
        # 实测发现左右两个面板各自有自己独立的"上/下个月"按钮（不是共用
        # 一组、联动挪动的），之前假设"右面板恒等于左面板+1个月"是错的——
        # 选大跨度日期区间时（比如跨好几个月）会导致结束日期点到完全不
        # 相干的月份去，查出来的数据跟手动筛选对不上号。这里改成左右面板
        # 各自独立翻页到目标月份。
        _navigate_panel_to_month(page, _RIGHT_PANEL, end_year, end_month, "右")
        _click_day(page, _RIGHT_PANEL, end_year, end_month, end_day)
        logger.info(f"[scraper] 已点击右面板结束日 {end_year}-{end_month}-{end_day}")

    confirm_button = page.locator(_OK_BTN)
    if confirm_button.count():
        confirm_button.first.click()
        logger.info("[scraper] 已点击日历「确定」按钮")
    else:
        logger.warning("[scraper] 未找到日历「确定」按钮，跳过点击")

    # 日历弹窗关闭有动画，点完"确定"不能立刻点"查询"——源码跑测试时靠
    # SLOW_MO_MS 的操作间隔意外掩盖了这个时序问题；打包成 exe 后没有
    # SLOW_MO_MS（没有 .env、默认是 0，全速跑），"查询"点得太早，日历弹窗
    # 还没真正关掉/筛选条件还没生效，结果查出来的是没按时间筛选的默认列表。
    # 这里显式等弹窗真正消失了再继续。超时时间给宽松点（网络代理/VPN 环境下
    # 可能会更慢），而且哪怕真等不到"确认关闭"的信号，也不整个报错崩掉——
    # 大概率弹窗其实已经视觉上关了，只是某个状态标记没按预期更新，继续往下
    # 走总比直接失败强。这几个分支的具体走向都记日志，方便排查"时间筛选
    # 没生效"这类问题到底是卡在哪一步。
    try:
        page.locator(_POPUP).wait_for(state="hidden", timeout=15000)
        logger.info("[scraper] 日历弹窗已在 15 秒内正常关闭")
    except PlaywrightTimeoutError:
        logger.warning("[scraper] 日历弹窗 15 秒内未关闭，尝试按 Escape 强制关闭")
        try:
            page.keyboard.press("Escape")
            page.locator(_POPUP).wait_for(state="hidden", timeout=15000)
            logger.info("[scraper] 按 Escape 后日历弹窗已关闭")
        except PlaywrightTimeoutError:
            logger.error("[scraper] 日历弹窗始终未关闭（15+15秒都超时），继续往下走，筛选可能没生效")

    page.get_by_role("button", name=loose_text("查询")).first.click()
    logger.info("[scraper] 已点击「查询」按钮")
    wait_settle(page)
    logger.info("[scraper] 查询后页面已 settle")


def _panel_month(page: Page, panel_selector: str) -> tuple[int, int]:
    panel = page.locator(panel_selector)
    year_text = panel.locator(".rocket-calendar-year-select").first.inner_text()
    month_text = panel.locator(".rocket-calendar-month-select").first.inner_text()
    year = int(re.sub(r"\D", "", year_text))
    month = int(re.sub(r"\D", "", month_text))
    return year, month


def _navigate_panel_to_month(
    page: Page, panel_selector: str, target_year: int, target_month: int, panel_label: str = ""
) -> None:
    """把指定面板（左或右）独立翻页到目标年月——两个面板各自的翻页按钮
    是分开的元素，必须限定在对应面板内点击，不能整页搜（否则永远点到
    左面板那个）。"""
    logger = get_logger()
    panel = page.locator(panel_selector)
    start_year, start_month = _panel_month(page, panel_selector)
    for i in range(120):
        year, month = _panel_month(page, panel_selector)
        delta = (target_year - year) * 12 + (target_month - month)
        if delta == 0:
            logger.info(
                f"[scraper] {panel_label}面板从 {start_year}-{start_month} 翻到目标 "
                f"{target_year}-{target_month}，共翻了 {i} 次"
            )
            return
        button = panel.locator(_PREV_MONTH_BTN if delta < 0 else _NEXT_MONTH_BTN)
        button.first.click()
        page.wait_for_timeout(150)
    logger.error(
        f"[scraper] {panel_label}面板翻页 120 次仍停在 {year}-{month}，未到达目标 "
        f"{target_year}-{target_month}"
    )
    raise RuntimeError(f"日历翻页超过120次仍未到达目标月份 {target_year}-{target_month}，选择器可能已失效")


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

    实测发现"点下一页"不完全可靠：翻页太快有时会被网站限流/报网络错误，
    点击其实没有真正翻页，但 aria-disabled 依旧是 false，如果不校验页面
    内容是否真的变了，就会在原地反复抓同一页，导致同一条违规记录被重复
    收录好几次（220 条里真正不重复的只有 50 条，就是这个原因）。这里在
    翻页前后各记一次"本页第一行的签名"，点击后如果签名没变就重试几次，
    真的翻不动了就当作已经到底，不再继续抓（不整个报错崩掉）。

    另外，日期跨度大、需要翻很多页时最容易触发网站的网络错误/限流——同事
    实测反馈过这个现象。固定 400ms 的翻页间隔节奏太规律、太快，不像人在
    操作，这里改成随机化的停顿（600~1400ms），每翻 8 页左右再额外多歇一
    小段时间，尽量降低触发限流的概率；同时保留总页数上限兜底，避免限流
    真的触发时陷入死循环刷屏。
    """
    logger = get_logger()
    rows: list[ViolationRow] = []
    seen: set[tuple[str, str, str]] = set()

    for page_index in range(500):
        page_rows = _parse_current_page_rows(page)
        before_signature = _page_signature(page_rows)
        new_count = 0
        for row in page_rows:
            key = (row.spu_id, row.violation_type, row.violation_detail)
            if key not in seen:
                seen.add(key)
                rows.append(row)
                new_count += 1
        logger.info(
            f"[scraper] 第 {page_index + 1} 页：本页 {len(page_rows)} 行，"
            f"新增 {new_count} 条，累计 {len(rows)} 条"
        )

        next_item = page.locator(_NEXT_PAGE_ITEM)
        if next_item.count() == 0:
            logger.info("[scraper] 找不到「下一页」元素，停止翻页")
            break
        if next_item.first.get_attribute("aria-disabled") == "true":
            logger.info("[scraper] 「下一页」已禁用（aria-disabled=true），已到最后一页")
            break

        if page_index > 0 and page_index % 8 == 0:
            page.wait_for_timeout(random.randint(2500, 4000))

        advanced = False
        for attempt in range(5):
            page.wait_for_timeout(random.randint(600, 1400))
            next_item.first.locator("a").click()
            wait_settle(page)
            after_signature = _page_signature(_parse_current_page_rows(page))
            if after_signature != before_signature:
                advanced = True
                if attempt > 0:
                    logger.warning(f"[scraper] 第 {page_index + 1} 页翻页重试 {attempt} 次后才成功")
                break
            logger.warning(
                f"[scraper] 第 {page_index + 1} 页点击「下一页」第 {attempt + 1} 次后页面内容未变化"
            )
        if not advanced:
            # 翻页按钮没禁用，但连续多次点击后页面内容都没变——大概率是
            # 网络错误/限流卡住了，不再继续翻页，把已经抓到的先返回。
            logger.error(
                f"[scraper] 第 {page_index + 1} 页连续 5 次翻页都没有变化，"
                f"判定为卡住/限流，停止翻页（可能导致抓取数量比实际少）"
            )
            break

    logger.info(f"[scraper] 翻页结束，共抓取 {len(rows)} 条去重后的违规记录")
    return rows


def _page_signature(rows: list[ViolationRow]) -> tuple[str, ...]:
    return tuple(f"{r.spu_id}|{r.violation_type}" for r in rows)


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
