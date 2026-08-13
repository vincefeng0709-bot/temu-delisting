"""客服自助工具聊天窗口交互：发起下架申请 + 等待机器人确认回复。

选择器基于文档截图文案写的，还没有跟真实客服聊天窗口联调过，第一次实测
大概率还需要微调（尤其是这个站点常见"两字按钮中间插空格"的写法，已经
统一用 loose_text 兜底，但没实测过这几个具体按钮/文案）。
"""
from __future__ import annotations

import time
from dataclasses import dataclass

from playwright.sync_api import Page, TimeoutError as PlaywrightTimeoutError

from .logging_setup import get_logger
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

    点第一个按钮之后弹窗通常会整个关掉，第二个按钮的元素跟着从 DOM 里消失
    ——如果这时候还硬点它，Playwright 的可操作性检测会一直等它变得可点，
    等不到就抛超时异常，把这个当成"清理弹窗"这一步本身给搞崩了（调用方
    没接住这个异常的话，会连累这个 SKC 甚至整个 SPU 都处理失败，而日志里
    只会看到一句语焉不详的"点击失败"，看不出跟这个弹窗有关）。所以两个
    按钮的点击都要单独兜底，点不到就跳过，不能让"关弹窗"这个动作本身
    变成新的故障点。
    """
    already_processed = page.get_by_text(loose_text(ALREADY_PROCESSED_TEXT))
    if already_processed.count() == 0:
        return False

    logger = get_logger()
    for button_text in ("确认", "取消"):
        button = page.get_by_role("button", name=loose_text(button_text))
        if button.count() == 0:
            continue
        try:
            button.first.click(timeout=3000)
        except Exception as exc:  # noqa: BLE001 — 关弹窗这一步本身不能再抛出新异常
            logger.warning(f"[chat] 点「已处理成功」弹窗的「{button_text}」按钮失败（弹窗可能已经自己关了）：{exc}")
    return True


def open_chat_session(page: Page, timeout_ms: int = 10000) -> None:
    """点击右上角客服图标 -> 联系官方客服，进入真正的对话。

    每次导航到一个新页面（比如换了个 SPU）之后，只需要调用一次。同一个页面
    里处理这个 SPU 下的多个 SKC 时，聊天面板会一直开着 —— 千万不要每个 SKC
    都重新调用这个函数：客服图标是个"开关"，面板已经开着的话再点一次会把它
    关掉，反而导致后面找不到"自助工具"。
    """
    logger = get_logger()
    page.bring_to_front()
    page.locator('[class*="kefu_kefu__"]').first.click()
    logger.info("[chat] 已点击客服图标")

    # "联系官方客服"这个按钮不一定是标准 <button> 标签（这个站点很多按钮是
    # div/a 自己套样式），用文字匹配而不是 role="button"，避免角色识别不上
    contact_button = page.get_by_text(loose_text("联系官方客服"))
    try:
        contact_button.first.wait_for(timeout=timeout_ms)
        contact_button.first.click()
        logger.info("[chat] 已点击「联系官方客服」")
    except PlaywrightTimeoutError:
        logger.info("[chat] 没找到「联系官方客服」按钮，视为已经在对话里了")

    if dismiss_already_processed_alert(page):
        logger.info("[chat] 打开客服面板时清理了一个残留的「已处理成功」弹窗")


def trigger_delist_flow(
    page: Page,
    tool_wait_ms: int = 15000,
    pause_on_error: bool = False,
) -> None:
    """在已经打开的聊天面板里点"自助工具" -> "商品下架"。

    每个 SKC 都要调用一次，但不需要（也不应该）重新打开客服面板 ——
    面板会一直保持打开状态，直到换了个 SPU 页面刷新为止。
    """
    logger = get_logger()
    if dismiss_already_processed_alert(page):
        logger.info("[chat] 发起下架流程前清理了一个残留的「已处理成功」弹窗")

    self_service_tool = page.get_by_text(loose_text("自助工具"))
    try:
        self_service_tool.first.wait_for(timeout=tool_wait_ms)
    except PlaywrightTimeoutError:
        logger.error(f"[chat] 等待「自助工具」超过 {tool_wait_ms}ms 仍未出现")
        if not pause_on_error:
            raise
        page.pause()  # 冻结在卡住的现场，检查完手动点 Resume 后重试一次
        self_service_tool.first.wait_for(timeout=tool_wait_ms)

    self_service_tool.first.click()
    page.get_by_text(loose_text("商品下架")).first.click()
    logger.info("[chat] 已点击「自助工具」->「商品下架」")


def wait_for_send_product_prompt(page: Page, timeout_ms: int) -> None:
    """等待客服回复"发商品"提示，再点击。"""
    logger = get_logger()
    send_product = page.get_by_text(loose_text("发商品"))
    try:
        send_product.first.wait_for(timeout=timeout_ms)
    except PlaywrightTimeoutError:
        logger.error(f"[chat] 等待客服回复「发商品」提示超过 {timeout_ms}ms 仍未出现")
        raise
    send_product.first.click()
    logger.info("[chat] 客服已回复「发商品」，已点击")


def submit_delist_request(page: Page, skc_id: str, delist_reason: str, dry_run: bool = False) -> None:
    """在"发送下架商品信息"表单里填 SKC ID + 下架原因，点击申请下架。

    dry_run=True 时只填表单，不点最终的"申请下架"按钮 —— 用来验证前面
    流程走对了，不会真的提交。

    实测发现"已处理成功"这个残留弹窗经常正好在这个表单打开之后才冒出来
    （盖在表单上面），不是只在 trigger_delist_flow 那个更早的检查点——
    这里再检查一次，不然弹窗会挡住"申请下架"按钮，点击一直等不到它变成
    可点状态，最后超时报一个看不出跟这个弹窗有关的模糊错误。
    """
    if dismiss_already_processed_alert(page):
        get_logger().info(f"[chat] SKC {skc_id} 打开下架表单时清理了一个残留的「已处理成功」弹窗")

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

    # 填表单这几步之间也可能冒出弹窗（盖在"申请下架"按钮上面），点之前
    # 再兜底检查一次，不然点击会一直等按钮变可点，等到超时才报错。
    if dismiss_already_processed_alert(page):
        get_logger().info(f"[chat] SKC {skc_id} 点「申请下架」前清理了一个残留的「已处理成功」弹窗")

    dialog.get_by_role("button", name=loose_text("申请下架")).click()
    get_logger().info(f"[chat] 已提交下架申请：SKC {skc_id}，原因「{delist_reason}」")


def count_delist_replies(page: Page, skc_id: str) -> int:
    """数一下聊天记录里目前已经有几条这个 SKC 的结论性回复。

    在提交下架申请之前先调一次记下"起点"，等回复时只认"比起点多出来的"，
    避免把聊天历史里这个 SKC 更早以前（甚至是本工具第一次接入前、人工
    客服时代留下）的旧回复误判成这次申请的回复——客服对话是跟账号绑定在
    服务端的，重开窗口/换个 SPU 都不会清空，旧记录会一直留在滚动条里。
    """
    return page.get_by_text(f"【SKC ID: {skc_id}】").count()


def wait_for_delist_confirmation(
    page: Page, skc_id: str, timeout_ms: int, baseline_reply_count: int = 0
) -> ChatResult:
    """轮询聊天记录，直到客服给出针对这个 SKC 的**新**结论性回复，或超时。

    客服的结论性回复不是只有"该商品已下架"这一种说法——还见过"该商品还未
    发布到任何站点，暂时无法操作下架"这类其他结论。这些回复格式统一是
    "【SKC ID: xxx】：您好，..."开头，不管具体结论是什么。之前只认"已下架"
    这一个关键字，遇到其他结论时明明客服已经回复了，代码却识别不出来，只能
    干等到超时，处理多个 SKC 时白白浪费很多时间。现在改成：只要出现这个
    SKC 的结论性回复就立刻停止等待，再看回复内容里有没有"已下架"来判断
    是成功还是失败。

    baseline_reply_count 是提交申请前 count_delist_replies() 的结果——只有
    数量比这个起点多，才认为是这次申请的新回复，不会被聊天历史里同一个
    SKC 更早以前的旧回复误判成"刚刚已经处理完了"。

    另外还要识别"该商品已在您的上次咨询后处理成功"这种重复申请提示弹窗
    （不是聊天气泡，是残留没关掉的弹窗），这个也算成功。
    """
    logger = get_logger()
    reply_marker = f"【SKC ID: {skc_id}】"
    reply_locator = page.get_by_text(reply_marker)
    logger.info(f"[chat] 开始等待 SKC {skc_id} 的结论性回复，起点回复数={baseline_reply_count}")

    deadline = time.monotonic() + timeout_ms / 1000
    while time.monotonic() < deadline:
        if dismiss_already_processed_alert(page):
            logger.info(f"[chat] SKC {skc_id} 弹出「已处理成功」提示，视为下架成功")
            return ChatResult(
                status="success", detail=f"重复申请：{ALREADY_PROCESSED_TEXT}（视为已下架成功）"
            )

        current_count = reply_locator.count()
        if current_count > baseline_reply_count:
            full_text = reply_locator.last.locator("xpath=ancestor::*[self::div][1]").inner_text()
            logger.info(
                f"[chat] SKC {skc_id} 收到新回复（回复数 {baseline_reply_count}->{current_count}）："
                f"{full_text[:80]}"
            )
            if any(keyword in full_text for keyword in DELISTED_KEYWORDS):
                return ChatResult(status="success", detail=full_text)
            return ChatResult(status="failed", detail=full_text)

        page.wait_for_timeout(1000)

    final_count = reply_locator.count()
    logger.error(
        f"[chat] SKC {skc_id} 等待 {timeout_ms}ms 超时——起点回复数={baseline_reply_count}，"
        f"超时时回复数={final_count}"
        + ("（数量没变，客服可能确实没回复）" if final_count <= baseline_reply_count else
           "（数量其实变了，但没被 count()>baseline 判定出来，选择器/时机可能有问题，需要复查）")
    )
    return ChatResult(status="timeout_needs_human", detail="等待客服确认回复超时")
