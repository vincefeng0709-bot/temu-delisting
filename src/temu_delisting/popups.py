"""处理"上新生命周期管理"等页面上不定时弹出的营销/提效弹窗，跟下架流程本身
无关，但会挡住后续点击，需要先清掉。

已知的两种：
- "您的商品可调价提效"：有"确认提交"和"稍后再说"两个按钮，要点"稍后再说"，
  绝不能点"确认提交"（会真的改价格）。
- "店铺提效，促进生意"：批量调价弹窗，只有右上角一个关闭按钮，用 Esc 关掉，
  绝不能点"确认提交本页"（会真的提交调价）。
"""
from __future__ import annotations

from playwright.sync_api import Page, TimeoutError as PlaywrightTimeoutError

from .text_match import loose_text


def dismiss_known_popups(page: Page, timeout_ms: int = 3000) -> None:
    _dismiss_later_button(page, timeout_ms)
    _dismiss_efficiency_modal(page, timeout_ms)


def _dismiss_later_button(page: Page, timeout_ms: int) -> None:
    try:
        later_button = page.get_by_text(loose_text("稍后再说"))
        later_button.first.wait_for(timeout=timeout_ms)
        later_button.first.click()
    except PlaywrightTimeoutError:
        pass


def _dismiss_efficiency_modal(page: Page, timeout_ms: int) -> None:
    try:
        marker = page.get_by_text(loose_text("店铺提效"))
        marker.first.wait_for(timeout=timeout_ms)
        page.keyboard.press("Escape")
    except PlaywrightTimeoutError:
        pass
