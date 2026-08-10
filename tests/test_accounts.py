import json

import pytest

from temu_delisting import accounts


@pytest.fixture
def data_root(tmp_path, monkeypatch):
    monkeypatch.setenv("DATA_ROOT", str(tmp_path))
    return tmp_path


def test_ensure_default_account_on_fresh_install(data_root):
    account = accounts.ensure_default_account()
    assert account.id == accounts.DEFAULT_ACCOUNT_ID
    assert account.display_name == accounts.DEFAULT_ACCOUNT_NAME
    assert (data_root / "accounts.json").exists()


def test_create_account_assigns_unique_slug(data_root):
    a = accounts.create_account("SaveNest 美国站")
    b = accounts.create_account("SaveNest 美国站")  # 重名
    assert a.id != b.id
    assert a.id.startswith("SaveNest")


def test_list_accounts_reflects_created_accounts(data_root):
    accounts.create_account("店铺A")
    accounts.create_account("店铺B")
    names = {a.display_name for a in accounts.list_accounts()}
    assert names == {"店铺A", "店铺B"}


def test_account_paths_creates_isolated_directories(data_root):
    a = accounts.create_account("店铺A")
    b = accounts.create_account("店铺B")
    paths_a = accounts.account_paths(a.id)
    paths_b = accounts.account_paths(b.id)

    assert paths_a.db_path != paths_b.db_path
    assert paths_a.root.exists()
    assert paths_a.exports_dir.exists()
    assert paths_a.log_dir.exists()


def test_migrates_legacy_flat_layout_into_default_account(data_root):
    (data_root / "app.db").write_text("legacy-db")
    (data_root / "storage_state.json").write_text("{}")
    (data_root / "exports").mkdir()
    (data_root / "exports" / "old_batch.csv").write_text("id,spu_id\n")

    account = accounts.ensure_default_account()
    paths = accounts.account_paths(account.id)

    assert paths.db_path.read_text() == "legacy-db"
    assert (paths.exports_dir / "old_batch.csv").exists()
    assert not (data_root / "app.db").exists()


def test_get_account_returns_none_for_unknown_id(data_root):
    assert accounts.get_account("nope") is None
