import json

from click.testing import CliRunner

from mt_linux.cli import cli


def test_cli_record_start_writes_request_and_reports_success(monkeypatch):
    written = {}

    def _write_request(request):
        written["request"] = request
        return None

    class _Result:
        status = "ok"
        message = "Manual recording started."
        session_id = "session-1"

    monkeypatch.setattr("mt_linux.cli.write_request", _write_request)
    monkeypatch.setattr("mt_linux.cli.wait_for_result", lambda request_id: _Result())
    runner = CliRunner()
    result = runner.invoke(cli, ["record", "start", "--title", "Ad Hoc", "--app", "slack"])
    assert result.exit_code == 0
    assert written["request"].action == "start"
    assert written["request"].title == "Ad Hoc"
    assert written["request"].app == "slack"
    assert "Manual recording started." in result.output
    assert "Session: session-1" in result.output


def test_cli_record_stop_reports_queued_job(monkeypatch):
    class _Result:
        status = "ok"
        message = "Manual recording stopped and queued."
        session_id = "session-1"

    monkeypatch.setattr("mt_linux.cli.write_request", lambda request: None)
    monkeypatch.setattr("mt_linux.cli.wait_for_result", lambda request_id: _Result())
    runner = CliRunner()
    result = runner.invoke(cli, ["record", "stop"])
    assert result.exit_code == 0
    assert "Manual recording stopped and queued." in result.output
    assert "Queued job: session-1" in result.output


def test_cli_record_status_reads_active_meeting(tmp_path, monkeypatch):
    state_path = tmp_path / "daemon_state.json"
    state_path.write_text(
        json.dumps(
            {
                "active_meeting": {
                    "session_id": "session-1",
                    "detection_method": "manual",
                    "app": "meet",
                    "title": "Ad Hoc Meet",
                }
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr("mt_linux.cli.STATE_FILE", state_path)
    runner = CliRunner()
    result = runner.invoke(cli, ["record", "status"])
    assert result.exit_code == 0
    assert "session-1  manual  meet  Ad Hoc Meet" in result.output
