from temu_delisting_gui.errors import friendly_message


def test_login_expired_maps_to_relogin_hint():
    exc = RuntimeError("未检测到有效登录态（或已过期），且不会尝试在自动化浏览器里登录")
    assert "添加账号" in friendly_message(exc)


def test_chrome_missing_maps_to_install_hint():
    exc = RuntimeError("BrowserType.launch: Executable doesn't exist at ...")
    assert "安装 Google Chrome" in friendly_message(exc)


def test_timeout_error_maps_to_retry_hint():
    exc = TimeoutError("Locator.click: Timeout 30000ms exceeded.")
    assert "超时" in friendly_message(exc)


def test_unknown_error_falls_back_to_generic_message():
    exc = ValueError("some totally unexpected internal error")
    message = friendly_message(exc)
    assert "日志文件" in message
    assert "ValueError" not in message  # 不暴露具体异常类型/堆栈
