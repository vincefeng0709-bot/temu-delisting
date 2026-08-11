"""Playwright 浏览器/上下文封装。"""
from __future__ import annotations

from contextlib import contextmanager
from pathlib import Path
from typing import Iterator

from playwright.sync_api import (
    BrowserContext,
    Page,
    Playwright,
    TimeoutError as PlaywrightTimeoutError,
    sync_playwright,
)

from .config import Settings


def wait_settle(page: Page, timeout_ms: int = 8000) -> None:
    """等页面"网络安静下来"，但不当成硬性条件——很多页面背后有轮询/心跳类的
    后台请求，网络永远不会真正"安静"，用 wait_for_load_state("networkidle")
    卡死等满默认的30秒直接超时报错是常见坑。这里给一个短一些的等待窗口，
    超时了就直接放行继续（大概率该加载的内容已经加载完了），不整个流程
    崩掉。"""
    try:
        page.wait_for_load_state("networkidle", timeout=timeout_ms)
    except PlaywrightTimeoutError:
        pass


@contextmanager
def launch_context(settings: Settings, pw: Playwright) -> Iterator[BrowserContext]:
    launch_kwargs = {"headless": settings.headless}
    if settings.browser_channel:
        launch_kwargs["channel"] = settings.browser_channel
    if settings.slow_mo_ms:
        launch_kwargs["slow_mo"] = settings.slow_mo_ms
    browser = pw.chromium.launch(**launch_kwargs)
    storage_state = (
        str(settings.storage_state_path) if settings.storage_state_path.exists() else None
    )
    context = browser.new_context(storage_state=storage_state)
    try:
        yield context
    finally:
        context.close()
        browser.close()


@contextmanager
def open_page(settings: Settings) -> Iterator[Page]:
    with sync_playwright() as pw:
        with launch_context(settings, pw) as context:
            page = context.new_page()
            try:
                yield page
            finally:
                settings.storage_state_path.parent.mkdir(parents=True, exist_ok=True)
                context.storage_state(path=str(settings.storage_state_path))
