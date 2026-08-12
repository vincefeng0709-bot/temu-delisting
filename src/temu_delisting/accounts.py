"""多账号管理：每个 Temu 账号/店铺的数据（登录态、SQLite、导出、日志）互相隔离，
放在各自的 data/accounts/<account_id>/ 目录下。

CLI 不需要关心账号概念——不传 account_id 时自动使用/创建一个"默认账号"，
行为跟以前的单账号版本一致。GUI 那边才会用到真正的多账号切换。
"""
from __future__ import annotations

import json
import os
import re
import shutil
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from .paths import get_app_root

DEFAULT_ACCOUNT_ID = "default"
DEFAULT_ACCOUNT_NAME = "默认账号"


def _data_root() -> Path:
    raw = os.getenv("DATA_ROOT", "data")
    path = Path(raw)
    return path if path.is_absolute() else get_app_root() / path


def data_root() -> Path:
    """给其他模块（比如接口程序的本地设置）复用同一份 data 根目录计算逻辑，
    不用各自重新算一遍打包前/打包后的路径差异。"""
    return _data_root()


def _registry_path() -> Path:
    return _data_root() / "accounts.json"


@dataclass
class Account:
    id: str
    display_name: str
    created_at: str
    # 有的 Temu 登录下挂了不止一个店铺（同一套 Cookie 能访问多个"店铺"），
    # 网站自己记的"当前激活的是哪个店铺"是服务端会话状态，不是单纯靠 Cookie
    # 就能决定的——必须在页面上显式点一次"切换"才会生效。这个字段记录这个
    # "账号"条目具体要绑定网页上显示的哪个店铺名字（必须跟页面上的文字
    # 完全一致，因为要靠文字去匹配、点击对应的切换按钮）。留空表示不做
    # 校验/切换（老账号、或者本来就只有一个店铺的情况）。
    mall_name: str = ""
    # 自由文本备注，批量导入账号清单时用来记一下这个店铺来自哪个手机号/
    # 那个手机号底下一共有几个店铺，方便事后核对——不是自动化要用的字段，
    # 纯粹给人看。
    notes: str = ""
    # 持久化 Chrome 配置目录的分组 id——同一个 Temu 登录下的多个店铺账号
    # 共用同一个 profile_id，指向同一份 Chrome 用户配置目录（真实登录态，
    # 不是 Cookie 快照），任何一个店铺刷新登录，其余共用的店铺自动跟着生效。
    # 空字符串表示这个账号还没迁移到新方案，继续走老的 storage_state.json
    # 快照方式（向后兼容，不会强迫老账号立刻迁移）。
    profile_id: str = ""


@dataclass
class AccountPaths:
    root: Path
    db_path: Path
    storage_state_path: Path
    exports_dir: Path
    log_dir: Path


def _slugify(display_name: str) -> str:
    slug = re.sub(r"[^a-zA-Z0-9一-鿿]+", "-", display_name).strip("-")
    return slug or "account"


def _load_registry() -> list[dict]:
    path = _registry_path()
    if not path.exists():
        return []
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def _save_registry(entries: list[dict]) -> None:
    path = _registry_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(entries, f, ensure_ascii=False, indent=2)


def _migrate_flat_layout_if_needed() -> None:
    """老版本是扁平的 data/app.db、data/storage_state.json 这种单账号结构，
    第一次在这种环境跑多账号版本时，把老数据搬进"默认账号"目录里，不丢数据。"""
    data_root = _data_root()
    registry_path = _registry_path()
    if registry_path.exists():
        return  # 已经是新结构，不用迁移

    legacy_db = data_root / "app.db"
    legacy_storage_state = data_root / "storage_state.json"
    legacy_exports = data_root / "exports"
    legacy_logs = data_root / "logs"
    has_legacy_data = legacy_db.exists() or legacy_storage_state.exists()

    if not has_legacy_data:
        _save_registry([])
        return

    default_dir = data_root / "accounts" / DEFAULT_ACCOUNT_ID
    default_dir.mkdir(parents=True, exist_ok=True)

    if legacy_db.exists():
        legacy_db.rename(default_dir / "app.db")
    if legacy_storage_state.exists():
        legacy_storage_state.rename(default_dir / "storage_state.json")
    if legacy_exports.exists():
        (default_dir / "exports").mkdir(exist_ok=True)
        for item in legacy_exports.iterdir():
            item.rename(default_dir / "exports" / item.name)
    if legacy_logs.exists():
        (default_dir / "logs").mkdir(exist_ok=True)
        for item in legacy_logs.iterdir():
            item.rename(default_dir / "logs" / item.name)

    _save_registry(
        [
            {
                "id": DEFAULT_ACCOUNT_ID,
                "display_name": DEFAULT_ACCOUNT_NAME,
                "created_at": datetime.now(timezone.utc).isoformat(),
            }
        ]
    )


def list_accounts() -> list[Account]:
    _migrate_flat_layout_if_needed()
    return [Account(**entry) for entry in _load_registry()]


def get_account(account_id: str) -> Account | None:
    for entry in _load_registry():
        if entry["id"] == account_id:
            return Account(**entry)
    return None


