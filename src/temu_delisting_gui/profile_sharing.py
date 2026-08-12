"""「复制账号」新建账号、和「更新登录信息」时改成共用别的账号的登录信息，
这两个地方要用的是同一段逻辑：把"来源账号"的登录信息解析成一个可以直接
复用的 profile_id——如果来源账号已经是新方案（有 profile_id）直接返回；
如果还是老的 storage_state.json 方案，先迁移成新方案再返回，两边都能
受益，不用以后来源账号自己也要单独迁移一次。
"""
from __future__ import annotations

import uuid

from temu_delisting import accounts
from temu_delisting.browser import migrate_storage_state_into_profile
from temu_delisting.config import load_settings


def account_has_login(account: accounts.Account) -> bool:
    if account.profile_id:
        profile_dir = accounts.chrome_profile_dir(account.profile_id)
        if profile_dir.exists() and any(profile_dir.iterdir()):
            return True
    return accounts.account_paths(account.id).storage_state_path.exists()


def resolve_shared_profile_id(source_account_id: str) -> str:
    """返回来源账号可以共用的 profile_id，需要的话顺带把它从老方案迁移成
    新方案。来源账号完全没有登录信息时抛 ValueError，调用方负责转成用户
    能看懂的提示。"""
    source_account = accounts.get_account(source_account_id)
    if source_account is None:
        raise ValueError("找不到这个账号")

    if source_account.profile_id:
        return source_account.profile_id

    settings = load_settings(account_id=source_account_id)
    if not settings.storage_state_path.exists():
        raise ValueError("选中的这个账号还没有登录信息，没法共用")

    profile_id = uuid.uuid4().hex
    profile_dir = accounts.chrome_profile_dir(profile_id)
    migrate_storage_state_into_profile(settings.storage_state_path, profile_dir, settings)
    accounts.set_profile_id(source_account_id, profile_id)
    return profile_id
