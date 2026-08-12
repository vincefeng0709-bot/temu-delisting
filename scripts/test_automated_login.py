"""诊断脚本：验证 Temu 卖家中心是否会拦截"自动化浏览器发起的登录"这个动作
本身——就算账号密码是人工在这个窗口里手动输入的（不是脚本自动填的），
也会被拦截吗？这个脚本只负责打开窗口、暂停、事后检查结果，全程不读取、
不存储任何密码。

用法：
    python scripts/test_automated_login.py

运行后会打开一个 Playwright 控制的 Chrome 窗口，停在登录页，同时弹出一个
Playwright Inspector 调试面板（脚本在这里暂停等你）。你在浏览器窗口里
正常手动登录，登录完成后回到 Inspector 面板点一下"Resume"（左上角的
播放按钮）继续，脚本会自动检查当前页面状态，把结果打印出来。
"""
from __future__ import annotations

from playwright.sync_api import sync_playwright

LOGIN_URL = "https://seller.kuajingmaihuo.com"


def main() -> None:
    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=False, channel="chrome")
        context = browser.new_context()
        page = context.new_page()
        page.goto(LOGIN_URL)

        print("=" * 60)
        print("浏览器已打开，停在登录页。")
        print("请在这个窗口里正常手动登录（账号密码由你自己输入，脚本不会碰）。")
        print("登录完成后，在弹出的 Playwright Inspector 面板里点「Resume」继续。")
        print("=" * 60)
        page.pause()

        current_url = page.url
        try:
            page_text = page.inner_text("body")
        except Exception:
            page_text = ""

        print(f"\n继续执行后，当前页面地址：{current_url}")
        if "账号异常" in page_text or "无法登录" in page_text:
            print("结果：页面上出现了异常提示文字，登录被拦截了。")
        elif any(marker in current_url.lower() for marker in ("login", "passport", "settle")):
            print("结果：还停在登录相关页面，登录大概率没成功（或者被拦截后没跳转）。")
        else:
            print("结果：页面已经跳转离开登录页，看起来登录成功了。")

        print("\n再暂停一次，方便你自己肉眼确认页面状态，看完手动点 Resume 结束脚本。")
        page.pause()
        browser.close()


if __name__ == "__main__":
    main()
