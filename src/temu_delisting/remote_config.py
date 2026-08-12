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
    # 同时最多处理几个远程任务——默认 1，也就是不管有几个账号同时提交，
    # 主机这边一次只跑一个，按排队顺序一个一个来（先求稳，观察效果之后
    # 再考虑要不要调大，同时开多个 Chrome 窗口跑）。
    max_concurrent_remote_jobs: int = 1


def _config_path() -> Path:
    return data_root() / "remote_config.json"


def _queue_order_path() -> Path:
    return data_root() / "remote_queue_order.json"


def load_queue_order() -> list[str]:
    """主机手动调整过的远程任务排队顺序（一份 job_id 列表）。文件不存在
    或者内容坏了都当成"还没手动调整过"，返回空列表——排队就按提交时间
    从早到晚来。"""
    path = _queue_order_path()
    if not path.exists():
        return []
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return []
    if not isinstance(data, list):
        return []
    return [str(item) for item in data]


def save_queue_order(order: list[str]) -> None:
    _queue_order_path().write_text(json.dumps(order, ensure_ascii=False, indent=2), encoding="utf-8")


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
