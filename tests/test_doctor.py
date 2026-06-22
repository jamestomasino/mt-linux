from pathlib import Path

from mt_linux.config import AppConfig
from mt_linux.doctor import CheckResult, run_doctor, summarize_results


def test_summarize_results_counts_statuses():
    ok, warn, fail = summarize_results(
        [
            CheckResult("a", "ok", ""),
            CheckResult("b", "warn", ""),
            CheckResult("c", "fail", ""),
        ]
    )
    assert (ok, warn, fail) == (1, 1, 1)


def test_run_doctor_reports_missing_runtime_bits(tmp_path: Path, monkeypatch):
    config = AppConfig()
    config.output.folder = str(tmp_path / "out")
    config.speakers.db_path = str(tmp_path / "speakers.json")
    config.calendar.backend = "caldav"
    config.calendar.caldav_url = ""

    monkeypatch.setattr("mt_linux.doctor.shutil.which", lambda cmd: None)
    monkeypatch.setattr("mt_linux.doctor.importlib.util.find_spec", lambda name: None)
    monkeypatch.setattr("mt_linux.doctor.cuda_available", lambda: False)

    results = run_doctor(config)
    by_name = {item.name: item for item in results}
    assert by_name["audio.recorder"].status == "fail"
    assert by_name["calendar.caldav_url"].status == "warn"
    assert by_name["output.folder"].status == "ok"
    assert by_name["transcription.device"].status == "ok"
    assert by_name["diarization.device"].detail == "cpu"


def test_run_doctor_warns_when_cuda_available_but_transcription_pinned_to_cpu(tmp_path: Path, monkeypatch):
    config = AppConfig()
    config.output.folder = str(tmp_path / "out")
    config.speakers.db_path = str(tmp_path / "speakers.json")
    config.transcription.device = "cpu"

    monkeypatch.setattr("mt_linux.doctor.shutil.which", lambda cmd: None)
    monkeypatch.setattr("mt_linux.doctor.importlib.util.find_spec", lambda name: object())
    monkeypatch.setattr("mt_linux.doctor.cuda_available", lambda: True)

    results = run_doctor(config)
    by_name = {item.name: item for item in results}
    assert by_name["transcription.device"].status == "warn"
    assert by_name["diarization.device"].detail == "cuda"
