""""专属登录窗口"方案：用系统直接拉起的真实 Chrome 进程（完全不经过
Playwright/CDP）打开一个独立的用户配置目录，供人工手动登录一次；之后
自动化用 Playwright 的 launch_persistent_context 复用这同一个配置目录，
不再需要 Cookie-Editor 导出/粘贴那一套。

关键点，之前专门写脚本实测过（见 scripts/test_automated_login.py）：
只要浏览器是 Playwright 启动的——不管是 pw.chromium.launch() 还是
launch_persistent_context()，也不管跑的是 Playwright 自带内核还是
channel="chrome" 的真实 Chrome——Temu 都会在**登录**这一步直接拦截，
提示"账号异常，无法登录"，哪怕账号密码是人工手动敲的。这不是"用了哪种
浏览器内核"的问题，是 Chrome 在被 CDP/自动化协议控制时会暴露特征，
Temu 检测的是这个。所以登录这个动作必须彻底脱离 Playwright，用
subprocess 直接拉起系统里装的 Chrome.exe，不能用 pw.chromium.launch*
任何一个变体。登录完之后，Playwright 接手复用这个配置目录去跑扫描/
下架不受影响——Temu 从来没在"登录之后的自动化操作"这一步拦过我们，
只拦"登录"本身。
"""
from __future__ import annotations

import subprocess
import winreg
from pathlib import Path

LOGIN_URL = "https://seller.kuajingmaihuo.com"

_CHROME_CANDIDATES = [
    r"C:\Program Files\Google\Chrome\Application\chrome.exe",
    r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
]


def find_chrome_executable() -> str | None:
    for candidate in _CHROME_CANDIDATES:
        if Path(candidate).exists():
            return candidate

    try:
        with winreg.OpenKey(
            winreg.HKEY_LOCAL_MACHINE,
            r"SOFTWARE\Microsoft\Windows\CurrentVersion\App Paths\chrome.exe",
        ) as key:
            path, _ = winreg.QueryValueEx(key, None)
            if path and Path(path).exists():
                return path
    except OSError:
        pass

    return None


def open_login_window(profile_dir: Path, url: str = LOGIN_URL) -> subprocess.Popen:
    """用系统直接启动一个独立配置目录的真实 Chrome 窗口，供人工手动登录。
    不经过 Playwright，Temu 看到的就是一个完全正常的 Chrome 实例。"""
    chrome_path = find_chrome_executable()
    if chrome_path is None:
        raise RuntimeError("没有找到系统安装的 Chrome，请先安装 Google Chrome 正式版。")

    profile_dir.mkdir(parents=True, exist_ok=True)
    return subprocess.Popen([chrome_path, f"--user-data-dir={profile_dir}", "--new-window", url])
