"""客服自助工具聊天窗口交互：发起下架申请 + 等待机器人确认回复。

选择器基于文档截图文案写的，还没有跟真实客服聊天窗口联调过，第一次实测
大概率还需要微调（尤其是这个站点常见"两字按钮中间插空格"的写法，已经
统一用 loose_text 兜底，但没实测过这几个具体按钮/文案）。
"""
from __future__ import annotations

import time
from dataclasses import dataclass

from playwright.sync_api import Page, TimeoutError as PlaywrightTimeoutError

from .text_match import loose_text

DELISTED_KEYWORDS = ("已下架",)
# 重复申请同一个 SKC（比如之前已经真实下架成功过）时，客服会弹一个提示弹窗，
# 而不是走正常的"已下架"聊天回复，要单独识别，否则会被当成超时失败
ALREADY_PROCESSED_TEXT = "已在您的上次咨询后处理成功"


@dataclass
class ChatResult:
    status: str          # success | timeout_needs_human
    detail: str


def dismiss_already_processed_alert(page: Page) -> bool:
    """客服对话是跟账号绑定在服务端的，不是跟浏览器窗口绑定 —— 哪怕重开一个
    新浏览器，只要连上客服还是接着显示上一次遗留、没关掉的提示弹窗（比如
    "该商品已在您的上次咨询后处理成功"）。这类残留弹窗会挡住后面所有点击，
    每次开始处理一个新 SKC 之前都要先检查一下有没有这种残留，有就关掉。
    返回 True 表示确实清理了一个残留弹窗。
    """
    already_processed = page.get_by_text(loose_text(ALREADY_PROCESSED_TEXT))
    if already_processed.count() == 0:
        return False

    confirm_button = page.get_by_role("button", name=loose_text("确认"))
    if confirm_button.count():
        confirm_button.first.click()
    cancel_button = page.get_by_role("button", name=loose_text("取消"))
    if cancel_button.count():
        cancel_button.first.click()
    return True


def open_chat_session(page: Page, timeout_ms: int = 10000) -> None:
    """点击右上角客服图标 -> 联系官方客服，进入真正的对话。

    每次导航到一个新页面（比如换了个 SPU）之后，只需要调用一次。同一个页面
    里处理这个 SPU 下的多个 SKC 时，聊天面板会一直开着 —— 千万不要每个 SKC
    都重新调用这个函数：客服图标是个"开关"，面板已经开着的话再点一次会把它
    关掉，反而导致后面找不到"自助工具"。
    """
    page.bring_to_front()
    page.locator('[class*="kefu_kefu__"]').first.click()

    # "联系官方客服"这个按钮不一定是标准 <button> 标签（这个站点很多按钮是
    # div/a 自己套样式），用文字匹配而不是 role="button"，避免角色识别不上
    contact_button = page.get_by_text(loose_text("联系官方客服"))
    try:
        contact_button.first.wait_for(timeout=timeout_ms)
        contact_button.first.click()
    except PlaywrightTimeoutError:
        pass  # 可能已经在对话里了

    dismiss_already_processed_alert(page)


def trigger_delist_flow(
    page: Page,
    tool_wait_ms: int = 15000,
    pause_on_error: bool = False,
) -> None:
    """在已经打开的聊天面板里点"自助工具" -> "商品下架"。

    每个 SKC 都要调用一次，但不需要（也不应该）重新打开客服面板 ——
    面板会一直保持打开状态，直到换了个 SPU 页面刷新为止。
    """
    dismiss_already_processed_alert(page)

    self_service_tool = page.get_by_text(loose_text("自助工具"))
    try:
        self_service_tool.first.wait_for(timeout=tool_wait_ms)
    except PlaywrightTimeoutError:
        if not pause_on_error:
            raise
        page.pause()  # 冻结在卡住的现场，检查完手动点 Resume 后重试一次
        self_service_tool.first.wait_for(timeout=tool_wait_ms)

    self_service_tool.first.click()
    page.get_by_text(loose_text("商品下架")).first.click()


def wait_for_send_product_prompt(page: Page, timeout_ms: int) -> None:
    """等待客服回复"发商品"提示，再点击。"""
    send_product = page.get_by_text(loose_text("发商品"))
    send_product.first.wait_for(timeout=timeout_ms)
    send_product.first.click()


def submit_delist_request(page: Page, skc_id: str, delist_reason: str, dry_run: bool = False) -> None:
    """在"发送下架商品信息"表单里填 SKC ID + 下架原因，点击申请下架。

    dry_run=True 时只填表单，不点最终的"申请下架"按钮 —— 用来验证前面
    流程走对了，不会真的提交。
    """
    dialog = page.get_by_text("发送下架商品信息").locator("xpath=ancestor::*[self::div][1]")

    id_input = dialog.get_by_placeholder("请输入完整SKC ID")
    id_input.fill(skc_id)

    # "下架原因"是官方表单组件（beast-core-form-item），标签文字和下拉框中间
    # 隔了好几层 Grid 布局，不能简单"往上一层"，改成往上找最近一个带
    # data-testid="beast-core-form-item" 的祖先节点，不用猜层数
    reason_row = dialog.get_by_text(loose_text("下架原因")).first.locator(
        'xpath=ancestor::*[@data-testid="beast-core-form-item"][1]'
    )
    reason_row.locator('[data-testid="beast-core-select-header"]').click()

    # 下拉选项是浮层，通常插在页面最后；聊天记录里可能已经留有同样文字的历史
    # 消息（比如上一个 SKC 也选过"业务调整下架"），所以取"最后一个匹配"而不是
    # "第一个"，降低点到历史消息而不是新弹出选项的风险
    page.get_by_text(loose_text(delist_reason)).last.click()

    if dry_run:
        return

    dialog.get_by_role("button", name=loose_text("申请下架")).click()


def wait_for_delist_confirmation(page: Page, skc_id: str, timeout_ms: int) -> ChatResult:
    """轮询聊天记录，直到出现下架确认，或超时。

    两种"成功"信号都要识别：
    1. 正常情况：聊天记录里出现包含该 SKC ID 和"已下架"关键字的回复
    2. 重复申请：这个 SKC 之前已经真实处理成功过，客服会弹一个
       "该商品已在您的上次咨询后处理成功"的提示弹窗（不是聊天气泡），
       这也算成功，要把弹窗关掉（点"确认"）避免挡住后面的操作
    """
    delisted_confirmation = page.get_by_text(skc_id).locator(
        f"xpath=ancestor::*[self::div][1]//*[contains(text(), '{DELISTED_KEYWORDS[0]}')]"
    )

    deadline = time.monotonic() + timeout_ms / 1000
    while time.monotonic() < deadline:
        if dismiss_already_processed_alert(page):
            return ChatResult(
                status="success", detail=f"重复申请：{ALREADY_PROCESSED_TEXT}（视为已下架成功）"
            )
        if delisted_confirmation.count() > 0:
            text = delisted_confirmation.first.inner_text()
            return ChatResult(status="success", detail=text)
        page.wait_for_timeout(1000)

    return ChatResult(status="timeout_needs_human", detail="等待客服确认回复超时")
