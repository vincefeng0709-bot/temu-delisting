"""接口程序的本地设置：共享文件夹路径 + 是否开启监听，存在
data/remote_config.json 里。这是这台主机全局的一份设置，跟具体账号无关
（哪个账号能被远程触发，看的是共享文件夹底下有没有对应名字的子文件夹）。
"""
from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from pathlib import Path

from .accounts import data_root


@dataclass
class RemoteConfig:
    root_dir: str = ""
    enabled: bool = False
    poll_interval_seconds: int = 10


def _config_path() -> Path:
    return data_root() / "remote_config.json"


def load_remote_config() -> RemoteConfig:
    path = _config_path()
    if not path.exists():
        return RemoteConfig()
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return RemoteConfig()
    defaults = asdict(RemoteConfig())
    defaults.update({k: v for k, v in data.items() if k in defaults})
    return RemoteConfig(**defaults)


def save_remote_config(config: RemoteConfig) -> None:
    path = _config_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(asdict(config), ensure_ascii=False, indent=2), encoding="utf-8")
