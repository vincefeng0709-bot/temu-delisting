import json
from pathlib import Path

import pytest

from temu_delisting import remote_jobs


def test_scan_pending_requests_finds_unprocessed_job(tmp_path):
    remote_jobs.write_request(tmp_path, "SaveNest", "job1", "scan", "2026-08-01", "2026-08-11")

    pending = remote_jobs.scan_pending_requests(tmp_path, ["SaveNest"])

    assert len(pending) == 1
    assert pending[0].job_id == "job1"
    assert pending[0].account_name == "SaveNest"
    assert pending[0].action == "scan"
    assert pending[0].start_date == "2026-08-01"
    assert pending[0].end_date == "2026-08-11"


def test_scan_pending_requests_skips_already_completed_job(tmp_path):
    remote_jobs.write_request(tmp_path, "SaveNest", "job1", "scan", "2026-08-01", "2026-08-11")
    remote_jobs.write_result(tmp_path, "SaveNest", "job1", {"status": "completed"})

    pending = remote_jobs.scan_pending_requests(tmp_path, ["SaveNest"])

    assert pending == []


def test_scan_pending_requests_ignores_unknown_account_folder(tmp_path):
    remote_jobs.write_request(tmp_path, "拼错的名字", "job1", "scan", "2026-08-01", "2026-08-11")

    pending = remote_jobs.scan_pending_requests(tmp_path, ["SaveNest"])

    assert pending == []


def test_scan_pending_requests_ignores_malformed_json(tmp_path):
    account_dir = tmp_path / "SaveNest"
    account_dir.mkdir()
    (account_dir / "request_bad.json").write_text("not valid json", encoding="utf-8")

    pending = remote_jobs.scan_pending_requests(tmp_path, ["SaveNest"])

    assert pending == []


def test_scan_pending_requests_ignores_invalid_action(tmp_path):
    account_dir = tmp_path / "SaveNest"
    account_dir.mkdir()
    (account_dir / "request_job1.json").write_text(
        json.dumps({"action": "delete_everything", "start_date": "2026-08-01", "end_date": "2026-08-11"}),
        encoding="utf-8",
    )

    pending = remote_jobs.scan_pending_requests(tmp_path, ["SaveNest"])

    assert pending == []


def test_scan_pending_requests_missing_root_dir_returns_empty(tmp_path):
    missing = tmp_path / "does-not-exist"

    assert remote_jobs.scan_pending_requests(missing, ["SaveNest"]) == []


def test_write_result_creates_file_with_job_id_and_timestamp(tmp_path):
    path = remote_jobs.write_result(tmp_path, "SaveNest", "job1", {"status": "completed", "raw_row_count": 5})

    assert path.exists()
    data = json.loads(path.read_text(encoding="utf-8"))
    assert data["job_id"] == "job1"
    assert data["status"] == "completed"
    assert data["raw_row_count"] == 5
    assert "completed_at" in data


def test_write_request_rejects_unknown_action(tmp_path):
    with pytest.raises(ValueError):
        remote_jobs.write_request(tmp_path, "SaveNest", "job1", "not_a_real_action", "2026-08-01", "2026-08-11")


def test_read_result_returns_none_when_not_yet_processed(tmp_path):
    remote_jobs.write_request(tmp_path, "SaveNest", "job1", "scan", "2026-08-01", "2026-08-11")

    assert remote_jobs.read_result(tmp_path, "SaveNest", "job1") is None


def test_read_result_returns_written_result(tmp_path):
    remote_jobs.write_result(tmp_path, "SaveNest", "job1", {"status": "completed", "raw_row_count": 5})

    result = remote_jobs.read_result(tmp_path, "SaveNest", "job1")

    assert result["status"] == "completed"
    assert result["raw_row_count"] == 5


def test_read_result_returns_none_for_malformed_file(tmp_path):
    account_dir = tmp_path / "SaveNest"
    account_dir.mkdir()
    (account_dir / "result_job1.json").write_text("not valid json", encoding="utf-8")

    assert remote_jobs.read_result(tmp_path, "SaveNest", "job1") is None


def test_list_account_folders_returns_sorted_subfolder_names(tmp_path):
    (tmp_path / "SaveNest").mkdir()
    (tmp_path / "Dwmane Shop").mkdir()
    (tmp_path / "not_a_folder.txt").write_text("x", encoding="utf-8")

    assert remote_jobs.list_account_folders(tmp_path) == ["Dwmane Shop", "SaveNest"]


def test_list_account_folders_missing_root_returns_empty(tmp_path):
    missing = tmp_path / "does-not-exist"
    assert remote_jobs.list_account_folders(missing) == []


def _make_request(job_id, account_name="SaveNest", submitted_at=""):
    return remote_jobs.JobRequest(
        job_id=job_id,
        account_name=account_name,
        action="scan",
        start_date="2026-08-01",
        end_date="2026-08-11",
        request_path=Path(f"/fake/{account_name}/request_{job_id}.json"),
        submitted_at=submitted_at,
    )


def test_prune_queue_order_drops_no_longer_pending_ids():
    pending = [_make_request("job1"), _make_request("job2")]
    saved_order = ["job0", "job1", "job2", "job3"]

    assert remote_jobs.prune_queue_order(saved_order, pending) == ["job1", "job2"]


def test_select_next_jobs_respects_manual_order():
    pending = [
        _make_request("job1", "AccountA", submitted_at="2026-08-11T10:00:00"),
        _make_request("job2", "AccountB", submitted_at="2026-08-11T09:00:00"),
    ]
    # job2 提交更早，但手动顺序把 job1 排在前面，应该优先选 job1
    selected = remote_jobs.select_next_jobs(pending, queue_order=["job1", "job2"], busy_account_names=set(), available_slots=1)
    assert [r.job_id for r in selected] == ["job1"]


def test_select_next_jobs_falls_back_to_submitted_at_when_not_in_manual_order():
    pending = [
        _make_request("job1", "AccountA", submitted_at="2026-08-11T10:00:00"),
        _make_request("job2", "AccountB", submitted_at="2026-08-11T09:00:00"),
    ]
    selected = remote_jobs.select_next_jobs(pending, queue_order=[], busy_account_names=set(), available_slots=2)
    assert [r.job_id for r in selected] == ["job2", "job1"]


def test_select_next_jobs_skips_busy_accounts():
    pending = [_make_request("job1", "AccountA"), _make_request("job2", "AccountB")]
    selected = remote_jobs.select_next_jobs(
        pending, queue_order=[], busy_account_names={"AccountA"}, available_slots=2
    )
    assert [r.job_id for r in selected] == ["job2"]


def test_select_next_jobs_respects_available_slots_cap():
    pending = [_make_request("job1", "AccountA"), _make_request("job2", "AccountB")]
    selected = remote_jobs.select_next_jobs(pending, queue_order=[], busy_account_names=set(), available_slots=1)
    assert len(selected) == 1


def test_select_next_jobs_zero_slots_returns_empty():
    pending = [_make_request("job1")]
    assert remote_jobs.select_next_jobs(pending, queue_order=[], busy_account_names=set(), available_slots=0) == []


def test_select_next_jobs_does_not_pick_same_account_twice_in_one_batch():
    pending = [_make_request("job1", "AccountA"), _make_request("job2", "AccountA")]
    selected = remote_jobs.select_next_jobs(pending, queue_order=[], busy_account_names=set(), available_slots=2)
    assert len(selected) == 1
