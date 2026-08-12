import json

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
