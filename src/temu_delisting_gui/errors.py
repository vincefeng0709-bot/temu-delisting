"""已知异常 → 人话中文提示。GUI 侧统一走这里，绝不在界面上直接甩 Python
堆栈。完整堆栈始终照常写进日志文件（调用方在 except 块里自己负责调
get_logger().exception()，这个函数只负责"给用户看的那句话"）。
"""
from __future__ import annotations


def friendly_message(exc: BaseException) -> str:
    text = str(exc)
    type_name = type(exc).__name__

    if "未检测到有效登录态" in text or "登录态已失效" in text:
        return "登录已过期，请点「添加账号」重新走一遍登录流程，导入最新的登录信息。"

    if "BrowserType.launch" in text or "Executable doesn't exist" in text:
        return "未检测到 Chrome 浏览器，请先安装 Google Chrome 后重试。"

    if type_name == "TimeoutError" or "Timeout" in text:
        return "页面响应超时，可能是网络不稳定或系统繁忙，请稍后重试；如果多次都超时，请联系管理员。"

    if "strict mode violation" in text or "waiting for" in text:
        return "页面结构好像发生了变化，自动化脚本可能需要更新，请联系管理员。"

    return "程序遇到问题，已记录到日志文件，请联系管理员并附上日志文件。"
