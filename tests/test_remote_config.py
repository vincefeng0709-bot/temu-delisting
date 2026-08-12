import pytest

from temu_delisting.remote_config import RemoteConfig, load_remote_config, save_remote_config


@pytest.fixture
def data_root(tmp_path, monkeypatch):
    monkeypatch.setenv("DATA_ROOT", str(tmp_path))
    return tmp_path


def test_load_remote_config_defaults_when_missing(data_root):
    config = load_remote_config()
    assert config == RemoteConfig()


def test_save_and_reload_remote_config(data_root):
    save_remote_config(RemoteConfig(root_dir=r"\\host\share\temu-jobs", enabled=True))

    config = load_remote_config()

    assert config.root_dir == r"\\host\share\temu-jobs"
    assert config.enabled is True


def test_load_remote_config_ignores_malformed_json(data_root):
    (data_root / "remote_config.json").write_text("not valid json", encoding="utf-8")
    assert load_remote_config() == RemoteConfig()


def test_load_remote_config_ignores_unknown_keys(data_root):
    (data_root / "remote_config.json").write_text(
        '{"root_dir": "D:\\\\jobs", "enabled": true, "unknown_field": "x"}', encoding="utf-8"
    )
    config = load_remote_config()
    assert config.root_dir == "D:\\jobs"
    assert config.enabled is True
