import pytest

from temu_delisting_satellite.config import (
    SatelliteConfig,
    SubmittedJob,
    load_config,
    load_job_history,
    save_config,
    save_job_history,
)


@pytest.fixture
def data_dir(tmp_path, monkeypatch):
    monkeypatch.setenv("SATELLITE_DATA_DIR", str(tmp_path))
    return tmp_path


def test_load_config_defaults_when_missing(data_dir):
    assert load_config() == SatelliteConfig()


def test_save_and_reload_config(data_dir):
    save_config(SatelliteConfig(root_dir=r"\\host\share", last_account_name="SaveNest"))

    config = load_config()

    assert config.root_dir == r"\\host\share"
    assert config.last_account_name == "SaveNest"


def test_load_config_ignores_malformed_json(data_dir):
    (data_dir / "satellite_config.json").write_text("not valid json", encoding="utf-8")
    assert load_config() == SatelliteConfig()


def test_load_job_history_empty_when_missing(data_dir):
    assert load_job_history() == []


def test_save_and_reload_job_history_round_trips(data_dir):
    job = SubmittedJob(
        job_id="job1",
        account_name="SaveNest",
        action="scan",
        start_date="2026-08-01",
        end_date="2026-08-11",
        submitted_at="2026-08-11 10:00:00",
        root_dir=r"\\host\share",
    )
    save_job_history([job])

    jobs = load_job_history()

    assert len(jobs) == 1
    assert jobs[0].job_id == "job1"
    assert jobs[0].result is None


def test_save_and_reload_job_history_preserves_result(data_dir):
    job = SubmittedJob(
        job_id="job1",
        account_name="SaveNest",
        action="scan",
        start_date="2026-08-01",
        end_date="2026-08-11",
        submitted_at="2026-08-11 10:00:00",
        root_dir=r"\\host\share",
        result={"status": "completed", "raw_row_count": 3},
    )
    save_job_history([job])

    jobs = load_job_history()

    assert jobs[0].result == {"status": "completed", "raw_row_count": 3}


def test_load_job_history_skips_malformed_entries(data_dir):
    (data_dir / "satellite_jobs.json").write_text('[{"unexpected_field": true}]', encoding="utf-8")
    assert load_job_history() == []
