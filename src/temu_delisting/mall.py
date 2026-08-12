"""同一个 Temu 登录下可能挂了不止一个店铺（比如"SaveNest"和"Dwmane Shop"共用
一套登录 Cookie）。实测发现"当前激活的是哪个店铺"是服务端记的会话状态，不是
单纯靠 Cookie 就能决定的——哪怕导出 Cookie 那一刻人工浏览器里已经手动切到了
目标店铺，自动化这边用同一份 Cookie 开一个新会话，落地的默认店铺也可能还是
另一个，必须在页面上显式点一次"切换"才会真的生效。

选择器是照着联调时导出的真实 DOM 写的：
- 右上角店铺信息触发器：.account-info_accountInfo__wc0kw（点一下展开小面板）
- 展开后的小面板：.account-info_mainMall__R6U14，里面有个"切换"按钮，点了
  才会弹出真正的"切换店铺"大弹窗
- 弹窗：.account-info_changeModal__6sHPm，里面每个店铺一行
  （.account-info_mallSection__zkiSZ），店铺名字在 .account-info_mallName__7Mk2U，
  当前激活的那一行会带 account-info_active__xOT-P 这个 class、按钮是禁用的
"""
from __future__ import annotations

from playwright.sync_api import Page, TimeoutError as PlaywrightTimeoutError

from .browser import wait_settle
from .logging_setup import get_logger
from .text_match import loose_text

_ACCOUNT_INFO_TRIGGER = ".account-info_accountInfo__wc0kw"
_MAIN_MALL_PANEL = ".account-info_mainMall__R6U14"
_SWITCH_MODAL = ".account-info_changeModal__6sHPm"
_MALL_SECTION = ".account-info_mallSection__zkiSZ"


def read_current_mall_name(page: Page) -> str:
    """读页面右上角当前显示的店铺名字。读不到就返回空字符串（不报错，
    调用方自己决定要不要因为读不到而报错）。"""
    locator = page.locator(_ACCOUNT_INFO_TRIGGER).locator(".account-info_mallInfo__ts61W")
    if locator.count() == 0:
        return ""
    return locator.first.inner_text().strip()


def ensure_correct_mall(page: Page, mall_name: str) -> None:
    """确保当前自动化会话激活的是 mall_name 这个店铺，不是就切过去。

    mall_name 为空字符串时直接跳过（老账号、或者本来就只有一个店铺，不需要
    校验/切换）。mall_name 非空但切换失败（比如页面结构变了、或者这个账号
    根本没有权限访问这个名字的店铺）会抛异常——宁可让这次扫描/下架直接
    报错停下来，也不能在错的店铺上继续跑，那样抓到/下架的就是另一个店铺
    的商品，风险比报错更大。
    """
    if not mall_name:
        return

    logger = get_logger()
    current = read_current_mall_name(page)
    if current == mall_name:
        logger.info(f"[mall] 当前店铺已经是「{mall_name}」，不需要切换")
        return

    logger.info(f"[mall] 当前店铺是「{current}」，需要切换到「{mall_name}」")

    page.locator(_ACCOUNT_INFO_TRIGGER).first.click()
    switch_button = page.locator(_MAIN_MALL_PANEL).get_by_text(loose_text("切换"))
    try:
        switch_button.first.wait_for(state="visible", timeout=5000)
    except PlaywrightTimeoutError:
        raise RuntimeError(
            f"没能找到店铺切换入口，页面结构可能变了（想切到「{mall_name}」，"
            f"当前是「{current}」）"
        )
    switch_button.first.click()

    try:
        page.locator(_SWITCH_MODAL).wait_for(state="visible", timeout=10000)
    except PlaywrightTimeoutError:
        raise RuntimeError("点了「切换」但「切换店铺」弹窗没有弹出来，页面结构可能变了")

    target_row = page.locator(_MALL_SECTION).filter(has_text=mall_name)
    if target_row.count() == 0:
        raise RuntimeError(
            f"「切换店铺」弹窗里找不到名字是「{mall_name}」的店铺——检查一下账号设置里"
            "填的店铺名称是不是跟网页上显示的文字完全一致（包括大小写、空格）"
        )

    target_row.first.get_by_text(loose_text("切换")).first.click()
    wait_settle(page)

    new_current = read_current_mall_name(page)
    if new_current != mall_name:
        raise RuntimeError(
            f"点了切换到「{mall_name}」，但切换后页面显示的当前店铺还是「{new_current}」，"
            "切换可能没有生效"
        )
    logger.info(f"[mall] 切换成功，当前店铺已确认是「{mall_name}」")
