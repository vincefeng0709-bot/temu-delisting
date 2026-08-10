import json

import pytest

from temu_delisting.session_import import (
    convert_cookie_editor_export,
    convert_cookie_editor_export_text,
    import_cookies,
    import_cookies_text,
    merge_cookie_states,
    write_storage_state,
)

SAMPLE = [
    {
        "domain": ".kuajingmaihuo.com",
        "expirationDate": 1999999999,
        "hostOnly": False,
        "httpOnly": True,
        "name": "sid",
        "path": "/",
        "sameSite": "lax",
        "secure": True,
        "session": False,
        "value": "abc123",
    },
    {
        "domain": "seller.kuajingmaihuo.com",
        "hostOnly": True,
        "httpOnly": False,
        "name": "csrf",
        "path": "/",
        "sameSite": "no_restriction",
        "secure": False,
        "session": True,
        "value": "xyz789",
    },
]


def test_converts_basic_fields(tmp_path):
    src = tmp_path / "cookies.json"
    src.write_text(json.dumps(SAMPLE), encoding="utf-8")

    result = convert_cookie_editor_export(src)
    cookies = {c["name"]: c for c in result["cookies"]}

    assert cookies["sid"]["value"] == "abc123"
    assert cookies["sid"]["domain"] == ".kuajingmaihuo.com"
    assert cookies["sid"]["sameSite"] == "Lax"
    assert cookies["sid"]["expires"] == 1999999999


def test_host_only_domain_not_prefixed(tmp_path):
    src = tmp_path / "cookies.json"
    src.write_text(json.dumps(SAMPLE), encoding="utf-8")

    result = convert_cookie_editor_export(src)
    cookies = {c["name"]: c for c in result["cookies"]}

    assert cookies["csrf"]["domain"] == "seller.kuajingmaihuo.com"


def test_session_cookie_gets_expires_minus_one(tmp_path):
    src = tmp_path / "cookies.json"
    src.write_text(json.dumps(SAMPLE), encoding="utf-8")

    result = convert_cookie_editor_export(src)
    cookies = {c["name"]: c for c in result["cookies"]}

    assert cookies["csrf"]["expires"] == -1


def test_samesite_none_forces_secure(tmp_path):
    src = tmp_path / "cookies.json"
    src.write_text(json.dumps(SAMPLE), encoding="utf-8")

    result = convert_cookie_editor_export(src)
    cookies = {c["name"]: c for c in result["cookies"]}

    assert cookies["csrf"]["sameSite"] == "None"
    assert cookies["csrf"]["secure"] is True


def test_import_merges_across_two_domains_without_losing_either(tmp_path):
    first_domain_cookies = [
        {
            "domain": ".kuajingmaihuo.com",
            "hostOnly": False,
            "httpOnly": True,
            "name": "sid",
            "path": "/",
            "sameSite": "lax",
            "secure": True,
            "session": False,
            "expirationDate": 1999999999,
            "value": "seller-session",
        }
    ]
    second_domain_cookies = [
        {
            "domain": ".temu.com",
            "hostOnly": False,
            "httpOnly": True,
            "name": "agent_sid",
            "path": "/",
            "sameSite": "lax",
            "secure": True,
            "session": False,
            "expirationDate": 1999999999,
            "value": "agentseller-session",
        }
    ]

    src1 = tmp_path / "cookies1.json"
    src1.write_text(json.dumps(first_domain_cookies), encoding="utf-8")
    src2 = tmp_path / "cookies2.json"
    src2.write_text(json.dumps(second_domain_cookies), encoding="utf-8")

    storage_state_path = tmp_path / "storage_state.json"
    import_cookies(src1, storage_state_path)
    count = import_cookies(src2, storage_state_path)

    result = json.loads(storage_state_path.read_text(encoding="utf-8"))
    names = {c["name"] for c in result["cookies"]}

    assert count == 2
    assert names == {"sid", "agent_sid"}


def test_convert_from_text_matches_file_based(tmp_path):
    text = json.dumps(SAMPLE)
    result = convert_cookie_editor_export_text(text)
    cookies = {c["name"]: c for c in result["cookies"]}
    assert cookies["sid"]["value"] == "abc123"


def test_convert_from_text_rejects_non_json_with_friendly_message():
    with pytest.raises(ValueError, match="不是合法的 JSON"):
        convert_cookie_editor_export_text("this is not json")


def test_import_cookies_text_writes_storage_state(tmp_path):
    storage_state_path = tmp_path / "storage_state.json"
    count = import_cookies_text(json.dumps(SAMPLE), storage_state_path)
    assert count == 2
    assert storage_state_path.exists()


def test_merge_cookie_states_is_pure_in_memory(tmp_path):
    """登录向导用这个：解析两段粘贴文本，内存里合并，最后才一次性落盘。"""
    state_a = convert_cookie_editor_export_text(
        json.dumps([{**SAMPLE[0], "name": "sid"}])
    )
    state_b = convert_cookie_editor_export_text(
        json.dumps([{**SAMPLE[0], "name": "agent_sid", "value": "second"}])
    )

    merged = merge_cookie_states(state_a, state_b)
    names = {c["name"] for c in merged["cookies"]}

    assert names == {"sid", "agent_sid"}
    storage_state_path = tmp_path / "storage_state.json"
    assert not storage_state_path.exists()  # 还没写盘

    write_storage_state(merged, storage_state_path)
    assert storage_state_path.exists()
    on_disk = json.loads(storage_state_path.read_text(encoding="utf-8"))
    assert {c["name"] for c in on_disk["cookies"]} == {"sid", "agent_sid"}
