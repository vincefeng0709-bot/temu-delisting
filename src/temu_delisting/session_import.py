"""把从真实（非自动化）Chrome 里导出的 Cookie，转换成 Playwright 的
storage_state.json 格式，这样 Playwright 就完全不用去驱动登录这个动作，
只需要加载一个已经登录好的会话。

导出方式推荐用 "Cookie-Editor" 这个浏览器扩展。注意登录会话分别落在
seller.kuajingmaihuo.com 和 agentseller.temu.com 两个域名下的 Cookie 里，
两个页面都要导出、都要导入（import_cookies 是合并写入，不会互相覆盖）：
1. 在 seller.kuajingmaihuo.com 页面导出一次，导入一次
2. 进入实际控制台（agentseller.temu.com）后再导出一次，再导入一次
"""
from __future__ import annotations

import json
from pathlib import Path

_SAME_SITE_MAP = {
    "strict": "Strict",
    "lax": "Lax",
    "no_restriction": "None",
    "none": "None",
    "unspecified": "Lax",
}


def _convert_cookie(raw: dict) -> dict:
    same_site_raw = str(raw.get("sameSite", "unspecified")).lower()
    same_site = _SAME_SITE_MAP.get(same_site_raw, "Lax")

    expires = raw.get("expirationDate")
    if raw.get("session") or expires is None:
        expires = -1

    domain = raw["domain"]
    # Playwright 要求非 hostOnly 的 cookie domain 以 "." 开头，跟 Cookie-Editor
    # 的 hostOnly=false 语义一致；hostOnly=true 时保持原样。
    if raw.get("hostOnly") is False and not domain.startswith("."):
        domain = "." + domain

    secure = bool(raw.get("secure", False))
    if same_site == "None" and not secure:
        # 浏览器规范要求 SameSite=None 的 cookie 必须是 secure，否则 Playwright 会拒绝加载
        secure = True

    return {
        "name": raw["name"],
        "value": raw["value"],
        "domain": domain,
        "path": raw.get("path", "/"),
        "expires": expires,
        "httpOnly": bool(raw.get("httpOnly", False)),
        "secure": secure,
        "sameSite": same_site,
    }


def convert_cookie_editor_export_text(cookie_editor_json_text: str) -> dict:
    """核心解析逻辑：接受 Cookie-Editor "Export as JSON" 的原始文本（不管是从
    文件读出来的还是用户直接粘贴的），转成 Playwright storage_state 格式。"""
    try:
        raw_cookies = json.loads(cookie_editor_json_text)
    except json.JSONDecodeError as exc:
        raise ValueError(
            "这段内容不是合法的 JSON，请确认是从 Cookie-Editor 的 'Export as JSON' "
            "复制出来的完整内容。"
        ) from exc

    if isinstance(raw_cookies, dict) and "cookies" in raw_cookies:
        raw_cookies = raw_cookies["cookies"]

    if not isinstance(raw_cookies, list):
        raise ValueError(
            "无法识别的 Cookie 导出格式，期望是一个 Cookie 对象数组"
            "（Cookie-Editor 的 'Export as JSON' 就是这个格式）。"
        )

    cookies = [_convert_cookie(c) for c in raw_cookies]
    return {"cookies": cookies, "origins": []}


def convert_cookie_editor_export(cookie_editor_json_path: Path) -> dict:
    with open(cookie_editor_json_path, "r", encoding="utf-8") as f:
        return convert_cookie_editor_export_text(f.read())


def _load_existing(storage_state_path: Path) -> dict:
    if not storage_state_path.exists():
        return {"cookies": [], "origins": []}
    with open(storage_state_path, "r", encoding="utf-8") as f:
        return json.load(f)


def merge_cookie_states(existing: dict, new: dict) -> dict:
    """按 name+domain+path 去重合并两份 storage_state（新的覆盖同名旧的），
    而不是整个覆盖 —— 这样可以分几次合并不同域名（比如 seller.kuajingmaihuo.com
    和 agentseller.temu.com）导出的 Cookie，不会互相丢失。纯内存操作，不碰磁盘
    ——GUI 登录向导用这个在完成前先把两次粘贴的内容攒在内存里。
    """
    merged: dict[tuple[str, str, str], dict] = {
        (c["name"], c["domain"], c["path"]): c for c in existing.get("cookies", [])
    }
    for c in new.get("cookies", []):
        merged[(c["name"], c["domain"], c["path"])] = c
    return {"cookies": list(merged.values()), "origins": existing.get("origins", [])}


def write_storage_state(state: dict, storage_state_path: Path) -> None:
    storage_state_path.parent.mkdir(parents=True, exist_ok=True)
    with open(storage_state_path, "w", encoding="utf-8") as f:
        json.dump(state, f, ensure_ascii=False, indent=2)


def import_cookies_text(cookie_editor_json_text: str, storage_state_path: Path) -> int:
    """把新导出的 Cookie（文本形式，GUI 粘贴框直接用这个）合并进已有的
    storage_state.json 并立即写盘。CLI 用这个；GUI 登录向导为了避免"没点完成
    就取消导致半成品账号"，改用 merge_cookie_states + write_storage_state
    自己控制何时落盘。
    """
    new_state = convert_cookie_editor_export_text(cookie_editor_json_text)
    existing_state = _load_existing(storage_state_path)
    result = merge_cookie_states(existing_state, new_state)
    write_storage_state(result, storage_state_path)
    return len(result["cookies"])


def import_cookies(cookie_editor_json_path: Path, storage_state_path: Path) -> int:
    """CLI 用：从文件路径导入（内部就是读文件文本再调 import_cookies_text）。"""
    with open(cookie_editor_json_path, "r", encoding="utf-8") as f:
        return import_cookies_text(f.read(), storage_state_path)
