"""局域网"接口程序"用的共享文件夹任务约定。

分机上跑的独立小程序（后续单独交付，不在这个模块里）往共享根目录下对应
账号的子文件夹里丢一个 request_<任务ID>.json；主机这边（跑完整自动化
程序的这台机器）定时扫描这些子文件夹，找到还没处理过的请求就自动执行，
执行完把 result_<任务ID>.json 写回同一个文件夹，分机那边去看结果。

目录结构：
<共享根目录>/
  <账号显示名称>/
    request_<job_id>.json   分机丢进来的任务请求
    result_<job_id>.json    主机处理完写回的结果

账号显示名称必须跟主机这边账号管理页里的名字完全一致——文件夹名字对不
上号的账号（分机拼错名字、或者这个账号还没在主机建过）会被直接跳过，
不会瞎猜是哪个账号。
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

REQUEST_PREFIX = "request_"
RESULT_PREFIX = "result_"

ACTION_SCAN = "scan"
ACTION_SCAN_AND_APPLY = "scan_and_apply"
VALID_ACTIONS = {ACTION_SCAN, ACTION_SCAN_AND_APPLY}


@dataclass
class JobRequest:
    job_id: str
    account_name: str
    action: str  # "scan" | "scan_and_apply"
    start_date: str
    end_date: str
    request_path: Path
    submitted_by: str = ""
    submitted_at: str = ""


def scan_pending_requests(root_dir: Path, account_names: list[str]) -> list[JobRequest]:
    """扫描共享根目录下每个账号子文件夹，找出还没处理过的请求文件（有
    request_ 但是没有对应的 result_，说明还没处理）。"""
    if not root_dir.exists():
        return []

    pending: list[JobRequest] = []
    for account_name in account_names:
        account_dir = root_dir / account_name
        if not account_dir.is_dir():
            continue

        for request_file in sorted(account_dir.glob(f"{REQUEST_PREFIX}*.json")):
            job_id = request_file.stem[len(REQUEST_PREFIX):]
            if not job_id:
                continue
            result_file = account_dir / f"{RESULT_PREFIX}{job_id}.json"
            if result_file.exists():
                continue  # 已经处理过了

            try:
                data = json.loads(request_file.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                continue

            action = data.get("action")
            start_date = data.get("start_date", "")
            end_date = data.get("end_date", "")
            if action not in VALID_ACTIONS or not start_date or not end_date:
                continue

            pending.append(
                JobRequest(
                    job_id=job_id,
                    account_name=account_name,
                    action=action,
                    start_date=start_date,
                    end_date=end_date,
                    request_path=request_file,
                    submitted_by=str(data.get("submitted_by", "")),
                    submitted_at=str(data.get("submitted_at", "")),
                )
            )
    return pending


def prune_queue_order(saved_order: list[str], pending: list[JobRequest]) -> list[str]:
    """主机这边手动排过的队列顺序，每轮轮询前先把已经跑完/已经开始跑的
    任务 ID 从这份顺序里摘掉——只保留"还在排队、还没轮到"的那些，不然这
    份顺序文件会越攒越长，混进一堆早就处理完的死数据。"""
    pending_ids = {request.job_id for request in pending}
    return [job_id for job_id in saved_order if job_id in pending_ids]


def select_next_jobs(
    pending: list[JobRequest],
    queue_order: list[str],
    busy_account_names: set[str],
    available_slots: int,
) -> list[JobRequest]:
    """按排队顺序（主机手动调整过的优先按那个来，没手动调整过的按提交时间
    从早到晚）挑出接下来最多 available_slots 个可以马上开始跑的任务——
    账号已经在忙的先跳过，留着排队，不占并发名额；同一轮里选中的账号也要
    立刻算"忙"，避免同一个账号在这一轮里被选中两次。"""
    if available_slots <= 0:
        return []

    order_index = {job_id: i for i, job_id in enumerate(queue_order)}
    ordered = sorted(pending, key=lambda r: (order_index.get(r.job_id, len(queue_order)), r.submitted_at))

    busy = set(busy_account_names)
    selected: list[JobRequest] = []
    for request in ordered:
        if request.account_name in busy:
            continue
        selected.append(request)
        busy.add(request.account_name)
        if len(selected) >= available_slots:
            break
    return selected


def read_result(root_dir: Path, account_name: str, job_id: str) -> dict | None:
    """分机那边用来查自己提交的任务跑完了没有。文件不存在（还没处理完）
    或者内容损坏，都返回 None，不抛异常——分机会定时重新来看一眼。"""
    result_path = root_dir / account_name / f"{RESULT_PREFIX}{job_id}.json"
    if not result_path.exists():
        return None
    try:
        return json.loads(result_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None


def list_account_folders(root_dir: Path) -> list[str]:
    """分机那边用来列出共享文件夹下面已经建好的账号子文件夹名字，给操作
    人员一个下拉框选，而不是让他手打账号名字（打错字就会被主机那边直接
    跳过，参考本文件顶部的说明）。"""
    if not root_dir.exists():
        return []
    return sorted(p.name for p in root_dir.iterdir() if p.is_dir())


def write_result(root_dir: Path, account_name: str, job_id: str, result: dict) -> Path:
    account_dir = root_dir / account_name
    account_dir.mkdir(parents=True, exist_ok=True)
    result_path = account_dir / f"{RESULT_PREFIX}{job_id}.json"
    payload = {**result, "job_id": job_id, "completed_at": datetime.now(timezone.utc).isoformat()}
    result_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return result_path


def write_request(
    root_dir: Path,
    account_name: str,
    job_id: str,
    action: str,
    start_date: str,
    end_date: str,
    submitted_by: str = "",
) -> Path:
    """分机那边的接口程序会用这个（这里先提供，给后续单独交付的分机小
    程序调用，也方便手动测试）。"""
    if action not in VALID_ACTIONS:
        raise ValueError(f"未知的操作类型：{action}，只能是 {sorted(VALID_ACTIONS)}")

    account_dir = root_dir / account_name
    account_dir.mkdir(parents=True, exist_ok=True)
    request_path = account_dir / f"{REQUEST_PREFIX}{job_id}.json"
    payload = {
        "action": action,
        "start_date": start_date,
        "end_date": end_date,
        "submitted_by": submitted_by,
        "submitted_at": datetime.now(timezone.utc).isoformat(),
    }
    request_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return request_path
