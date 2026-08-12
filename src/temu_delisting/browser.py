"""Playwright 浏览器/上下文封装。"""
from __future__ import annotations

from contextlib import contextmanager
from datetime import datetime, timezone
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
from .logging_setup import get_logger

# 实测确认这两个才是真正的会话令牌（其余 Cookie 都是长期有效的追踪/指纹类，
# 不是登录会不会掉线的关键）。二者的 expirationDate 几乎总是同时落在导出
# 那一刻起大约 24 小时后，"seller_temp" 这个名字本身也印证了这是临时令牌。
# 这里每次运行前后都记一下这两个令牌的过期时间——用于验证一个还没确认的
# 猜测：正常使用会不会让服务端悄悄把这个令牌"续期"（如果会，定期跑一次
# 轻量操作就能一直不掉线；如果不会，说明是服务端写死的硬性 24 小时上限，
# 没法绕开，只能接受每天要重新导入 Cookie）。这只是诊断用的探测记录，
# 不影响正常流程，读不到就跳过，不报错。
_TRACKED_SESSION_COOKIES = {
    "seller_temp": "agentseller.temu.com",
    "SUB_PASS_ID": "seller.kuajingmaihuo.com",
}


def _log_session_token_status(context: BrowserContext, when: str) -> None:
    logger = get_logger()
    try:
        cookies = context.cookies()
    except Exception:  # noqa: BLE001 — 纯诊断用途，任何异常都不该影响正常流程
        return

    for cookie in cookies:
        expected_domain = _TRACKED_SESSION_COOKIES.get(cookie.get("name", ""))
        if expected_domain is None or expected_domain not in cookie.get("domain", ""):
            continue
        expires = cookie.get("expires")
        if not expires or expires <= 0:
            continue
        expires_str = datetime.fromtimestamp(expires, tz=timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
        logger.info(f"[保活探测] {when}：{cookie['name']} 过期时间 = {expires_str}")


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
            _log_session_token_status(context, "本次运行开始时")
            page = context.new_page()
            try:
                yield page
            finally:
                _log_session_token_status(context, "本次运行结束时")
                settings.storage_state_path.parent.mkdir(parents=True, exist_ok=True)
                context.storage_state(path=str(settings.storage_state_path))
