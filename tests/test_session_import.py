import json

from temu_delisting.session_import import convert_cookie_editor_export, import_cookies

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
