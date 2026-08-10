"""登录态管理：storageState 复用 + 失效检测。

不做验证码/滑块自动绕过，也不在 Playwright 驱动的浏览器窗口里尝试登录 ——
实测 Temu 卖家中心会拦截自动化浏览器发起的登录（哪怕是人工手动输入账号密码），
提示"账号异常，无法登录"。所以登录这个动作必须在你平时正常使用的浏览器里
完成，然后用 `temu-delisting import-cookies` 把那个会话导入进来，Playwright
只负责复用已经登录好的状态，不碰登录本身。
"""
from __future__ import annotations

from playwright.sync_api import Page

from .config import Settings

LOGIN_URL_MARKERS = ("login", "passport")


def is_logged_in(page: Page, settings: Settings) -> bool:
    page.goto(settings.seller_url, wait_until="domcontentloaded")
    current_url = page.url.lower()
    return not any(marker in current_url for marker in LOGIN_URL_MARKERS)


def ensure_logged_in(page: Page, settings: Settings) -> None:
    """确保当前 page 处于已登录状态，否则报错并指引去导入 Cookie。"""
    if is_logged_in(page, settings):
        return

    raise RuntimeError(
        "\n[auth] 未检测到有效登录态（或已过期），且不会尝试在自动化浏览器里登录"
        "（会被风控拦截）。\n"
        "[auth] 请按以下步骤操作：\n"
        "  1. 在你平时正常使用的 Chrome 里登录 "
        f"{settings.seller_url}\n"
        "  2. 用 Cookie-Editor 之类的扩展导出该站点的 Cookie 为 JSON 文件\n"
        "  3. 运行: temu-delisting import-cookies <导出的json文件路径>\n"
        "  4. 重新运行本命令"
    )