def get_account_by_name(display_name: str) -> Account | None:
    """接口程序用：分机丢过来的任务文件是按账号「显示名称」分文件夹的，
    不知道 account_id，得靠名字反查。名字要求跟账号管理页里完全一致
    （大小写、空格都算），重名的话返回第一个匹配上的。"""
    for entry in _load_registry():
        if entry["display_name"] == display_name:
            return Account(**entry)
    return None


def create_account(
    display_name: str, mall_name: str = "", notes: str = "", profile_id: str = ""
) -> Account:
    _migrate_flat_layout_if_needed()
    entries = _load_registry()

    base_id = _slugify(display_name)
    existing_ids = {e["id"] for e in entries}
    account_id = base_id
    if account_id in existing_ids:
        account_id = f"{base_id}-{uuid.uuid4().hex[:6]}"

    account = Account(
        id=account_id,
        display_name=display_name,
        created_at=datetime.now(timezone.utc).isoformat(),
        mall_name=mall_name,
        notes=notes,
        profile_id=profile_id,
    )
    entries.append(
        {
            "id": account.id,
            "display_name": account.display_name,
            "created_at": account.created_at,
            "mall_name": account.mall_name,
            "notes": account.notes,
            "profile_id": account.profile_id,
        }
    )
    _save_registry(entries)
    account_paths(account.id)  # 提前建好目录
    return account


def rename_account(account_id: str, new_display_name: str) -> Account:
    """只改显示名字，account_id 和数据目录都不变（目录是按 id 建的，跟
    显示名字无关，改名不会动到任何登录态/数据库文件）。"""
    entries = _load_registry()
    for entry in entries:
        if entry["id"] == account_id:
            entry["display_name"] = new_display_name
            _save_registry(entries)
            return Account(**entry)
    raise ValueError(f"找不到账号 {account_id}")


def set_mall_name(account_id: str, mall_name: str) -> Account:
    """设置/修改这个账号绑定的店铺名称（自动切换用），留空表示不做校验/切换。"""
    entries = _load_registry()
    for entry in entries:
        if entry["id"] == account_id:
            entry["mall_name"] = mall_name
            _save_registry(entries)
            return Account(**entry)
    raise ValueError(f"找不到账号 {account_id}")


def set_notes(account_id: str, notes: str) -> Account:
    """设置/修改这个账号的备注文字（纯展示用，不影响自动化）。"""
    entries = _load_registry()
    for entry in entries:
        if entry["id"] == account_id:
            entry["notes"] = notes
            _save_registry(entries)
            return Account(**entry)
    raise ValueError(f"找不到账号 {account_id}")


def set_profile_id(account_id: str, profile_id: str) -> Account:
    """设置/修改这个账号绑定的 Chrome 配置分组 id。"""
    entries = _load_registry()
    for entry in entries:
        if entry["id"] == account_id:
            entry["profile_id"] = profile_id
            _save_registry(entries)
            return Account(**entry)
    raise ValueError(f"找不到账号 {account_id}")


def chrome_profile_dir(profile_id: str) -> Path:
    """持久化 Chrome 配置目录的路径——按 profile_id 分组，不是按 account_id，
    同一登录下的多个店铺账号会解析到同一个目录。"""
    path = _data_root() / "chrome_profiles" / profile_id
    path.mkdir(parents=True, exist_ok=True)
    return path


def delete_account(account_id: str) -> None:
    """从注册表里移除，并把这个账号的数据目录（登录态/数据库/导出/日志）
    一起删掉——这是本地文件删除，不会影响 Temu 账号本身。调用方（GUI）
    自己负责在删之前跟用户确认。"""
    entries = _load_registry()
    remaining = [e for e in entries if e["id"] != account_id]
    if len(remaining) == len(entries):
        raise ValueError(f"找不到账号 {account_id}")
    _save_registry(remaining)

    account_dir = _data_root() / "accounts" / account_id
    if account_dir.exists():
        shutil.rmtree(account_dir)


def ensure_default_account() -> Account:
    """给 CLI 用：不关心账号概念时，自动拿到（或建一个）默认账号。"""
    _migrate_flat_layout_if_needed()
    entries = _load_registry()
    if not entries:
        entries = [
            {
                "id": DEFAULT_ACCOUNT_ID,
                "display_name": DEFAULT_ACCOUNT_NAME,
                "created_at": datetime.now(timezone.utc).isoformat(),
            }
        ]
        _save_registry(entries)
    account_paths(entries[0]["id"])
    return Account(**entries[0])


def account_paths(account_id: str) -> AccountPaths:
    root = _data_root() / "accounts" / account_id
    exports_dir = root / "exports"
    log_dir = root / "logs"
    root.mkdir(parents=True, exist_ok=True)
    exports_dir.mkdir(parents=True, exist_ok=True)
    log_dir.mkdir(parents=True, exist_ok=True)
    return AccountPaths(
        root=root,
        db_path=root / "app.db",
        storage_state_path=root / "storage_state.json",
        exports_dir=exports_dir,
        log_dir=log_dir,
    )
