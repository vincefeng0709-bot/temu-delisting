"""Playwright 浏览器/上下文封装。"""
from __future__ import annotations

from contextlib import contextmanager
from pathlib import Path
from typing import Iterator

from playwright.sync_api import BrowserContext, Page, Playwright, sync_playwright

from .config import Settings


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
