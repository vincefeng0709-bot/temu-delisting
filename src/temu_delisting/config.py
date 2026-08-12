"""加载 .env 环境变量、config/violation_types.yaml，以及按账号解析出的数据路径。"""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

import yaml
from dotenv import load_dotenv

from . import accounts
from .paths import get_app_root


@dataclass
class Settings:
    account_id: str
    mall_name: str
    seller_url: str
    username: str
    password: str
    headless: bool
    browser_channel: str
    slow_mo_ms: int
    db_path: Path
    storage_state_path: Path
    exports_dir: Path
    log_dir: Path
    # 非空表示这个账号已经迁移到"持久化 Chrome 配置目录"方案，browser.py
    # 会用这个目录复用真实登录态，不再依赖 storage_state_path 那份快照。
    chrome_profile_dir: Path | None
    chat_timeout_seconds: int
    chat_cooldown_seconds: int
    known_delist_types: list[str] = field(default_factory=list)
    delist_reasons: list[str] = field(default_factory=list)


def load_settings(env_file: str | Path | None = None, account_id: str | None = None) -> Settings:
    """account_id 不传时自动使用/创建"默认账号"，CLI 不需要关心多账号概念——
    这是给 GUI 那边真正做账号切换用的参数。"""
    app_root = get_app_root()
    load_dotenv(dotenv_path=env_file or (app_root / ".env"))

    violation_config_path = app_root / "config" / "violation_types.yaml"
    with open(violation_config_path, "r", encoding="utf-8") as f:
        violation_config = yaml.safe_load(f) or {}

    if account_id is None:
        account_id = accounts.ensure_default_account().id
    paths = accounts.account_paths(account_id)
    account = accounts.get_account(account_id)
    mall_name = account.mall_name if account else ""
    chrome_profile_dir = (
        accounts.chrome_profile_dir(account.profile_id) if account and account.profile_id else None
    )

    return Settings(
        account_id=account_id,
        mall_name=mall_name,
        seller_url=os.getenv("TEMU_SELLER_URL", "https://seller.kuajingmaihuo.com"),
        username=os.getenv("TEMU_USERNAME", ""),
        password=os.getenv("TEMU_PASSWORD", ""),
        headless=os.getenv("HEADLESS", "false").strip().lower() in {"1", "true", "yes"},
        browser_channel=os.getenv("BROWSER_CHANNEL", "chrome").strip(),
        # 默认给个小的保险停顿，不是 0——这个站点好几处 UI（日历弹窗关闭、
        # 客服面板）本身有动画/异步状态更新，操作间完全没有停顿容易踩时序
        # 坑。打包成 exe 的场景不会有 .env，全靠这个默认值兜底。
        slow_mo_ms=int(os.getenv("SLOW_MO_MS", "150")),
        db_path=paths.db_path,
        storage_state_path=paths.storage_state_path,
        exports_dir=paths.exports_dir,
        log_dir=paths.log_dir,
        chrome_profile_dir=chrome_profile_dir,
        # 客服"结论性回复"现在靠 wait_for_delist_confirmation 里更宽松的
        # 匹配规则（不再只认"已下架"这一种说法）。实测发现客服回复经常要
        # 超过 15 秒，调太短会导致大量本来会成功的 SKC 被误判成"需要人工
        # 跟进"，事后还要去后台核实——这里按同事的明确要求调成 4 秒，属于
        # "宁可多标一些需要人工确认，也要跑得快"的取舍，不是能自动兼顾的。
        chat_timeout_seconds=int(os.getenv("CHAT_TIMEOUT_SECONDS", "4")),
        chat_cooldown_seconds=int(os.getenv("CHAT_COOLDOWN_SECONDS", "4")),
        known_delist_types=violation_config.get("known_delist_types", []),
        delist_reasons=violation_config.get("delist_reasons", []),
    )
