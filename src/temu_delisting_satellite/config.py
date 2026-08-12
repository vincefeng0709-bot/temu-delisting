"""分机端自己的本地设置：记住共享文件夹路径，以及自己提交过哪些任务
（等结果的时候要靠这份记录去共享文件夹里找对应的 result 文件）。

分机不需要账号管理、不需要 SQLite、不需要 Playwright——只是往共享文件夹
里丢一个 JSON 文件、之后回来看一眼有没有结果文件，所以这里的持久化也是
最简单的一个本地 JSON 文件，不跟主机那边的 data/ 混在一起。
"""
from __future__ import annotations

import json
import os
from dataclasses import asdict, dataclass, field
from pathlib import Path

from temu_delisting.paths import get_app_root


def _local_data_dir() -> Path:
    raw = os.getenv("SATELLITE_DATA_DIR", "data")
    path = Path(raw)
    path = path if path.is_absolute() else get_app_root() / path
    path.mkdir(parents=True, exist_ok=True)
    return path


def _config_path() -> Path:
    return _local_data_dir() / "satellite_config.json"


def _jobs_path() -> Path:
    return _local_data_dir() / "satellite_jobs.json"


@dataclass
class SatelliteConfig:
    root_dir: str = ""
    last_account_name: str = ""


def load_config() -> SatelliteConfig:
    path = _config_path()
    if not path.exists():
        return SatelliteConfig()
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return SatelliteConfig()
    defaults = asdict(SatelliteConfig())
    defaults.update({k: v for k, v in data.items() if k in defaults})
    return SatelliteConfig(**defaults)


def save_config(config: SatelliteConfig) -> None:
    _config_path().write_text(json.dumps(asdict(config), ensure_ascii=False, indent=2), encoding="utf-8")


@dataclass
class SubmittedJob:
    job_id: str
    account_name: str
    action: str
    start_date: str
    end_date: str
    submitted_at: str
    # 提交这个任务时用的共享文件夹路径——查结果要用这个，不是界面上当前
    # 输入框里的值（万一提交之后又改了路径但没保存，不能影响老任务查结果）。
    root_dir: str = ""
    # 还没查到结果之前是 None；查到之后把 result_<job_id>.json 的内容整个
    # 存进来，界面上直接显示，不用每次都重新去共享文件夹读。
    result: dict | None = field(default=None)


def load_job_history() -> list[SubmittedJob]:
    path = _jobs_path()
    if not path.exists():
        return []
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return []
    jobs = []
    for entry in data:
        try:
            jobs.append(SubmittedJob(**entry))
        except TypeError:
            continue  # 格式不对的条目跳过，不让一条坏数据搞垮整个历史列表
    return jobs


def save_job_history(jobs: list[SubmittedJob]) -> None:
    _jobs_path().write_text(
        json.dumps([asdict(job) for job in jobs], ensure_ascii=False, indent=2), encoding="utf-8"
    )
